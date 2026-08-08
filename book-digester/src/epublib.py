"""Minimal, dependency-free EPUB reader.

Reads an EPUB (a zip of XHTML) using only the Python standard library and
returns spine documents parsed into ordered *blocks* (headings and paragraphs)
plus a normalized text string per document with exact character offsets. The
digester and verifier both build offsets against this normalized text, so a
chunk's (char_start, char_end) round-trips to a verbatim source span.

Also parses the EPUB3 navigation document (nav.xhtml) into a Part/Chapter tree
when present. txt and pdf are handled as best-effort fallbacks in digest.py.
"""
from __future__ import annotations

import html
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

_WS = re.compile(r"\s+")
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = _HEADINGS | {"p"}


@dataclass
class Block:
    """A single structural block of text within a spine document."""

    kind: str  # "heading" or "para"
    level: int  # 1..6 for headings, 0 for paragraphs
    text: str  # normalized, whitespace-collapsed
    verse: str | None = None  # canonical "chapter:verse" if the block was verse-tagged
    char_start: int = 0  # offset into the document's normalized text
    char_end: int = 0


@dataclass
class SpineDoc:
    """One spine document (an itemref) with its parsed structure."""

    idref: str
    href: str  # path relative to the OPF directory, e.g. "chapter-01.xhtml"
    blocks: list[Block] = field(default_factory=list)
    normalized: str = ""  # the canonical source text; offsets index into this


@dataclass
class NavNode:
    title: str
    href: str | None = None
    children: list["NavNode"] = field(default_factory=list)


class _BlockExtractor(HTMLParser):
    """Collect headings and paragraphs in document order.

    Text inside a verse marker (``<span class="v" id="c1v1">1</span>``) is
    dropped from the block text but recorded as the block's canonical verse
    reference, so paragraph text reads naturally while verses stay addressable.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._cur: Block | None = None
        self._buf: list[str] = []
        self._in_verse = 0
        self._pending_verse: str | None = None

    @staticmethod
    def _verse_from_id(vid: str) -> str | None:
        m = re.fullmatch(r"c(\d+)v(\d+)", vid or "")
        return f"{m.group(1)}:{m.group(2)}" if m else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in _BLOCKS:
            self._flush()
            level = int(tag[1]) if tag in _HEADINGS else 0
            self._cur = Block(kind="heading" if level else "para", level=level, text="")
            self._buf = []
            self._pending_verse = None
        elif tag == "span" and "v" in a.get("class", "").split():
            self._in_verse += 1
            v = self._verse_from_id(a.get("id", ""))
            if v and self._cur is not None and self._pending_verse is None:
                self._pending_verse = v

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCKS:
            self._flush()
        elif tag == "span" and self._in_verse:
            self._in_verse -= 1

    def handle_data(self, data: str) -> None:
        if self._cur is not None and not self._in_verse:
            self._buf.append(data)

    def _flush(self) -> None:
        if self._cur is None:
            return
        text = _WS.sub(" ", "".join(self._buf)).strip()
        if text:
            self._cur.text = text
            self._cur.verse = self._pending_verse
            self.blocks.append(self._cur)
        self._cur = None
        self._buf = []
        self._pending_verse = None


def _parse_xhtml_blocks(data: bytes) -> list[Block]:
    p = _BlockExtractor()
    p.feed(data.decode("utf-8", "replace"))
    p._flush()
    return p.blocks


def _assign_offsets(blocks: list[Block], sep: str = "\n\n") -> str:
    """Join blocks into normalized text and stamp each block's char range."""
    pos = 0
    parts: list[str] = []
    for i, b in enumerate(blocks):
        if i:
            pos += len(sep)
        b.char_start = pos
        b.char_end = pos + len(b.text)
        parts.append(b.text)
        pos = b.char_end
    return sep.join(parts)


class Epub:
    def __init__(self, path: str) -> None:
        self.path = path
        self.zip = zipfile.ZipFile(path, "r")
        self.opf_path = self._find_opf()
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.manifest: dict[str, dict] = {}
        self.spine: list[str] = []  # idrefs in reading order
        self.metadata: dict[str, str] = {}
        self._nav_href: str | None = None
        self._read_opf()

    # -- OPF / container ----------------------------------------------------
    def _find_opf(self) -> str:
        data = self.zip.read("META-INF/container.xml")
        root = ET.fromstring(data)
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        el = root.find(".//c:rootfile", ns)
        if el is None or not el.get("full-path"):
            raise ValueError("container.xml has no rootfile")
        return el.get("full-path")

    def _read_opf(self) -> None:
        root = ET.fromstring(self.zip.read(self.opf_path))
        opf = "http://www.idpf.org/2007/opf"
        dc = "http://purl.org/dc/elements/1.1/"
        for tag in ("title", "creator", "language", "identifier"):
            el = root.find(f".//{{{dc}}}{tag}")
            if el is not None and el.text:
                self.metadata[tag] = el.text.strip()
        for item in root.findall(f".//{{{opf}}}manifest/{{{opf}}}item"):
            iid = item.get("id")
            self.manifest[iid] = {
                "href": item.get("href"),
                "media_type": item.get("media-type"),
                "properties": item.get("properties", ""),
            }
            if "nav" in (item.get("properties") or "").split():
                self._nav_href = item.get("href")
        for ref in root.findall(f".//{{{opf}}}spine/{{{opf}}}itemref"):
            if ref.get("linear", "yes") != "no":
                self.spine.append(ref.get("idref"))

    def _read_rel(self, href: str) -> bytes:
        arc = posixpath.normpath(posixpath.join(self.opf_dir, href))
        return self.zip.read(arc)

    # -- Public API ---------------------------------------------------------
    def spine_docs(self) -> list[SpineDoc]:
        docs: list[SpineDoc] = []
        for idref in self.spine:
            item = self.manifest.get(idref)
            if not item or "xhtml" not in (item.get("media_type") or ""):
                continue
            blocks = _parse_xhtml_blocks(self._read_rel(item["href"]))
            normalized = _assign_offsets(blocks)
            docs.append(SpineDoc(idref=idref, href=item["href"],
                                 blocks=blocks, normalized=normalized))
        return docs

    def nav_tree(self) -> list[NavNode]:
        """Parse nav.xhtml's toc into a Part/Chapter tree, if present."""
        if not self._nav_href:
            return []
        try:
            data = self._read_rel(self._nav_href).decode("utf-8", "replace")
        except KeyError:
            return []
        return _parse_nav(data)


# -- nav.xhtml parsing (a nested <ol><li> tree) -----------------------------
class _NavParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[NavNode] = []
        self.roots: list[NavNode] = []
        self._in_toc = False
        self._depth = 0
        self._cur_href: str | None = None
        self._buf: list[str] = []
        self._collecting = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "nav" and a.get("epub:type") == "toc":
            self._in_toc = True
        if not self._in_toc:
            return
        if tag == "li":
            node = NavNode(title="")
            if self.stack:
                self.stack[-1].children.append(node)
            else:
                self.roots.append(node)
            self.stack.append(node)
            self._buf = []
            self._collecting = True
        elif tag == "a":
            self._cur_href = a.get("href")
            self._buf = []
            self._collecting = True
        elif tag == "span":
            self._buf = []
            self._collecting = True

    def handle_endtag(self, tag):
        if not self._in_toc:
            return
        if tag == "nav":
            self._in_toc = False
        elif tag in ("a", "span"):
            if self.stack and self._collecting:
                title = _WS.sub(" ", "".join(self._buf)).strip()
                if title and not self.stack[-1].title:
                    self.stack[-1].title = title
                    if tag == "a":
                        self.stack[-1].href = self._cur_href
            self._collecting = False
            self._cur_href = None
        elif tag == "li":
            if self.stack:
                self.stack.pop()

    def handle_data(self, data):
        if self._collecting:
            self._buf.append(data)


def _parse_nav(data: str) -> list[NavNode]:
    p = _NavParser()
    p.feed(data)
    return p.roots


def normalize_plaintext(text: str) -> tuple[list[Block], str]:
    """Best-effort structuring of a .txt book into blocks.

    Blank-line-separated groups become paragraphs; a short line in Title Case
    or matching a chapter pattern becomes a heading. Structural confidence for
    txt is 'low' (recorded by the digester).
    """
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    groups = re.split(r"\n\s*\n", raw)
    blocks: list[Block] = []
    chap = re.compile(r"^\s*(chapter|part|book)\b", re.I)
    for g in groups:
        t = _WS.sub(" ", g).strip()
        if not t:
            continue
        is_head = len(t) <= 70 and (chap.match(t) or t.istitle())
        blocks.append(Block(kind="heading" if is_head else "para",
                            level=1 if is_head else 0, text=t))
    return blocks, _assign_offsets(blocks)
