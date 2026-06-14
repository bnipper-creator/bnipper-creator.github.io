---
title: "Jerry — HTB Writeup"
date: 2026-06-13
draft: false
---

**Difficulty:** Easy | **OS:** Windows | **Date:** June 2026

## Overview

Jerry simulates something that's not just a CTF trope — it's a live threat pattern
that shows up in internal pentest reports every week: a management interface exposed
to the network, running on default credentials, on a service that can deploy
executable code. Apache Tomcat's Manager application is the entire attack surface
here. There is no CVE to chase, no binary exploitation, no weird Windows kernel
path. The whole chain is: find the open port, find the credential hint the app
hands you in its own 401 error page, deploy a WAR file, get SYSTEM. It's
embarrassingly clean — which is exactly what makes it instructive.

## Kill Chain Summary

1. Nmap reveals a single open port: 8080 (Apache Tomcat 7.0.88, Windows Server 2012 R2)
2. Tomcat Manager UI at `/manager/html` is publicly accessible, returning a 401 with credential hints
3. Default credential `tomcat:[default-password]` authenticates with `manager-gui` role
4. Malicious WAR file deployed via the text API at `/manager/text/deploy`
5. Shell triggered — received as `nt authority\system`, no privesc required
6. Both flags retrieved from a single file on the Administrator desktop

## Recon & Enumeration

The surface area here is about as narrow as it gets: one open TCP port, no vhosts, no
DNS games, no UDP. A full TCP sweep with `nmap -p- --min-rate 5000 -Pn` confirms port
8080 is the only entry point. Service detection (`-sV -sC`) identifies it immediately
as Apache Tomcat 7.0.88 with the Coyote/1.1 connector — an older branch of Tomcat 7
with a known-bad security posture.

The interesting discovery isn't from a scanner — it's from reading the application's
own error pages. Tomcat 7's default 401 response on `/manager/html` includes an XML
snippet showing example credentials, specifically the default `manager-gui` password. This is a default
configuration leftover that ships with many older Tomcat installations. The app is
telling you the password in its login failure message.

A quick credential sweep confirms two valid accounts:
- `admin:admin` — `manager-status` role only; can view the status page, cannot deploy
- `tomcat:[default-password]` — `manager-gui` role; full deployment capability

The distinction matters: the status role exists for monitoring; the gui role includes
the WAR deployment API. Only the second account opens the door.

## Foothold

The Tomcat Manager's WAR deployment capability is a legitimate feature — it lets
administrators push Java web applications to the server by uploading a `.war` archive.
The vulnerability class here isn't a buffer overflow or injection flaw; it's **feature
abuse via weak authentication**. The feature works exactly as designed, just not for
its intended user.

The path through the text API (`/manager/text/deploy`) is preferable to the HTML GUI
for scripted exploitation because it's not CSRF-protected — it accepts a direct PUT
from `curl`. The process:

1. Generate a JSP reverse shell packaged as a WAR file using `msfvenom` with the
   `java/jsp_shell_reverse_tcp` payload, targeting the attacker's tun0 interface.
2. Deploy with `curl -u tomcat:[default-password] -T shell.war "http://[target]:8080/manager/text/deploy?path=/shell"`.
   Tomcat responds: `OK - Deployed application at context path /shell`.
3. Stand up a listener, then GET `/shell/` to trigger the JSP and receive the connection.

The shell lands immediately as `nt authority\system`. This is the default behavior on
Windows when Tomcat is installed as a service without explicit service account
hardening — the service inherits the SYSTEM token, so every request it processes,
including your malicious JSP, executes with the highest privilege level on the box.
No privesc step exists here because there's nothing to escalate to.

## Privilege Escalation

There isn't one, and that's the real lesson.

The conventional penetration testing model assumes a staircase: low user → privileged
user → admin/root. Jerry collapses that model entirely. The Tomcat service running as
SYSTEM means the foothold and the root are the same step. This is a misconfiguration
in how the service was installed, not in the application itself — Windows service
accounts should follow the principle of least privilege, running as a purpose-built
low-privilege account with exactly the permissions the service needs.

In a real engagement, this finding would go in the report under "Critical — Tomcat
service running as SYSTEM" and would have a CVSS score in the 9+ range, not because
Tomcat has a CVE, but because the operational configuration hands an attacker SYSTEM
with nothing more than a valid WAR file and a stolen credential.

## Key Takeaways

1. **Default credentials are live vulnerabilities.** Tomcat's default `manager-gui` credential ships in
   documentation and default config files. Scanning for default creds isn't exotic
   — it should be in every internal assessment checklist. MITRE ATT&CK: T1078.001
   (Valid Accounts: Default Accounts).

2. **The application's 401 page is a security finding.** Tomcat's example XML in the
   403/401 error response is a credential hint baked into the default error template.
   In production, custom error pages should never include credential examples.

3. **Feature abuse is harder to detect than exploit traffic.** The WAR deployment
   here is legitimate application behavior. It won't trigger most signature-based IDS
   rules — it looks like a normal management operation. Detection requires behavioral
   baselines: "has a WAR been deployed outside the change window?"

4. **Windows service accounts need least-privilege hardening.** SYSTEM is not a
   service account — it's an emergency fallback. Real service accounts should be
   domain or local service accounts scoped to the directories the service actually
   needs. MITRE ATT&CK: T1543.003 (Create or Modify System Process: Windows Service).

5. **Network exposure of management interfaces is the root cause.** Tomcat Manager
   has no business being reachable on a network interface in production. It should be
   bound to 127.0.0.1 or placed behind an authenticated proxy with MFA. The entire
   attack chain collapses if the manager is not reachable.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|------|---------|--------------------|
| nmap | Port and service discovery | `-p- --min-rate 5000 -Pn`, then `-sV -sC -p 8080` |
| msfvenom | WAR payload generation | `-p java/jsp_shell_reverse_tcp -f war` |
| curl | WAR deployment via Tomcat text API | `-u user:pass -T file.war "url?path=/app"` |
| netcat | Reverse shell listener | `nc -lvnp 4444` |
