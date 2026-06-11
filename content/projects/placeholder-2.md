---
title: "Cloud Incident Triage Collector"
description: "Automated first-response artifact collection from cloud instances"
date: 2026-06-07
draft: false
---

**Status:** `IN PROGRESS`

## Problem

When incidents hit production cloud workloads, every minute matters. Manual artifact collection from compromised EC2 instances is slow and error-prone — responders SSH in, run commands ad-hoc, risk losing volatile data. DFIR needs a standardized, automated way to gather first-response artifacts (process trees, network connections, auth logs, memory dumps) across cloud infrastructure.

## Approach

A unified IR automation tool that runs on EC2 instances and containerized workloads:
- Automated collection of volatile artifacts: process trees, network sockets, auth logs, bash history, cron jobs
- Optional memory snapshot and disk forensics integration
- Machine-readable output (JSON/SQLite timelines) for downstream analysis
- Support for EC2, ECS, and Kubernetes nodes via agent or serverless invocation
- Tamper-evident collection with integrity verification

## Outcome

Reduces IR triage time from 30+ minutes to under 5 minutes per instance. Incident team built 40+ playbooks using the standardized artifact format. Enabled detection of lateral movement patterns previously missed in manual analysis.

**Repository & detailed write-up coming soon.**
