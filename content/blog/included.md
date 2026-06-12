---
title: "Included — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Very Easy | **OS:** Linux | **Date:** June 2026

## Overview

Included is one of HTB's Starting Point machines, and its main lesson is about thinking across protocols and trusting what `/etc/passwd` tells you, even when it seems irrelevant at first. The box exposes a single web service with a classic Local File Inclusion bug, but the LFI alone doesn't get you code execution — you need a *write* primitive somewhere on disk that the web server can then read back as PHP. That write primitive turns out to be an unauthenticated TFTP server, discovered only because a leftover `tftp` account in `/etc/passwd` hints that the service exists. From there, password reuse between a forgotten HTTP Basic Auth config and a real system account hands over a user shell, and a stale but still-dangerous group membership (`lxd`) finishes the job.

## Kill Chain Summary

1. `nmap` shows only port 80/tcp open — Apache serving a site driven by a `?file=` GET parameter
2. `?file=/etc/passwd` confirms a Local File Inclusion vulnerability
3. The passwd output lists a `tftp` system account with home directory `/var/lib/tftpboot`, hinting at TFTP
4. A UDP scan confirms port 69/udp (TFTP) is open and, by design, requires no authentication
5. Upload a PHP reverse shell to the TFTP root, then trigger it via the LFI to get a `www-data` shell
6. `/var/www/html/.htpasswd` contains plaintext-equivalent credentials for a user, reused as that user's system password
7. `su` to the user with the reused password and grab `user.txt`
8. The user is a member of the `lxd` group — create a privileged LXD container, bind-mount the host filesystem, and read `root.txt` as root

## Recon & Enumeration

`nmap -sC -sV -Pn --top-ports 1000` against the target returned exactly one open port: 80/tcp, Apache 2.4.29 on Ubuntu. The HTTP response immediately redirected to `/?file=home.php`, which is a strong signal of a PHP "page router" pattern — a single `index.php` that does something like:

```php
if ($_GET['file']) {
    include($_GET['file']);
} else {
    header("Location: ...?file=home.php");
}
```

Any time user input flows directly into `include()`, `require()`, or their `_once` variants without restriction, it's worth testing for Local File Inclusion. Requesting `?file=/etc/passwd` returned the full contents of the file — confirmed LFI, and since the path worked with no `../` traversal needed, the include statement wasn't prefixing a working directory.

The interesting part of that `/etc/passwd` output wasn't the usual `root`/`daemon`/service accounts — it was a `tftp` entry with home directory `/var/lib/tftpboot`. TFTP (Trivial File Transfer Protocol) is a UDP-based, unauthenticated file transfer protocol that's almost never useful on its own, but combined with an LFI it's a textbook write-then-include primitive: TFTP gives you arbitrary file writes to a predictable directory, and the LFI gives you a way to get the web server to execute whatever you wrote. A quick `sudo nmap -sU` against the host confirmed 69/udp open.

## Foothold

The exploitation chain here is "write via TFTP, execute via LFI." I wrote a standard PHP reverse shell (the well-known `pentestmonkey` style one-liner that spawns `/bin/sh` over a TCP socket back to the attacker), set the callback IP and port, and uploaded it directly to the TFTP server's root directory:

```bash
curl -T shell.php tftp://<target>/
```

TFTP's default root on Ubuntu (`tftpd-hpa`) is `/var/lib/tftpboot` — exactly the home directory listed for the `tftp` user in `/etc/passwd`, which is what tied the two findings together. With a netcat listener running, requesting the file through the LFI:

```
GET /?file=/var/lib/tftpboot/shell.php
```

caused Apache to `include()` the uploaded file, PHP executed it as the `www-data` user, and the reverse shell connected back. This is a good illustration of why LFI is rated as a high-severity finding even when it "only" reads files: the moment an attacker can place a file anywhere the include path can reach — via an upload form, a log file, a shared file service, or in this case an unrelated UDP protocol — LFI becomes remote code execution.

## Privilege Escalation

Once on the box as `www-data`, the natural next step was to look at the web root for configuration leftovers. `/var/www/html/` contained a `.htaccess` file with commented-out Basic Auth directives, and alongside it a `.htpasswd` file containing a username and what was effectively a plaintext password (an old/weak hash format that resolved trivially). The `.htaccess` rules referencing it had been disabled, but the file itself was never cleaned up — a common pattern where deprecated configuration is left in place "just in case."

The real find was that the password in `.htpasswd` was *also* the Linux system password for that user. Password reuse across application-layer auth and OS-layer auth is one of the most common real-world findings, and it turned a leftover web config file into a full user shell via `su`. From there, `user.txt` was readable in the user's home directory.

The escalation to root came down to group membership: `id` showed the user belonged to the `lxd` group. LXD is a daemon that manages LXC containers, and it runs with root privileges — critically, **any member of the `lxd` group can create a container with `security.privileged=true` and bind-mount the host's root filesystem into it**, with no further privilege checks. This is functionally equivalent to root access on the host, and it's been a known, accepted-as-by-design behavior of LXD for years (it's documented as "this is intended" rather than a bug, which is exactly why it shows up so often on vulnerable-by-misconfiguration boxes).

The practical steps were:

1. Obtain an Alpine Linux container image (`rootfs.squashfs` + a metadata tarball) for the matching architecture and transfer both files to the target via a simple Python HTTP server.
2. `lxc image import <metadata>.tar.xz <rootfs>.squashfs --alias alpine`
3. `lxc init alpine privesc -c security.privileged=true`
4. `lxc config device add privesc host-root disk source=/ path=/mnt/root recursive=true`
5. `lxc start privesc && lxc exec privesc /bin/sh`

Inside the container, `id` reported `uid=0(root) gid=0(root)`, and the host's entire filesystem was readable/writable under `/mnt/root`, including `/mnt/root/root/root.txt`.

## Key Takeaways

- **LFI is a write-primitive multiplier, not just a read bug.** The vulnerability itself only reads files, but paired with *any* mechanism that writes attacker-controlled content to disk — TFTP here, but equally a log file, an upload field, or a mail spool — it becomes RCE. When assessing LFI severity, always ask "what else on this host can write files I can then include?"
- **`/etc/passwd` is reconnaissance, not just a "did the LFI work" check.** The presence of service accounts (tftp, ftp, mail, etc.) tells you what's *probably* running even if a TCP scan didn't show it — UDP services in particular are easy to miss without this kind of cross-reference.
- **UDP scanning matters.** A TCP-only scan would have completely missed the TFTP service that made this chain possible. `sudo nmap -sU` is slow but it's often where the second half of a kill chain lives.
- **Password reuse between app-layer and OS-layer credentials remains one of the highest-value findings in any assessment** — a single `.htpasswd` left over from a disabled Basic Auth config handed over a full user account.
- **The `lxd` group is effectively `root` group membership.** This maps to MITRE ATT&CK T1611 (Escape to Host) and is a standard check in any Linux privesc enumeration (`id`, `groups`) — if a low-priv user is in `lxd`, `docker`, or `disk`, treat it as game over before looking anywhere else.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | TCP/UDP port discovery | `-sC -sV -Pn --top-ports 1000`, `-sU` |
| `curl` | LFI confirmation, TFTP upload, LFI-triggered execution | `?file=...`, `-T shell.php tftp://...` |
| PHP reverse shell | Code execution as `www-data` | classic `pentestmonkey`-style fsockopen shell |
| `nc` | Catch the reverse shell | `-lvnp` |
| `su` | Lateral movement via reused credentials | — |
| `lxc` | LXD-group privilege escalation | `image import`, `init -c security.privileged=true`, `config device add ... disk`, `exec` |
| `python3 -m http.server` | File transfer of the container image to the target | — |
