---
title: "Cap — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Easy | **OS:** Linux | **Date:** June 2026

## Overview

Cap is a Starting Point box, but it packs in two lessons that show up
constantly in real-world web app pentests: an Insecure Direct Object
Reference (IDOR) that leaks another user's data, and a Linux capability
misconfiguration that turns a single unprivileged binary into a root shell.
Neither step requires writing an exploit — both are "the application trusted
something it shouldn't have" failures, which is exactly why they're so common
in production.

## Kill Chain Summary

1. Nmap reveals FTP, SSH, and a Gunicorn-served "Security Dashboard" web app.
2. The dashboard's "Security Snapshot" feature triggers a server-side packet
   capture and serves it back via a predictable, incrementing ID.
3. Requesting an earlier ID than the one assigned to you (IDOR) returns
   another user's capture.
4. That capture contains a cleartext FTP login.
5. The recovered credentials work over SSH too, giving a foothold.
6. A non-default Linux capability on the system Python binary
   (`cap_setuid`) lets that user escalate straight to root.

## Recon & Enumeration

A full TCP sweep turned up exactly three open ports: FTP (vsftpd 3.0.3), SSH
(OpenSSH 8.2p1 on Ubuntu), and HTTP on port 80, served by Gunicorn rather than
nginx/Apache — a strong signal this is a Python web app (Flask, in this case).

Anonymous FTP login was disabled, so the web app was the obvious next stop.
The site presents itself as a "Security Dashboard" with menu items for IP
configuration, network status, and a "Security Snapshot" feature. The first
two pages turned out to be thin wrappers around `ifconfig` and `netstat` —
the app is shelling out to system tools and rendering the output, which is
worth flagging on its own as a potential command-injection surface, though it
wasn't the path needed here.

The "Security Snapshot" page was more interesting: clicking it kicks off a
short (~5 second) packet capture on the server, then presents a page with a
Download button. The page lived at a URL of the form `/data/<id>`, with `id`
incrementing each time a new capture was requested, and the download itself
was served from a separate `/download/<id>` route.

## Foothold

Incrementing, attacker-visible numeric IDs for what's supposed to be
per-user data is a classic IDOR setup — the natural next move is to request
an ID lower than your own and see what comes back. My own capture landed at
ID 1, so I requested `/download/0` directly, with no prior interaction with
that capture at all.

The server returned it without complaint: a valid pcap file belonging to
whoever (or whatever automated process) generated capture 0. Neither the
`/data/<id>` page nor the `/download/<id>` route performed any check that the
requesting session actually owned that capture ID — the only "access
control" was the assumption that nobody would guess or iterate IDs.

Opening the pcap in Wireshark/tshark showed an FTP session, complete with the
`USER` and `PASS` commands in plaintext — FTP has no built-in transport
encryption, so any credential exchanged over it is trivially recoverable to
anyone who can capture the traffic. That's exactly what capture 0 had done,
presumably during routine use of the dashboard by another account.

The recovered credentials worked for both FTP and, more usefully, SSH —
giving an interactive shell and the user flag without needing to touch FTP at
all.

## Privilege Escalation

With a shell as a low-privileged user, the next step was looking for
misconfigured permissions, SUID binaries, and Linux capabilities. Running
`getcap -r /` across the filesystem turned up something unusual:
`/usr/bin/python3.8` had `cap_setuid` and `cap_net_bind_service` set.

Neither of those is a default capability on a system Python interpreter.
`cap_net_bind_service` makes some sense in context — it would let a
non-root process bind to privileged ports (under 1024), which the dashboard
app might need if it ever serves on port 80 directly. `cap_setuid`, however,
is far more dangerous: it allows a process to call `setuid()` and change its
own UID *without* needing the SUID bit on the binary or starting as root.

Because the capability is attached to the interpreter itself, any code run
through that specific Python binary inherits the privilege. A three-line
script does the rest:

```python
import os
os.setuid(0)
os.system("/bin/bash")
```

`setuid(0)` drops the process's effective UID to 0 (root), and the spawned
shell inherits that. From there, reading `/root/root.txt` is trivial.

## Key Takeaways

- **IDOR is often the cheapest vulnerability to exploit and the easiest to
  prevent.** The fix here is a single authorization check — "does this
  session own this resource ID?" — applied consistently across every route
  that takes an ID, not just the ones a developer remembers to protect.
- **Don't assume plaintext protocols are "internal only."** FTP credentials
  sent in cleartext are a liability the moment *anything* on the network path
  can capture traffic — including the application's own diagnostic features.
- **Linux capabilities are a more surgical alternative to SUID, but they're
  still root-equivalent in the wrong combination.** `cap_setuid` on a
  general-purpose interpreter (Python, Perl, etc.) is effectively "give this
  binary root" for anyone who can execute it — equivalent in practice to an
  SUID root shell (MITRE ATT&CK T1548.001-adjacent abuse of privileged
  binaries).
- **Audit `getcap -r /` as part of any Linux hardening review.** It's cheap
  to run and capabilities are easy to grant during development and forget
  about before shipping.
- **Defense in depth would have stopped this chain at multiple points** —
  per-resource authorization on the dashboard, TLS/SFTP instead of plaintext
  FTP, or removing the stray capability from Python would each independently
  have broken the path to root.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|------|---------|---------------------|
| `nmap` | Service/version enumeration | `-sC -sV -p- --min-rate 5000 -Pn` |
| `curl` | Direct IDOR exploitation against `/download/<id>` | `-D -` to inspect headers/content-disposition |
| `tshark` | Extract FTP credentials from the captured pcap | `-Y "ftp" -T fields -e ftp.request.command -e ftp.request.arg` |
| `ssh` | Foothold using recovered credentials | — |
| `getcap` | Enumerate Linux capabilities for privesc | `-r /` |
| `python3` | Abuse `cap_setuid` to escalate to root | `os.setuid(0)` |
