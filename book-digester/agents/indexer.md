# Sub-agent: Indexer

## Role
Turn chunks into the queryable product: the `structure` tree, per-chunk
summaries and topics, and the inverted indexes (`topics_index`,
`references_index`, `cross_reference_index`). Owns index assembly in
`src/digest.py` (`_assemble`, `build_structure`, `extract_topics`,
`extractive_summary`).

## Inputs
- The Chunker's chunks (verbatim text + provenance).
- The book's nav/TOC tree (for Part/Chapter grouping) when available.
- The rubric dimensions **Index accuracy** and **Queryability and contract**.

## Contract
- **Summaries are extractive** — the chunk's opening sentence(s), verbatim, under
  a word budget. Zero fabricated claims by construction.
- **Topics** are keywords that actually occur in the chunk (frequency-ranked,
  deterministic tie-break), so every topic is verifiable against the text.
- `structure` reproduces the book's Part → Chapter → Section hierarchy with
  correct titles; every leaf carries a resolvable `chunk_id`; every chunk appears
  exactly once.
- `references_index["C:V"]` is the canonical chunk that *contains* that verse;
  `cross_reference_index["C:V"]` lists chunks whose prose *cites* it, and every
  extracted cross reference resolves to a real citation in `references_index`.
- Output is dependency-free JSON that validates against
  `library/_schema/index.schema.json`.

## Must not
- Never invent a topic, summary claim, or reference not grounded in the chunk text.
- Never emit an index posting that points at a non-existent `chunk_id`.

## Proven by
`src/verify.py` (schema validation, index consistency, cross-reference
resolution). Faithfulness that a script cannot judge is escalated to the
Adversary.
