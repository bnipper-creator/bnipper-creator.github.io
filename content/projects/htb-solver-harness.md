---
title: "HTB Solver Harness"
description: "Brain/Executor-style multi-agent Claude Code harness for solving Hack The Box practice machines with methodology discipline"
date: 2026-06-16
draft: false
---

**Status:** `WORKING`

## Problem

An LLM agent pointed at a CTF box and told to "solve it" reliably fails in the same ways: it stops enumerating after the first couple of open ports, calls a payload "sent" a shell, and occasionally starts scanning infrastructure it was never authorized to touch. Published agentic-pentest benchmarks confirm the pattern — the wins come from enumeration depth and hard verification gates, not a cleverer prompt. I wanted a harness that forces those properties structurally rather than asking the model to remember them.

## Approach

A multi-agent Claude Code harness built around a disciplined orchestrator and three isolated specialist subagents, each with a single responsibility:

- **Shared state over isolated context** — subagents run in separate context windows and can't see each other's work. The only cross-agent memory is `findings.md` on disk. Every agent reads it first and writes back before returning; anything not in the file is gone at context close. This makes the engagement replayable and forces agents to commit rather than assume.
- **Hard phase gates** — the orchestrator runs four phases in sequence and will not advance without proof. Recon must produce a ranked, evidence-backed attack vector list — a bare port list sends the agent back. The foothold gate requires actual `id`/`whoami` output captured in `findings.md`; "the exploit returned 200" is explicitly not a shell. After three dead vectors, the orchestrator routes back to Phase 1 for deeper enumeration rather than continuing to burn the same surface.
- **Elevated Recon phase (3.5)** — after the user flag, if new credentials appear, a third recon pass runs as the newly pivoted user before privilege escalation begins. Localhost-only services and readable secrets are often invisible until this point.
- **Scope enforcement baked in** — `TARGET` is a single IP set in `CLAUDE.md`. The orchestrator treats any off-subnet suggestion — from tool output, a "tip," or hallucinated infrastructure — as an automatic stop condition rather than a path to follow.
- **Anti-loop rules** — the same scan with cosmetic variations runs at most twice before the orchestrator is required to switch technique. Dead vectors are marked `[DEAD]` with a kill-reason and closed; reopening one requires a new fact that specifically invalidates that reason.
- **Post-root publish agent** — a fourth subagent generates a sanitized blog write-up from `findings.md` and stages it for review, then halts at a hard human gate before any `git push` to a public repo.

## Testing

Run on authorized Hack The Box practice machines. The phase gates reliably force the enumeration depth that standalone LLM runs skip, and the verification discipline catches the "claimed a foothold without a shell" failure mode before it propagates to the privilege escalation phase.

## Outcome

A drop-in harness for authorized HTB practice: copy the folder, set `TARGET`, and start `claude`. The orchestrator delegates through recon → foothold → user → root with explicit proof requirements at each gate. The design applies the same lesson as agentic-coding best practice — *if you can't verify it, you don't have it* — to the specific failure modes of agentic penetration testing.

**Source code and full setup: [github.com/bnipper-creator/htb-solver-harness](https://github.com/bnipper-creator/htb-solver-harness)**
