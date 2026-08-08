#!/usr/bin/env python3
"""Reference consumer: answer queries against an index without the book.

Demonstrates the contract in SCHEMA.md. A downstream workflow (e.g. a daily
scripture-study builder) integrates against exactly these three access paths
and never opens the source book.

Usage:
    python3 tools/query.py library/<slug> chapter "Chapter 3. On Storms"
    python3 tools/query.py library/<slug> reference 3:7
    python3 tools/query.py library/<slug> topic patience
"""
from __future__ import annotations

import json
import os
import sys


def load_index(book_dir):
    with open(os.path.join(book_dir, "index.json"), encoding="utf-8") as f:
        return json.load(f)


def load_chunk(book_dir, cid):
    with open(os.path.join(book_dir, "chunks", f"{cid}.json"), encoding="utf-8") as f:
        return json.load(f)


def _find_chapter(nodes, title):
    for n in nodes:
        if n.get("type") == "chapter" and n.get("title") == title:
            return n
        hit = _find_chapter(n.get("children", []), title)
        if hit:
            return hit
    return None


def by_chapter(index, title):
    node = _find_chapter(index["structure"], title)
    if not node:
        return []
    return [s["chunk_id"] for s in node.get("children", []) if "chunk_id" in s]


def by_reference(index, ref):
    cid = index["references_index"].get(ref)
    return [cid] if cid else []


def by_topic(index, topic):
    return index["topics_index"].get(topic.lower(), [])


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 3:
        print(__doc__)
        return 2
    book_dir, kind, arg = argv[0], argv[1], argv[2]
    index = load_index(book_dir)
    ids = {"chapter": by_chapter, "reference": by_reference,
           "topic": by_topic}[kind](index, arg)
    print(f"query {kind}={arg!r} -> {ids}")
    for cid in ids:
        c = load_chunk(book_dir, cid)
        print(f"\n[{cid}] {c['title']}  ({c['word_count']} words)")
        print(f"  summary: {c['summary']}")
    return 0 if ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
