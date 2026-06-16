---
title: "AppSec Solver Harness"
description: "Claude Code multi-agent harness for authorized application security testing — threat model to SAST to human-gated dynamic testing to review"
date: 2026-06-16
draft: false
---

**Status:** `WORKING` (validated end-to-end on OWASP Juice Shop)

## Problem

Application security testing done by hand is ad hoc, hard to repeat, and easy to fudge.
The failure mode that costs the most trust isn't a missed bug — it's a confident finding
with nothing behind it. An LLM pointed at a codebase and asked to "find vulnerabilities"
makes this worse: it produces fluent, plausible findings that don't trace to any tool
output and can't be reproduced. I wanted a harness that uses an LLM for what it's good at —
orchestration, triage, and synthesis — while forcing every claim to be backed by a real
artifact, and that refuses to attack anything outside an explicit authorization scope.

## Approach

A multi-agent harness built for Claude Code, structured as a disciplined orchestrator plus
isolated, single-purpose subagents. It runs a phased loop with hard gates between phases:

- **Threat model as the spine** — Phase 1 derives a STRIDE threat model and data-flow
  diagram into a typed, schema-validated `threat-model.json`. Every later finding must
  trace back to a node ID in it; orphan findings don't exist.
- **SAST orchestration, not LLM guessing** — Phase 3 drives Semgrep and CodeQL and captures
  the actual result rows. "The model read it and it looks fine" is explicitly not a valid
  resolution — a test case it can't confirm with tooling is marked `STATIC-INCONCLUSIVE`
  and escalated, never silently passed.
- **Grounded test cases** — every test case cites a threat ID, an entry-point ID, and a
  data classification. Ungrounded hypotheticals are dropped rather than carried forward.
- **Human-gated dynamic testing** — Phase 4 stages a dynamic-test plan and stops. The
  active-testing agent reads an authorization manifest and refuses to send a single request
  until a human has reviewed the plan and signed off. Production is off-limits without a
  separate per-run approval, and targets run only in isolated Docker networks.
- **Adversarial review** — Phase 5 runs in a fresh context to diff every finding against its
  evidence, flag inconsistencies, and list threat-model nodes with zero coverage as blind
  spots.

The design principle throughout: the LLM orchestrates real tools and is held to
artifact-backed claims — it doesn't replace the tools, and it doesn't get to assert.

## Testing

Validated end-to-end against [OWASP Juice Shop](https://github.com/juice-shop/juice-shop)
running in an isolated Docker network — the full chain from threat model through SAST to a
staged, human-gated dynamic plan and adversarial review. Results are scored for
precision/recall against a ground-truth vulnerability list (`validation/known-vulns.md`),
with tiered practice targets (DVWA, Juice Shop, WebGoat) for tuning grounding and triage
before the harness is ever pointed at real code. The repo ships the actual Juice Shop run —
threat model, findings trail, and raw Semgrep output — as a worked example.

## Outcome

A working, safety-gated AppSec harness that produces auditable findings instead of
plausible prose: every finding traces to a threat-model node and a concrete tool artifact,
active testing can't fire without explicit human authorization, and a fresh-context
reviewer challenges the results before they're reported. It runs reproducibly against
known-vulnerable targets and is built to be pointed at authorized, source-available code.

**Source code and full methodology: [github.com/bnipper-creator/appsec-harness](https://github.com/bnipper-creator/appsec-harness)**
