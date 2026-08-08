# RUBRIC — book-digester

Scored acceptance spec for one digested book. Each dimension is 1 to 10; the text
describes a 9 to 10.

## Dimensions

1. **Structural fidelity** (1 to 10). 9 to 10: chunk boundaries align to the book's real
   structure (spine + TOC hierarchy); no chunk splits a paragraph; the `structure` tree in the
   index reproduces the book's chapter and section hierarchy with correct titles and nesting.
2. **Coverage and completeness** (1 to 10). 9 to 10: 99%+ of substantive words are mapped to
   exactly one chunk; no silent duplication; every excluded item (cover, copyright page, blank
   nav) is listed with a reason in `coverage.json`; the delta is script-computed, not estimated.
3. **Provenance and traceability** (1 to 10). 9 to 10: every chunk carries spine item, char
   start, char end, and a source sha256; any chunk round-trips to the exact source span it came
   from; a reader can cite back to the book from a chunk alone.
4. **Index accuracy** (1 to 10). 9 to 10: each chunk summary faithfully reflects its text with
   zero fabricated claims; topics are present in the chunk; extracted references resolve to real
   citations in the text; spot-checks of any five chunks find no invented content.
5. **Queryability and contract** (1 to 10). 9 to 10: `SCHEMA.md` documents the index and chunk
   schema fully; the inverted indexes (`topics_index`, `references_index`) and the `structure`
   tree each resolve a documented example query to the correct chunk IDs; a downstream workflow
   can integrate against the contract cold, without opening the book.
6. **Consumer robustness** (1 to 10). 9 to 10: `index.json` validates against the published JSON
   Schema; IDs and boundaries are byte-for-byte identical on re-run; artifacts are dependency
   free JSON readable by any consumer; the pipeline degrades gracefully on txt and pdf and logs
   its structural confidence instead of guessing silently.

## Thresholds

Hard minimum 8 on every dimension. Overall gate: no dimension below 8, and no
open Blocker or Major finding.

## Elite markers

- Round-trippable provenance: a small script reconstructs any chapter verbatim from its chunks
  in order, matching the normalized source span.
- A published `index.schema.json` the index validates against, plus at least two worked queries
  in `SCHEMA.md` (one by chapter, one by reference) that return correct IDs.
- Script-proven coverage accounting: `coverage.json` shows the exact word delta and an explicit,
  named exclusion list, not a hand-waved "looks complete."

## How this repo meets the gate

| Dimension | Evidence in this repo |
|---|---|
| Structural fidelity | `structure` tree reproduces Part → Chapter → Section with titles; chunker splits only at heading boundaries — `verify.py` proves no paragraph is split (spans align to blocks). |
| Coverage | `coverage.json` is recomputed by `verify.py` from the source; 100% mapped on the fixture; `cover.xhtml` and `copyright.xhtml` excluded with named reasons. |
| Provenance | Every chunk carries `spine_item`, `char_start`, `char_end`, `source_sha256`; `verify.py` re-derives the source and asserts `source[start:end] == text`; `roundtrip.py` rebuilds each chapter verbatim. |
| Index accuracy | Summaries and topics are **extractive** (verbatim spans / words present in the chunk), so nothing is fabricated by construction; the Adversary review (`agents/adversary.md`) audits faithfulness. |
| Queryability | `SCHEMA.md` documents every field and includes three runnable worked queries (chapter, reference, topic) executed by `tools/query.py`. |
| Consumer robustness | `verify.py` validates `index.json` against `library/_schema/index.schema.json`, proves byte-identical re-runs, and the pipeline reports `structural_confidence` (`high` for epub, `low` for txt). |
