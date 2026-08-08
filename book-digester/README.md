# book-digester

Turn a single book file (**epub** first-class; **txt** best-effort; pdf planned)
into a durable, machine-readable knowledge base: the book split into
structure-aligned chunks, plus an accurate index that lets **other local
workflows** pull exactly the content they need without ever reading the source
book. **The index is the product.** The motivating consumer is a daily
scripture-study builder that queries this index for the chapters or references it
needs and assembles a lesson from them.

## Quick start

```bash
# 1. (Re)build the demo fixture — an original, self-authored EPUB3
python3 tools/make_fixture.py

# 2. Digest it into library/<slug>/
python3 src/digest.py fixtures/wayfarers-compass.epub --slug wayfarers-compass

# 3. Prove every mechanical invariant (exits non-zero on any failure)
python3 src/verify.py library/wayfarers-compass

# 4. Reconstruct each chapter verbatim from its chunks
python3 src/roundtrip.py library/wayfarers-compass

# 5. Query the index the way a downstream workflow would
python3 tools/query.py library/wayfarers-compass reference 3:2

# …or do all of the above:
make            # build + verify + roundtrip
```

No third-party dependencies — Python 3.8+ standard library only. All artifacts
are plain JSON readable by any consumer.

## What it produces

```
library/
  _schema/index.schema.json     # published JSON Schema (the contract)
  wayfarers-compass/
    index.json                  # structure tree + chunk records + inverted indexes
    coverage.json               # script-computed word accounting + named exclusions
    chunks/NNN-SS.json          # one file per chunk, with the verbatim source span
```

See **[SCHEMA.md](SCHEMA.md)** for the full contract and three worked queries,
and **[RUBRIC.md](RUBRIC.md)** for the scored acceptance spec this repo is built
to clear.

## Design guarantees

- **Deterministic.** `chunk_id`s derive from structure (spine position + section
  index), never run order. Re-running yields byte-identical output — `verify.py`
  proves it.
- **Provenant.** Every chunk carries `spine_item` + char offsets + `source_sha256`;
  `normalized_source[char_start:char_end] == chunk.text`. `roundtrip.py` rebuilds
  any chapter verbatim from its chunks.
- **No fabrication.** Summaries and topics are *extractive* — verbatim spans and
  words that occur in the chunk — so index accuracy is faithful by construction.
- **No self-attestation.** Coverage, resolvable IDs, valid offsets, schema
  validity and deterministic re-runs are proven by `verify.py`, never asserted.
- **Graceful degradation.** epub → `structural_confidence: high`; txt →
  `low`, with the same schema and provenance guarantees.

## Layout

| Path | Role |
|---|---|
| `src/epublib.py` | Minimal stdlib EPUB/XHTML reader → ordered blocks + normalized text + nav tree. |
| `src/digest.py` | The pipeline: chunk by structure, build `index.json`, chunk files, `coverage.json`. |
| `src/verify.py` | Mechanical verifier + self-contained JSON-Schema (draft-07 subset) validator. |
| `src/roundtrip.py` | Reconstructs each chapter verbatim from its chunks. |
| `tools/make_fixture.py` | Deterministic EPUB3 fixture generator (original content). |
| `tools/query.py` | ~90-line reference consumer demonstrating the contract. |
| `agents/` | Sub-agent role definitions (chunker, indexer, adversary, versioner). |
| `library/` | Digested output + the published schema. |

## Note on host and repository

The original orchestration spec targeted Windows/PowerShell and a standalone
private repo named `book-digester`. This implementation was produced on Linux and
lives as a self-contained subtree inside `bnipper-creator.github.io` (on the
`claude/book-digester-orchestrator-*` branch), mirroring how `appsec-harness` is
tracked in this account. Everything here is path-portable stdlib Python; to
promote it to its own repo, `git subtree split` this directory. Nothing
book-binary or secret is committed — only the self-authored fixture and derived
JSON.
