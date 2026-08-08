# Sub-agent: Chunker

## Role
Split a parsed book into structure-aligned chunks and emit their provenance.
Owns `src/digest.py`'s chunking logic (`chunk_spine_doc`) and the block/offset
model in `src/epublib.py`.

## Inputs
- One book file (`.epub` first-class, `.txt` best-effort).
- The rubric dimensions **Structural fidelity**, **Coverage**, **Provenance**.

## Contract (what "done" means for this agent)
- A new chunk begins only at a heading boundary; **no chunk splits a paragraph**.
- Boundaries adapt to the heading levels present: split at the section level, fold
  a shallower chapter heading into its first section; single-level docs split at
  that level.
- Each chunk records `spine_item`, `char_start`, `char_end`, `source_sha256`, and
  `word_count`, where offsets index the spine item's **normalized** text and
  `normalized[char_start:char_end]` is exactly the chunk text.
- `chunk_id` is `NNN-SS`, derived from structure (spine position + section index),
  never from run order → identical on re-run.
- Front/back matter (cover, copyright, nav) is excluded and reported, not chunked.

## Must not
- Never paraphrase, reflow, or rewrite source text — chunks are verbatim spans.
- Never let `chunk_id` depend on timestamps, iteration order of sets/dicts, or
  randomness.

## Proven by
`src/verify.py` (offset/hash/round-trip/determinism checks) and
`src/roundtrip.py`. The Chunker asserts nothing it cannot prove with those.
