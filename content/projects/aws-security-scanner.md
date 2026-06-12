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
- **One choke point for AWS access**: a `SessionManager` wraps every boto3 client, so AWS profile, region, and optional `--assume-role-arn` apply uniformly across every scanner and remediation module.

It runs against a real AWS account using the standard boto3 credential chain — your existing AWS CLI profile, environment variables, instance role, or an assumed cross-account role. Scanning only needs read access; the AWS-managed `SecurityAudit` policy covers everything `awsscanner scan` needs.

## Testing

- **Unit tests** (`pytest` + [moto](https://github.com/getmoto/moto)) mock every AWS call, covering each scanner's pass/fail logic, the CIS catalog, report writers, and remediation — no Docker required.
- **Integration tests** exercise the full scan/remediate flow against a seeded [LocalStack](https://www.localstack.cloud/) instance, auto-skipping if it isn't running, so changes can be validated end-to-end without touching a real account.

## Outcome

A working CLI that scans an AWS account, flags misconfigured resources (public S3 buckets, admin IAM users, security groups open on SSH/RDP, unrotated KMS keys) against their CIS control IDs, and can remediate the S3 finding end-to-end with a dry-run preview first. 25 unit tests plus a LocalStack-backed integration suite passing.

**Source code and full setup instructions: [github.com/bnipper-creator/aws-cis-scanner](https://github.com/bnipper-creator/aws-cis-scanner)**
