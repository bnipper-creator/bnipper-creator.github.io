# SCHEMA — the book-digester contract

This document is the integration contract. A downstream workflow (for example, a
daily scripture-study builder) can build against it **without ever opening the
source book**. The machine-readable version is
[`library/_schema/index.schema.json`](library/_schema/index.schema.json)
(JSON Schema draft-07); `index.json` validates against it and `verify.py` checks
that on every run.

## Artifact layout

```
library/
  _schema/index.schema.json        # the published JSON Schema
  <book-slug>/
    index.json                     # the queryable product (this document)
    coverage.json                  # word accounting + named exclusions
    chunks/<chunk_id>.json         # one file per chunk, with the verbatim text
```

- **`index.json`** is small and always safe to load; it holds structure and
  metadata, not full text.
- **`chunks/<id>.json`** holds the verbatim source span for one chunk. Load only
  the chunks a query resolves to.

## `chunk_id`

A chunk id is `NNN-SS` (zero-padded): `NNN` is the spine position of the source
document, `SS` is the section index within it. IDs derive from **structure, not
run order**, so they are stable across re-runs. Regex: `^\d{3}-\d{2}$`.

## `index.json`

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Semantic version of this contract (`"1.0.0"`). |
| `book` | object | Book metadata (below). |
| `counts` | object | `chunks`, `chapters`, `sections`, `topics`, `references`. |
| `structure` | array | Part → Chapter → Section tree; leaves carry `chunk_id`. |
| `chunks` | array | One record per chunk (below). Does **not** include full text. |
| `topics_index` | object | `topic → [chunk_id, …]` inverted index. |
| `references_index` | object | `"C:V" → chunk_id` — the canonical chunk that *contains* that verse. |
| `cross_reference_index` | object | `"C:V" → [chunk_id, …]` — chunks whose prose *cites* that verse. |

### `book`

`slug`, `title`, `author`, `language`, `identifier`, `source_format`
(`epub`/`txt`/`pdf`), `source_sha256` (sha256 of the raw source file),
`structural_confidence` (`high`/`medium`/`low`), `generated_by`.

### `chunks[]` record

| Field | Type | Meaning |
|---|---|---|
| `chunk_id` | string | `NNN-SS`. |
| `book_slug` | string | Owning book. |
| `title` | string | Section title, else chapter title. |
| `chapter_title` | string / null | Chapter this chunk belongs to. |
| `section_title` | string / null | Section heading (null for chapter-level chunks). |
| `spine_item` | string | Source document (href relative to the OPF). |
| `char_start`, `char_end` | int | Offsets into the spine item's **normalized** text. |
| `source_sha256` | string | sha256 of that spine item's normalized text. |
| `word_count` | int | Words in the chunk. |
| `summary` | string | Extractive (verbatim) summary — the chunk's opening sentence(s). |
| `topics` | array | Salient keywords, each guaranteed present in the chunk. |
| `contains_refs` | array | Canonical `"C:V"` refs located in this chunk. |
| `cross_references` | array | `"C:V"` refs the prose points to (each resolves in `references_index`). |
| `verses` | object / null | `{chapter, start, end}` verse range, when present. |

The chunk **file** (`chunks/<id>.json`) has every field above **plus `text`**,
the verbatim source span: `normalized_source[char_start:char_end] == text`.

## `coverage.json`

`total_words`, `substantive_words` (total minus excluded items),
`mapped_words`, `unmapped_words`, `coverage_ratio`, `threshold` (0.99),
`passes`, `included_spine_items[]` (`spine_item`, `words`, `chunks`), and
`excluded_spine_items[]` (`spine_item`, `reason`, `words`). The numbers are
recomputed from the source by `verify.py`, never asserted.

## Worked queries

Run against the digested fixture (`python3 tools/query.py …`). These are the
three access paths a consumer uses.

### 1. By chapter (structure tree)

```
$ python3 tools/query.py library/wayfarers-compass chapter "Chapter 3. On Storms"
query chapter='Chapter 3. On Storms' -> ['004-00', '004-01']
```

Walk `structure` to the chapter node; its section children give the chunk ids in
reading order.

### 2. By reference (references_index)

```
$ python3 tools/query.py library/wayfarers-compass reference 3:2
query reference='3:2' -> ['004-00']
```

`references_index["3:2"]` is the canonical chunk containing verse 3:2. This is
the path the scripture-study builder uses to pull a cited passage: look up the
reference, load that one chunk file, done — no book required.

### 3. By topic (topics_index)

```
$ python3 tools/query.py library/wayfarers-compass topic needle
query topic='needle' -> ['003-00']
```

`topics_index["needle"]` lists every chunk whose salient keywords include
*needle*.

## Integrating cold (no book)

1. Load `index.json`; validate against `index.schema.json` if you want a guarantee.
2. Resolve chunk ids via `structure`, `references_index`, or `topics_index`.
3. Load only those `chunks/<id>.json` files and use their `text` / `summary`.
4. To cite back to the book, use each chunk's `spine_item` + `char_start`/`char_end`.

`tools/query.py` is a ~90-line reference consumer that does exactly this.
