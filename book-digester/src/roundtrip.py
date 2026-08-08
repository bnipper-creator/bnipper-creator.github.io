#!/usr/bin/env python3
"""Reconstruct each chapter verbatim from its chunks and match the source.

For every chapter in the structure tree, concatenate its chunks' text in
reading order and compare the result, character for character, to the exact
normalized source span the chunks came from. Exits non-zero on any mismatch.

This is the strongest provenance guarantee: a consumer holding only the chunk
files can rebuild any chapter and know it is the real text, byte for byte.

Usage:
    python3 src/roundtrip.py library/<slug> [--source <book file>]
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import epublib  # noqa: E402

SEP = "\n\n"  # the block separator digest.py uses to build normalized text


def _chapters(nodes):
    for n in nodes:
        if n.get("type") == "chapter":
            yield n
        yield from _chapters(n.get("children", []))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("book_dir")
    ap.add_argument("--source", default=None)
    args = ap.parse_args(argv)

    with open(os.path.join(args.book_dir, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    slug = index["book"]["slug"]
    source = args.source or os.path.join(
        os.path.dirname(os.path.dirname(args.book_dir)), "fixtures", f"{slug}.epub")
    if not os.path.exists(source):
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2

    norm = {d.href: d.normalized for d in epublib.Epub(source).spine_docs()}
    chunks_dir = os.path.join(args.book_dir, "chunks")

    def load(cid):
        with open(os.path.join(chunks_dir, f"{cid}.json"), encoding="utf-8") as f:
            return json.load(f)

    failures = 0
    checked = 0
    for chap in _chapters(index["structure"]):
        cids = [s["chunk_id"] for s in chap.get("children", []) if "chunk_id" in s]
        if not cids:
            continue
        parts = [load(cid) for cid in cids]
        href = parts[0]["spine_item"]
        rebuilt = SEP.join(p["text"] for p in parts)
        span_start = parts[0]["char_start"]
        span_end = parts[-1]["char_end"]
        original = norm[href][span_start:span_end]
        ok = rebuilt == original
        checked += 1
        mark = "ok " if ok else "FAIL"
        print(f"  [{mark}] {chap['title']} <- {', '.join(cids)}")
        if not ok:
            failures += 1

    print(f"roundtrip: {checked} chapters, {failures} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
