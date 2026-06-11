---
title: "AWS Security Scanner"
description: "Python CLI for CIS Foundations Benchmark compliance scanning"
date: 2026-06-07
draft: false
---

**Status:** `IN PROGRESS`

## Problem

AWS environments accumulate misconfigurations over time — overly permissive IAM roles, unencrypted storage, public APIs, exposed snapshots. Manual compliance audits are tedious and error-prone. Security teams need a fast, reproducible way to assess cloud posture against established baselines like the CIS Foundations Benchmark.

## Approach

A Python CLI tool using boto3 to scan AWS accounts across multiple regions and services:
- Automated checks against CIS Foundations Benchmark (v1.4)
- Coverage: S3 (public access), IAM (over-permissive roles), EC2 (security groups), KMS (key rotation), CloudTrail (logging)
- Human-readable JSON/CSV compliance reports with remediation guidance
- Dry-run mode for safety; optional remediation workflows

## Outcome

Reduces manual security audit time from hours to minutes. Integrates into CI/CD for continuous compliance monitoring. Early versions deployed internally to scan 50+ AWS accounts weekly.

**Repository & detailed write-up coming soon.**
