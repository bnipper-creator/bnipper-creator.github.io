---
title: "Oopsie — HTB Writeup"
date: 2026-06-11
draft: false
---

**Difficulty:** Very Easy | **OS:** Linux | **Date:** June 2026

## Overview

Oopsie is a Very Easy HTB box built around a small "MegaCorp Automotive" web
application. On paper it doesn't look like much — there's no flashy CVE, no
custom binary exploitation, no kernel exploit at the end. What makes it worth
writing about is that the entire chain is built from small mistakes that, on
their own, look almost cosmetic: an unsigned session cookie, an account ID
that increments predictably, an upload form with no file-type checks, and a
password left in a PHP file. None of these would make headlines individually.
Chained together, they walked us from an anonymous visitor to root.

That's the real lesson of this box: information disclosure and broken access
control are routinely dismissed as "low severity" findings in pentest
reports, but they're often the connective tissue that turns a handful of
unrelated low-risk issues into a full compromise.

## Kill Chain Summary

1. Guest login on the web app exposes session state in plaintext, editable
   cookies.
2. An IDOR on an account-lookup endpoint leaks the admin account's internal
   ID.
3. Forging the cookie with that ID grants admin access to a file upload
   feature.
4. The upload feature has no file-type validation — upload a PHP reverse
   shell, get a `www-data` shell.
5. Source code in the web root contains hardcoded credentials, one of which
   is reused as a system account's password (`robert`).
6. `robert` belongs to a group that owns a SUID root binary with an unsafe
   `PATH`-dependent call to `cat` — hijack `PATH`, get root.

## Recon & Enumeration

A standard `nmap -sC -sV` against the host turned up only two open ports:
SSH (22) and Apache 2.4.29 on Ubuntu (80). With SSH closed off as an attack
surface (no creds yet), the web app on port 80 was the obvious starting
point.

The homepage is a fairly generic automotive-company template, but it hints
that "services" are available after logging in. Passively spidering the site
turned up `/cdn-cgi/login/` — a login page that wasn't linked anywhere from
the visible navigation. This is a common pattern on easier boxes: directories
that aren't in the nav bar but are very much reachable, and a passive proxy
crawl (or a quick gobuster run) finds them faster than clicking around ever
will.

The login page offered a "Login as Guest" option. Taking it logged us in
without credentials and dropped two cookies: `role=guest` and `user=2233`.
Both were plain, unsigned values sitting in the cookie jar — an immediate
red flag, since nothing was stopping a client from just... changing them.

## Foothold

The guest session exposed an "Account" page at
`admin.php?content=accounts&id=2`, which displayed account details for the
ID in the query string. Changing `id=2` to `id=1` returned a *different*
account's details — a textbook IDOR. That account turned out to be the admin
user, and its page exposed an internal "Access ID" value (`34322`) that the
application apparently uses as the real identity token behind the `user`
cookie.

Swapping our cookies to `user=34322; role=admin` and revisiting the app
granted full admin access, including a "Branding" image upload feature that
had previously returned a permissions error for the guest account. The
upload endpoint accepted any file type — no extension whitelist, no MIME
checking, nothing. I uploaded `php-reverse-shell.php` (the pentestmonkey
classic from `/usr/share/webshells/php/`, with the IP/port patched to match my
tun0 address) and requested it directly from `/uploads/`, which is the
default storage location for this app.

One divergence worth noting: the first time I triggered the shell, the
uploaded file had already been removed — there appears to be a cleanup job
that periodically purges the uploads directory. A second upload-and-trigger
in quick succession worked fine and landed a `www-data` shell.

The underlying vulnerability class here is **unrestricted file upload**
(OWASP-style: missing server-side validation of uploaded content), but it's
worth emphasizing that it was *only reachable* because of the broken access
control and IDOR that came before it. A pentest report that flagged the IDOR
as "informational" and the cookie tampering as "low" would have missed that
together they're a direct path to RCE.

## Privilege Escalation

From `www-data`, the next move was to look at the application's own source
for anything useful — a very common move on boxes where the foothold is a
web app, since the app's PHP files are sitting right there in the web root,
readable by the user running the web server. Grepping recursively for
`passw` across `/var/www/html/cdn-cgi/login/` turned up a hardcoded admin
password in the login logic itself, and separately, a
`db.php` file containing MySQL credentials for a user named `robert`.

`/etc/passwd` confirmed `robert` was the only non-root account with a login
shell, so the obvious next step was to try the database password against his
system account via `su`. **Password reuse across a database account and a
Unix account** is depressingly common in real environments, and it paid off
here — `su robert` succeeded and the user flag was sitting in his home
directory.

`id` showed `robert` belongs to a secondary group called `bugtracker`.
Searching the filesystem for files owned by that group (`find / -group
bugtracker`) turned up exactly one binary: `/usr/bin/bugtracker`, owned by
`root:bugtracker` with the SUID bit set. Since `robert` is a member of that
group, he can execute it — and because it's SUID root, it runs with root
privileges regardless of who invokes it.

Running the binary presents a small "Bug Tracker" menu and, behind the
scenes, shells out to `cat` to display a file — but it does so by calling
`cat` as a bare command name rather than `/bin/cat`. That means it resolves
the binary via the `$PATH` environment variable inherited from the calling
user's shell. This is **CWE-426 (Untrusted Search Path)**: a privileged
program trusting an attacker-controllable environment variable to locate an
executable.

The exploit is about as simple as privilege escalation gets: write a script
called `cat` into `/tmp` (in this case just `#!/bin/bash` to drop a shell),
make it executable, and prepend `/tmp` to `$PATH`. Running `bugtracker` again
now resolves "cat" to our malicious script first — and because the binary is
SUID root, our script executes as root. From there, reading `/root/root.txt`
(via `/bin/cat`, since our hijacked `cat` was still shadowing the real one in
the resulting shell's `PATH`) completed the box.

## Key Takeaways

- **Low-severity findings compound.** An unsigned cookie, an IDOR, and a
  missing upload filter are each "medium" at best in isolation, but chained
  together they produced full RCE. Triage chains, not just individual
  findings.
- **Client-controlled identity is not identity.** Any value the client can
  read or set (cookies, hidden fields, query params) must be treated as
  attacker-controlled. Authorization decisions belong server-side, backed by
  signed/encrypted session tokens.
- **Source code in the web root is a liability.** Hardcoded credentials in
  PHP files are trivially recoverable by anyone who gets even unprivileged
  code execution on the host.
- **Password reuse between services and OS accounts** turns a database
  credential leak into a full user compromise — this is the same pattern
  behind countless real-world lateral movement incidents.
- **SUID binaries must use absolute paths for everything they exec.** This
  maps directly to CWE-426 and is a recurring finding in real audits of
  legacy setuid tooling, especially older administrative utilities written
  without a hardened `$PATH`.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | Initial port/service enumeration | `-sC -sV -Pn --top-ports 1000` |
| Burp Suite (passive spider) | Discover hidden directories without active scanning | proxy + sitemap |
| Firefox DevTools | Inspect and edit session cookies | Storage tab |
| `php-reverse-shell.php` | Reverse shell payload after gaining upload access | IP/port patched for listener |
| `nc` | Catch the reverse shell | `-lvnp` |
| `grep` | Search source files for hardcoded credentials | `-i` for case-insensitive `passw` match |
| `find` | Locate files owned by a specific group | `-group bugtracker` |
| `su` | Test password reuse against a Unix account | — |
| PATH hijack (`/tmp/cat`) | Escalate via SUID binary with unsafe `cat` call | `export PATH=/tmp:$PATH` |
