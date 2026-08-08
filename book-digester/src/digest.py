#!/usr/bin/env python3
"""book-digester: turn a book file into a structure-aligned knowledge base.

Reads an .epub (first-class) or .txt (best-effort) and produces, under
``library/<book-slug>/``:

    index.json      the queryable product: structure tree, chunk records,
                    topics_index, references_index, cross_reference_index
    coverage.json   script-computed word accounting + named exclusions
    chunks/<id>.json  one file per chunk, carrying the verbatim source span
                      and full provenance (spine item, char offsets, sha256)

Design guarantees:
  * Deterministic. chunk_ids derive from structure (spine position + section
    index), never run order. Re-running yields byte-identical output.
  * Provenance. char_start/char_end index the spine document's *normalized*
    text; chunk.text is exactly that span; source_sha256 is that text's hash.
  * No fabrication. summaries and topics are extractive (verbatim from the
    chunk), so index accuracy is faithful by construction.

Dependency-free: standard library only. Usage:
    python3 src/digest.py fixtures/wayfarers-compass.epub
    python3 src/digest.py <book> --out library --slug my-book
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import epublib  # noqa: E402

SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "book-digester 1.0.0"

# Spine items matching these (by id or href stem) are front/back matter we
# exclude from chunking. Each exclusion is recorded with its reason.
EXCLUDE_PATTERNS = [
    (re.compile(r"cover", re.I), "cover page (no substantive body text)"),
    (re.compile(r"copyright|colophon", re.I), "copyright/colophon page"),
    (re.compile(r"^title(page)?$|titlepage", re.I), "title page"),
    (re.compile(r"\b(toc|nav|contents)\b", re.I), "navigation/table of contents"),
    (re.compile(r"dedication|acknowledg|index$", re.I), "front/back matter"),
]

_STOPWORDS = set("""
a an the and or but if then else of to in on at by for with without from into
over under again further is are was were be been being do does did doing have
has had having i you he she it we they them his her its our their this that
these those as not no nor so too very can will just than which who whom what
when where why how all any both each few more most other some such only own
same up down out off above below because about against between through during
before after here there once your my me him us who whose also may might must
shall should would could one two three does don t s
""".split()) | set("""
already enough ever never always often sometimes still yet quite rather almost
nearly else whole kind sort thing things much many every another
behind ahead around beyond along across toward towards within upon
contains contain arrives arrive given gives give looks look looked
comes come coming goes going gone made makes make take takes taken taking
become becomes became being having gets get got kept keep
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_SENT = re.compile(r"(?<=[.!?])\s+")
_XREF = re.compile(r"(?:cf\.|see|compare)\s+(\d+):(\d+)", re.I)


def slugify(text: str) -> str:
    s = text.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s) or "book"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def extractive_summary(body: str, max_words: int = 30) -> str:
    """First sentence(s) of the body, verbatim, up to a word budget."""
    sents = _SENT.split(body.strip())
    out, used = [], 0
    for s in sents:
        w = word_count(s)
        if out and used + w > max_words:
            break
        out.append(s.strip())
        used += w
        if used >= max_words:
            break
    return " ".join(out).strip()


def extract_topics(body: str, k: int = 5) -> list[str]:
    """Deterministic keyword extraction. Every topic occurs in the body."""
    counts: dict[str, int] = {}
    for w in _WORD.findall(body.lower()):
        if len(w) < 4 or w in _STOPWORDS:
            continue
        counts[w] = counts.get(w, 0) + 1
    # Sort by frequency desc, then alphabetically for determinism.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:k]]


def is_excluded(idref: str, href: str) -> str | None:
    stem = os.path.splitext(os.path.basename(href))[0]
    for pat, reason in EXCLUDE_PATTERNS:
        if pat.search(idref) or pat.search(stem):
            return reason
    return None


# --- chunking ---------------------------------------------------------------
def chunk_spine_doc(doc: epublib.SpineDoc, spine_index: int, book_slug: str):
    """Split one spine document into section-aligned chunks.

    Sectioning adapts to the heading levels actually present. When a document
    has two or more heading levels (e.g. an EPUB chapter with an <h1> title and
    <h2> sections), it splits at the section level and the shallower chapter
    heading folds into the first section. When only one heading level is present
    (e.g. a best-effort .txt where each "Chapter N" is a lone heading), it
    splits at that level. Documents with no headings become a single chunk.
    Paragraphs are never split.
    """
    blocks = doc.blocks
    if not blocks:
        return []

    heading_levels = sorted({b.level for b in blocks if b.kind == "heading"})
    if not heading_levels:
        chapter_level = section_level = None
    else:
        chapter_level = heading_levels[0]
        section_level = heading_levels[1] if len(heading_levels) >= 2 else heading_levels[0]

    # Section boundaries: a new chunk begins at every section-level heading.
    starts = [0]
    if section_level is not None:
        for i, b in enumerate(blocks):
            if i > 0 and b.kind == "heading" and b.level == section_level:
                starts.append(i)
    starts = sorted(set(starts))
    raw_bounds = list(zip(starts, starts[1:] + [len(blocks)]))

    # Coalesce heading-only leading groups forward (e.g. a lone <h1> chapter
    # title before the first <h2>) so no chunk is title-only. Skip this when
    # there is only one heading level, so each heading stays its own chunk.
    if section_level is not None and section_level != chapter_level:
        bounds = []
        pending_start = None
        for k, (a, z) in enumerate(raw_bounds):
            start = pending_start if pending_start is not None else a
            has_para = any(bl.kind != "heading" for bl in blocks[a:z])
            if not has_para and k < len(raw_bounds) - 1:
                pending_start = start
                continue
            bounds.append((start, z))
            pending_start = None
        if pending_start is not None:
            bounds.append((pending_start, len(blocks)))
    else:
        bounds = raw_bounds

    chunks = []
    for sec_idx, (a, z) in enumerate(bounds):
        group = blocks[a:z]
        char_start = group[0].char_start
        char_end = group[-1].char_end
        text = doc.normalized[char_start:char_end]

        # chapter title = the nearest chapter-level heading at or before this
        # chunk's start; section title = the first section-level heading inside
        # the group (only meaningful when chapters and sections differ).
        chapter_title = None
        if chapter_level is not None:
            for b in blocks[:z]:
                if b.kind == "heading" and b.level == chapter_level \
                        and b.char_start <= char_start:
                    chapter_title = b.text
        section_title = None
        if section_level is not None and section_level != chapter_level:
            section_title = next(
                (b.text for b in group
                 if b.kind == "heading" and b.level == section_level), None)
        title = section_title or chapter_title or f"Section {sec_idx + 1}"

        # Body = non-heading text, used for summary/topics (no titles leak in).
        body = "\n\n".join(b.text for b in group if b.kind != "heading").strip()
        body = body or text

        verses = [b.verse for b in group if b.verse]
        verse_range = None
        if verses:
            nums = [tuple(int(x) for x in v.split(":")) for v in verses]
            ch = nums[0][0]
            verse_range = {"chapter": ch,
                           "start": min(n[1] for n in nums),
                           "end": max(n[1] for n in nums)}

        cross = sorted({f"{m.group(1)}:{m.group(2)}" for m in _XREF.finditer(text)})

        chunk_id = f"{spine_index:03d}-{sec_idx:02d}"
        chunks.append({
            "chunk_id": chunk_id,
            "book_slug": book_slug,
            "title": title,
            "chapter_title": chapter_title,
            "section_title": section_title,
            "spine_item": doc.href,
            "char_start": char_start,
            "char_end": char_end,
            "source_sha256": sha256_text(doc.normalized),
            "word_count": word_count(text),
            "verses": verse_range,
            "contains_refs": verses,
            "cross_references": cross,
            "summary": extractive_summary(body),
            "topics": extract_topics(body),
            "text": text,
        })
    return chunks


# --- structure tree ---------------------------------------------------------
def build_structure(nav: list[epublib.NavNode], chunks_by_href: dict, docs):
    """Build a Part/Chapter/Section tree, mapping sections to chunk_ids.

    Uses the EPUB nav for Part/Chapter grouping and titles when available,
    falling back to spine order. Sections come from the chunks themselves.
    """
    def sections_for(href):
        out = []
        for c in chunks_by_href.get(href, []):
            out.append({
                "type": "section",
                "title": c["section_title"] or c["chapter_title"] or c["title"],
                "chunk_id": c["chunk_id"],
            })
        return out

    href_by_stem = {os.path.splitext(os.path.basename(d.href))[0]: d.href
                    for d in docs}

    def resolve(href):
        if href is None:
            return None
        base = href.split("#")[0]
        stem = os.path.splitext(os.path.basename(base))[0]
        return href_by_stem.get(stem)

    tree = []
    if nav:
        for part in nav:
            node = {"type": "part", "title": part.title, "children": []}
            children_src = part.children or [part]
            for chap in children_src:
                href = resolve(chap.href)
                if href is None or not chunks_by_href.get(href):
                    continue
                node["children"].append({
                    "type": "chapter",
                    "title": chap.title,
                    "spine_item": href,
                    "children": sections_for(href),
                })
            if node["children"]:
                tree.append(node)
    if not tree:
        # Fallback: flat chapter list from spine order.
        for d in docs:
            secs = sections_for(d.href)
            if not secs:
                continue
            title = next((c["chapter_title"] for c in chunks_by_href[d.href]
                          if c["chapter_title"]), d.href)
            tree.append({"type": "chapter", "title": title,
                         "spine_item": d.href, "children": secs})
    return tree


# --- main pipeline ----------------------------------------------------------
def digest(path: str, out_root: str, slug: str | None = None) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        result = _digest_epub(path, slug)
    elif ext == ".txt":
        result = _digest_txt(path, slug)
    else:
        raise SystemExit(f"unsupported format: {ext} (epub, txt supported)")

    index, chunks, coverage = result
    book_slug = index["book"]["slug"]
    book_dir = os.path.join(out_root, book_slug)
    chunks_dir = os.path.join(book_dir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    # Clear stale chunk files so re-runs are clean.
    for fn in os.listdir(chunks_dir):
        if fn.endswith(".json"):
            os.remove(os.path.join(chunks_dir, fn))

    for c in chunks:
        with open(os.path.join(chunks_dir, f'{c["chunk_id"]}.json'), "w",
                  encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    _write_json(os.path.join(book_dir, "index.json"), index)
    _write_json(os.path.join(book_dir, "coverage.json"), coverage)
    return {"book_dir": book_dir, "chunks": len(chunks),
            "coverage": coverage["coverage_ratio"], "slug": book_slug}


def _write_json(path: str, obj: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _assemble(book_meta, docs, nav, chunk_lists, excluded, source_words):
    """Common assembly of index + coverage from parsed chunks."""
    chunks_by_href: dict = {}
    all_chunks = []
    for doc, cl in chunk_lists:
        chunks_by_href[doc.href] = cl
        all_chunks.extend(cl)
    all_chunks.sort(key=lambda c: c["chunk_id"])

    structure = build_structure(nav, chunks_by_href, docs)

    # Inverted indexes.
    topics_index: dict = {}
    references_index: dict = {}  # canonical: "C:V" -> chunk containing that verse
    xref_index: dict = {}        # "C:V" -> chunks that cite it in prose
    for c in all_chunks:
        for t in c["topics"]:
            topics_index.setdefault(t, [])
            if c["chunk_id"] not in topics_index[t]:
                topics_index[t].append(c["chunk_id"])
        for ref in c["contains_refs"]:
            references_index[ref] = c["chunk_id"]
        for xr in c["cross_references"]:
            xref_index.setdefault(xr, [])
            if c["chunk_id"] not in xref_index[xr]:
                xref_index[xr].append(c["chunk_id"])
    topics_index = {k: sorted(v) for k, v in sorted(topics_index.items())}
    references_index = dict(sorted(references_index.items(),
                                   key=lambda kv: tuple(int(x) for x in kv[0].split(":"))))
    xref_index = {k: sorted(v) for k, v in sorted(xref_index.items())}

    # Index chunk records omit the full text (that lives in chunk files).
    index_chunks = [{k: v for k, v in c.items() if k != "text"}
                    for c in all_chunks]

    mapped_words = sum(c["word_count"] for c in all_chunks)
    substantive = source_words - sum(e["words"] for e in excluded)
    ratio = (mapped_words / substantive) if substantive else 1.0

    n_chapters = sum(1 for _ in _iter_type(structure, "chapter"))
    n_sections = len(all_chunks)

    index = {
        "schema_version": SCHEMA_VERSION,
        "book": book_meta,
        "counts": {"chunks": len(all_chunks), "chapters": n_chapters,
                   "sections": n_sections,
                   "topics": len(topics_index),
                   "references": len(references_index)},
        "structure": structure,
        "chunks": index_chunks,
        "topics_index": topics_index,
        "references_index": references_index,
        "cross_reference_index": xref_index,
    }

    included = []
    for doc, cl in chunk_lists:
        included.append({"spine_item": doc.href,
                         "words": word_count(doc.normalized),
                         "chunks": len(cl)})
    coverage = {
        "book_slug": book_meta["slug"],
        "total_words": source_words,
        "substantive_words": substantive,
        "mapped_words": mapped_words,
        "unmapped_words": max(substantive - mapped_words, 0),
        "coverage_ratio": round(ratio, 6),
        "threshold": 0.99,
        "passes": ratio >= 0.99,
        "included_spine_items": included,
        "excluded_spine_items": excluded,
    }
    return index, all_chunks, coverage


def _iter_type(tree, typ):
    for node in tree:
        if node.get("type") == typ:
            yield node
        for child in node.get("children", []):
            yield from _iter_type([child], typ)


def _digest_epub(path: str, slug: str | None):
    book = epublib.Epub(path)
    md = book.metadata
    title = md.get("title", os.path.basename(path))
    book_slug = slug or slugify(title.split(":")[0])
    docs = book.spine_docs()
    nav = book.nav_tree()

    excluded = []
    chunk_lists = []
    source_words = 0
    for si, doc in enumerate(docs):
        source_words += word_count(doc.normalized)
        reason = is_excluded(doc.idref, doc.href)
        if reason:
            excluded.append({"spine_item": doc.href, "reason": reason,
                             "words": word_count(doc.normalized)})
            continue
        cl = chunk_spine_doc(doc, si, book_slug)
        if cl:
            chunk_lists.append((doc, cl))

    book_meta = {
        "slug": book_slug,
        "title": md.get("title", title),
        "author": md.get("creator", "Unknown"),
        "language": md.get("language", "und"),
        "identifier": md.get("identifier", ""),
        "source_format": "epub",
        "source_sha256": sha256_file(path),
        "structural_confidence": "high",
        "generated_by": TOOL_VERSION,
    }
    return _assemble(book_meta, docs, nav, chunk_lists, excluded, source_words)


def _digest_txt(path: str, slug: str | None):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    blocks, normalized = epublib.normalize_plaintext(raw)
    doc = epublib.SpineDoc(idref="txt", href=os.path.basename(path),
                           blocks=blocks, normalized=normalized)
    title = os.path.splitext(os.path.basename(path))[0]
    book_slug = slug or slugify(title)
    cl = chunk_spine_doc(doc, 0, book_slug)
    book_meta = {
        "slug": book_slug, "title": title, "author": "Unknown",
        "language": "und", "identifier": "",
        "source_format": "txt", "source_sha256": sha256_file(path),
        "structural_confidence": "low", "generated_by": TOOL_VERSION,
    }
    return _assemble(book_meta, [doc], [], [(doc, cl)], [],
                     word_count(normalized))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Digest a book into a knowledge base.")
    ap.add_argument("book", help="path to .epub or .txt")
    ap.add_argument("--out", default="library", help="output root (default: library)")
    ap.add_argument("--slug", default=None, help="override book slug")
    args = ap.parse_args(argv)

    if not os.path.exists(args.book):
        print(f"error: no such file: {args.book}", file=sys.stderr)
        return 2
    res = digest(args.book, args.out, args.slug)
    print(f"digested -> {res['book_dir']}")
    print(f"  chunks:   {res['chunks']}")
    print(f"  coverage: {res['coverage']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
