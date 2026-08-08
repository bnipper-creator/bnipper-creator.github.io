#!/usr/bin/env python3
"""Mechanical verification of a digested book. No self-attestation.

Proves the invariants a script *can* prove, exiting non-zero on any failure:

  1. index.json validates against library/_schema/index.schema.json
  2. every chunk_id in the index resolves to a chunks/<id>.json and back
     (no dangling references, no orphan chunk files)
  3. provenance round-trips: for every chunk, the spine item's normalized
     source (re-derived independently from the book) hashes to the stored
     source_sha256, and source[char_start:char_end] == the chunk's text
  4. the structure tree references every chunk exactly once
  5. topics/references/cross-reference indexes are consistent, and every
     extracted cross reference resolves to a real citation
  6. coverage.json recomputes to the stored numbers and clears the 99% gate
  7. determinism: re-running the digester yields byte-identical artifacts

Usage:
    python3 src/verify.py library/<slug> [--source <book file>]
If --source is omitted, fixtures/<slug>.epub is tried.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import epublib  # noqa: E402
import digest  # noqa: E402

SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "library", "_schema",
                           "index.schema.json")


# --- a small, honest draft-07-subset JSON Schema validator -----------------
class SchemaError(Exception):
    pass


def _resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"unsupported $ref: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate(inst, schema, root, path, errs):
    if "$ref" in schema:
        schema = _resolve_ref(root, schema["$ref"])

    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else types
        if not any(_is_type(inst, t) for t in types):
            errs.append(f"{path}: expected type {types}, got {type(inst).__name__}")
            return  # further checks are unreliable once the type is wrong

    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in enum {schema['enum']}")
    if "pattern" in schema and isinstance(inst, str):
        if not re.search(schema["pattern"], inst):
            errs.append(f"{path}: {inst!r} does not match /{schema['pattern']}/")
    if "minimum" in schema and isinstance(inst, (int, float)):
        if inst < schema["minimum"]:
            errs.append(f"{path}: {inst} < minimum {schema['minimum']}")

    if isinstance(inst, dict):
        for req in schema.get("required", []):
            if req not in inst:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for k, v in inst.items():
            if k in props:
                _validate(v, props[k], root, f"{path}.{k}", errs)
            else:
                ap = schema.get("additionalProperties", True)
                if ap is False:
                    errs.append(f"{path}: additional property '{k}' not allowed")
                elif isinstance(ap, dict):
                    _validate(v, ap, root, f"{path}.{k}", errs)
    elif isinstance(inst, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(inst):
                _validate(item, item_schema, root, f"{path}[{i}]", errs)


def _is_type(inst, t) -> bool:
    if t == "object":
        return isinstance(inst, dict)
    if t == "array":
        return isinstance(inst, list)
    if t == "string":
        return isinstance(inst, str)
    if t == "integer":
        return isinstance(inst, int) and not isinstance(inst, bool)
    if t == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    if t == "boolean":
        return isinstance(inst, bool)
    if t == "null":
        return inst is None
    return False


def validate_schema(instance, schema) -> list[str]:
    errs: list[str] = []
    _validate(instance, schema, schema, "$", errs)
    return errs


# --- verification checks ----------------------------------------------------
class Verifier:
    def __init__(self, book_dir: str, source: str | None):
        self.book_dir = book_dir
        self.chunks_dir = os.path.join(book_dir, "chunks")
        self.index = self._load("index.json")
        self.coverage = self._load("coverage.json")
        self.slug = self.index["book"]["slug"]
        self.source = source or self._guess_source()
        self.failures: list[str] = []
        self.checks = 0

    def _load(self, name):
        with open(os.path.join(self.book_dir, name), encoding="utf-8") as f:
            return json.load(f)

    def _guess_source(self):
        cand = os.path.join(os.path.dirname(os.path.dirname(self.book_dir)),
                            "fixtures", f"{self.slug}.epub")
        return cand if os.path.exists(cand) else None

    def check(self, cond, msg):
        self.checks += 1
        if not cond:
            self.failures.append(msg)
        return cond

    # 1 -------------------------------------------------------------------
    def schema(self):
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        errs = validate_schema(self.index, schema)
        self.check(not errs, "schema validation failed:\n    "
                   + "\n    ".join(errs[:20]))

    # 2 & 4 ---------------------------------------------------------------
    def chunk_files_and_structure(self):
        idx_ids = {c["chunk_id"] for c in self.index["chunks"]}
        file_ids = {fn[:-5] for fn in os.listdir(self.chunks_dir)
                    if fn.endswith(".json")}
        self.check(idx_ids == file_ids,
                   f"chunk id/file mismatch: only-in-index={idx_ids - file_ids} "
                   f"only-on-disk={file_ids - idx_ids}")
        # structure references every chunk exactly once
        struct_ids = list(self._structure_chunk_ids(self.index["structure"]))
        self.check(len(struct_ids) == len(set(struct_ids)),
                   "structure references a chunk more than once")
        self.check(set(struct_ids) == idx_ids,
                   f"structure/chunk set mismatch: "
                   f"missing={idx_ids - set(struct_ids)} "
                   f"extra={set(struct_ids) - idx_ids}")

    def _structure_chunk_ids(self, nodes):
        for n in nodes:
            if "chunk_id" in n:
                yield n["chunk_id"]
            yield from self._structure_chunk_ids(n.get("children", []))

    # 3 ------------------------------------------------------------------
    def provenance(self):
        if not self.source:
            self.failures.append("no source book available for provenance check "
                                 "(pass --source)")
            return
        norm = self._normalized_by_href()
        for cid in sorted({c["chunk_id"] for c in self.index["chunks"]}):
            with open(os.path.join(self.chunks_dir, f"{cid}.json"),
                      encoding="utf-8") as f:
                c = json.load(f)
            href = c["spine_item"]
            src = norm.get(href)
            if not self.check(src is not None,
                              f"{cid}: spine_item {href} not found in source"):
                continue
            self.check(digest.sha256_text(src) == c["source_sha256"],
                       f"{cid}: source_sha256 mismatch for {href}")
            a, z = c["char_start"], c["char_end"]
            self.check(0 <= a < z <= len(src),
                       f"{cid}: offsets [{a},{z}] out of range 0..{len(src)}")
            if 0 <= a < z <= len(src):
                self.check(src[a:z] == c["text"],
                           f"{cid}: text does not match source span [{a},{z}]")
            self.check(digest.word_count(c["text"]) == c["word_count"],
                       f"{cid}: word_count mismatch")

    def _normalized_by_href(self):
        if self.source.lower().endswith(".txt"):
            with open(self.source, encoding="utf-8", errors="replace") as f:
                _, normalized = epublib.normalize_plaintext(f.read())
            return {os.path.basename(self.source): normalized}
        book = epublib.Epub(self.source)
        return {d.href: d.normalized for d in book.spine_docs()}

    # 5 ------------------------------------------------------------------
    def indexes(self):
        ids = {c["chunk_id"]: c for c in self.index["chunks"]}
        # topics_index postings resolve, and reflect each chunk's topics
        for topic, postings in self.index["topics_index"].items():
            for cid in postings:
                self.check(cid in ids, f"topics_index[{topic}] -> unknown {cid}")
        for cid, c in ids.items():
            for t in c["topics"]:
                self.check(cid in self.index["topics_index"].get(t, []),
                           f"chunk {cid} topic '{t}' missing from topics_index")
        # references_index: canonical verse -> chunk that contains it
        for ref, cid in self.index["references_index"].items():
            self.check(cid in ids, f"references_index[{ref}] -> unknown {cid}")
            self.check(ref in ids[cid]["contains_refs"],
                       f"references_index[{ref}] -> {cid} which lacks that verse")
        # every extracted cross reference resolves to a real citation
        for cid, c in ids.items():
            for xr in c["cross_references"]:
                self.check(xr in self.index["references_index"],
                           f"chunk {cid} cross reference {xr} resolves to nothing")
                self.check(cid in self.index["cross_reference_index"].get(xr, []),
                           f"cross_reference_index missing {cid} under {xr}")

    # 6 ------------------------------------------------------------------
    def coverage_recompute(self):
        cov = self.coverage
        mapped = sum(c["word_count"] for c in self.index["chunks"])
        self.check(mapped == cov["mapped_words"],
                   f"coverage mapped_words {cov['mapped_words']} != recomputed {mapped}")
        ratio = mapped / cov["substantive_words"] if cov["substantive_words"] else 1.0
        self.check(abs(ratio - cov["coverage_ratio"]) < 1e-6,
                   "coverage_ratio does not recompute")
        self.check(cov["coverage_ratio"] >= 0.99,
                   f"coverage {cov['coverage_ratio']:.4f} below 0.99 gate")
        self.check(cov.get("passes") is True, "coverage.passes is not true")
        # every excluded item names a reason
        for e in cov["excluded_spine_items"]:
            self.check(bool(e.get("reason")),
                       f"excluded item {e.get('spine_item')} has no reason")

    # 7 ------------------------------------------------------------------
    def determinism(self):
        if not self.source:
            return
        with tempfile.TemporaryDirectory() as tmp:
            digest.digest(self.source, tmp, self.slug)
            a_dir = self.book_dir
            b_dir = os.path.join(tmp, self.slug)
            a_files = self._tree(a_dir)
            b_files = self._tree(b_dir)
            self.check(a_files.keys() == b_files.keys(),
                       "determinism: file set differs on re-run")
            for rel in a_files.keys() & b_files.keys():
                self.check(a_files[rel] == b_files[rel],
                           f"determinism: {rel} differs on re-run")

    def _tree(self, root):
        out = {}
        for base, _, files in os.walk(root):
            for fn in files:
                p = os.path.join(base, fn)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, root)] = f.read()
        return out

    def run(self):
        self.schema()
        self.chunk_files_and_structure()
        self.provenance()
        self.indexes()
        self.coverage_recompute()
        self.determinism()
        return not self.failures


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Verify a digested book.")
    ap.add_argument("book_dir")
    ap.add_argument("--source", default=None)
    args = ap.parse_args(argv)

    v = Verifier(args.book_dir, args.source)
    ok = v.run()
    print(f"book-digester verify: {args.book_dir}")
    print(f"  source:  {v.source or '(none)'}")
    print(f"  checks:  {v.checks}")
    if ok:
        print("  RESULT:  PASS (all mechanical invariants hold)")
        return 0
    print(f"  RESULT:  FAIL ({len(v.failures)} failing)")
    for f in v.failures:
        print(f"    - {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
