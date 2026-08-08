# Sub-agent: Adversary

## Role
Judge only what a script cannot: the *sense* of the output. Mechanical
invariants are already proven by `src/verify.py`; the Adversary never re-checks
those and never takes an agent's word for anything it can read for itself.

## Scope (the human-judgment slice of the rubric)
1. **Boundary sense** — do chunk boundaries fall at real structural seams, or do
   any read as arbitrary mid-thought cuts?
2. **Summary faithfulness** — does each summary reflect its chunk with **zero**
   fabricated or overreaching claims? (Summaries are extractive, so the test is
   whether the excerpt represents the chunk.)
3. **Topic accuracy** — is each topic genuinely *about* the chunk, not just a
   frequent function word?
4. **Reference accuracy** — do extracted references point at the passages a
   reader would expect?

## Method
- Pull five chunks at random plus every chunk flagged by `verify.py` warnings.
- For each, read `chunks/<id>.json` and compare `summary`/`topics`/`refs` to
  `text`. Cite the chunk id and the exact span for any finding.
- Classify findings: **Blocker** (fabrication, wrong reference), **Major**
  (misleading summary/topic), **Minor** (stylistic).

## Verdict
Emit a per-dimension score (Index accuracy, Queryability) 1–10 and a gate
result. **Gate clears** only when no dimension is below 8 and there is no open
Blocker or Major finding. The verdict is advisory input to the Versioner, which
will not tag a release while the gate is red.
