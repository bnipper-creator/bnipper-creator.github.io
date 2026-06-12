---
title: "AWS Security Scanner"
description: "Python CLI for CIS AWS Foundations Benchmark compliance scanning"
date: 2026-06-12
draft: false
---

**Status:** `COMPLETE` (v0.1)

## Problem

AWS environments accumulate misconfigurations over time — public S3 buckets, over-permissive IAM policies, security groups open to the world, KMS keys without rotation. Manual review against a baseline like the CIS AWS Foundations Benchmark is tedious and easy to get wrong, especially when you want a repeatable check rather than a one-off audit.

## Approach

`awsscanner` is a Typer-based Python CLI, built around a small, reusable core:

- **Coverage**: CIS AWS Foundations Benchmark v1.4 checks for S3 (block public access, default encryption), IAM (no full-admin policies, user MFA, root MFA), EC2 (unrestricted SSH/RDP, open ingress review), and KMS (key rotation). CloudTrail is intentionally out of scope for v0.1.
- **Central CIS catalog**: every check maps to a CIS control ID, title, severity, and remediation guidance defined in one place, so scanners and reports can never drift out of sync.
- **Reporting**: findings render as a `rich` console table, or export to JSON/CSV for downstream tooling.
- **Safe-by-default remediation**: a `remediate` command can fix certain findings (currently S3 Block Public Access), but requires *both* `--no-dry-run` and `--apply` to make any change — a bare run only prints the intended API call.
- **One choke point for AWS access**: a `SessionManager` wraps every boto3 client, so `--endpoint-url`, AWS profile, and optional `--assume-role-arn` apply uniformly across every scanner and remediation module.

The whole project is built and tested against [LocalStack](https://www.localstack.cloud/) — a local AWS emulator — so it's safe to run, seed with intentionally insecure resources, and remediate without touching a real account.

## Testing

- **Unit tests** (`pytest` + [moto](https://github.com/getmoto/moto)) mock every AWS call, covering each scanner's pass/fail logic, the CIS catalog, report writers, and remediation — no Docker required.
- **Integration tests** run the real scanners against a live, seeded LocalStack instance and auto-skip if it isn't running.

## Outcome

A working CLI that scans a seeded LocalStack environment, correctly flags intentionally-misconfigured resources (a public S3 bucket, an admin IAM user, a security group open on port 22, an unrotated KMS key) against their CIS control IDs, and can remediate the S3 finding end-to-end with a dry-run preview first. 29 unit + integration tests passing.

**Source code and full setup instructions: [github.com/bnipper-creator/aws-cis-scanner](https://github.com/bnipper-creator/aws-cis-scanner)**
