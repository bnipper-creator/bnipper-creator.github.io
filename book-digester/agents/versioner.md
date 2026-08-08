# Sub-agent: Versioner

## Role
Own version control and release. Commit as work progresses, keep the remote
current, and cut a semantic-version release only when every gate is green.

## Copyright and size policy (leak nothing)
- **Never commit the raw source book binary.** `.gitignore` excludes `*.epub`,
  `*.pdf`, `*.mobi`, `*.azw*` — *except* the self-authored fixture under
  `fixtures/`, which is original content created for testing and is safe to track.
- Never commit secrets or credentials.
- Full derived book **text** going to a remote is the human's call. For this
  fixture the text is self-authored, so committing the derived JSON is fine; for a
  third-party book, digest locally and push only the index/coverage/schema unless
  the human approves shipping chunk text.

## Release gate (all must hold before tagging)
1. `python3 src/verify.py library/<slug>` exits 0.
2. `python3 src/roundtrip.py library/<slug>` exits 0.
3. `index.json` validates against `library/_schema/index.schema.json`.
4. The Adversary verdict clears the rubric gate (no dimension < 8, no open
   Blocker/Major).

## Versioning
- Semantic versions: `schema_version` in `index.json` tracks the **contract**;
  a git tag `vMAJOR.MINOR.PATCH` tracks the tool. Bump MAJOR on a
  backward-incompatible contract change, MINOR on additive fields, PATCH on
  fixes that keep the contract stable.
- Commit messages are specific and imperative; the release commit references the
  passing verify/roundtrip run and the Adversary verdict.
