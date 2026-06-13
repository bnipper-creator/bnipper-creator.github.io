---
title: "Mirage — HTB Writeup"
date: 2026-06-12
draft: false
---

# Mirage — HTB Writeup & Reflection

**Difficulty:** Hard | **OS:** Windows (Active Directory Domain Controller) | **Date:** June 2026

## Overview

Mirage is a hard-difficulty Windows Domain Controller that strings together almost
every category of AD weakness in one box: an unauthenticated NFS misconfiguration,
insecure dynamic DNS updates, a credential leak through an internal message bus, classic
Kerberoasting, cross-session NTLM hash theft, ACL/DACL abuse on a disabled account,
gMSA password disclosure, and finally an AD CS ESC10 certificate-mapping abuse chained
into Resource-Based Constrained Delegation (RBCD) and a DCSync. Individually, every one
of these issues is "well known." What makes Mirage interesting is how each step's output
becomes the next step's input — there's no single silver bullet, just a long, logical
chain of small misconfigurations.

## Kill Chain Summary

1. Mount an unauthenticated NFS share exposing internal pentest reports.
2. Use the reports' own findings against the domain: abuse insecure dynamic DNS updates
   to re-point a missing internal hostname (`nats-svc.mirage.htb`) at our attacker host.
3. Stand up a rogue NATS server; capture the real client's authentication attempt and
   recover credentials from the raw packet capture (the application log redacted them,
   the wire didn't).
4. Use those NATS credentials to read a JetStream log stream containing a second set of
   plaintext domain credentials.
5. Kerberoast a service account from that foothold, crack it offline, and get an initial
   WinRM session as a domain user (Kerberos-only domain — NTLM is fully disabled).
6. Notice a second user has an active interactive session on the DC; coerce and relay
   that user's authentication to steal their NetNTLMv2 hash, then crack it.
7. Use that user's group membership to reset the password, fix the logon hours, and
   re-enable a disabled "service" account via DACL abuse.
8. Use the re-enabled account to read a gMSA's password.
9. Abuse a WriteProperty right the gMSA holds over another user's UPN, combined with a
   misconfigured CA (ESC10), to request a certificate that authenticates as the Domain
   Controller's machine account.
10. Use the DC machine account's certificate to set up RBCD against itself, granting a
    domain user S4U2Proxy rights — then DCSync the Administrator hash and log in.

## Recon & Enumeration

A standard `nmap -p-` against the target showed exactly the profile of a Domain
Controller (Kerberos 88, LDAP 389/3268, SMB 445, DNS 53) plus two services that don't
normally appear on a DC: NFS (111/2049) and a NATS message broker (4222, identified via
nmap's service fingerprinting as `nats-server` v2.11.x with `auth_required: true`).

`showmount -e` against the DC revealed an NFS export, `/MirageReports`, exported to
"everyone" — no Kerberos, no IP restriction, nothing. Mounting it read-only handed over
two PDFs that read like real internal incident reports:

- An **incident report** documenting that the DNS record for `nats-svc.mirage.htb` had
  been removed by DNS scavenging (the host had been offline >14 days, exceeding the
  zone's no-refresh/refresh intervals), and — critically — that the zone allows
  **Nonsecure and Secure dynamic updates**.
- A **security hardening report** describing the domain's phased move to Kerberos-only
  authentication and the disabling of NTLM.

Both documents read as "lessons learned" writeups, but together they're a roadmap: one
tells you a hostname is dangling and DNS will accept anonymous updates for it; the other
tells you that *anything* you do later needs to work over Kerberos, not NTLM.

## Foothold

I verified the dynamic-update finding directly with `nsupdate`, adding an arbitrary test
record with no authentication required — confirmed. I then added an `A` record for
`nats-svc.mirage.htb` pointing at my attacker box and started a rogue `nats-server`
under a packet capture.

Within seconds, the DC connected to "nats-svc" (now pointing at me) and attempted to
authenticate as `Dev_Account_A`. The NATS server's own debug log redacted the password
in its output — but the raw TCP capture didn't. The CONNECT frame on the wire contained
the cleartext password in plain JSON.

This is the crux of the foothold: **a fixed, hardcoded service hostname plus a DNS zone
that accepts anonymous dynamic updates equals a free credential-capture proxy.** Any
service that's configured to "just connect to nats-svc.mirage.htb" will happily hand its
credentials to whoever currently owns that DNS name — and on a zone with scavenging
enabled and dynamic updates allowed, that can be anyone.

With `Dev_Account_A`'s credentials, I connected to the *real* NATS server and listed
JetStream streams. A stream called `auth_logs` contained several messages — base64-encoded
JSON blobs logging a username and password for `david.jjackson`, apparently captured by
some internal logging/auditing process. This is a second-order credential leak: an
internal observability tool was faithfully logging authentication attempts, including
the plaintext password, into a stream that the `dev` account could read.

`david.jjackson`'s credentials worked over Kerberos (NTLM is disabled domain-wide, as the
hardening report promised). From there, a standard Kerberoast (`GetUserSPNs`) turned up
`nathan.aadam`, a member of `Exchange_Admins` with an `HTTP/exchange.mirage.htb` SPN.
The resulting TGS-REP hash cracked against `rockyou` in under a minute, giving a Kerberos
TGT and a WinRM session on the DC as `nathan.aadam` — and `user.txt`.

## Privilege Escalation

The interesting part starts here. With a foothold but no juicy group memberships, the
next move was lateral, not vertical.

**Cross-session credential theft.** Checking active sessions (which required spawning a
process under a different logon type, since a plain WinRM session can't enumerate other
users' sessions) showed a second user, `mark.bbond`, had an active interactive console
session on the DC. Using `RemotePotato0` — a tool that abuses DCOM activation to coerce
a victim's session into authenticating to an attacker-controlled RPC endpoint — combined
with a `socat` relay back to the attacker host, I captured `mark.bbond`'s NetNTLMv2 hash.
It cracked instantly against `rockyou`. This is the same family of attack as "Hot Potato"
/ "Rogue Potato" — local privilege escalation and lateral movement via DCOM/NTLM
coercion, still very much alive on systems where unprivileged local sessions can trigger
COM activation.

**DACL abuse on a disabled account.** `mark.bbond` belonged to an `IT_SUPPORT` group with
several interesting rights over `javier.mmarshall`, an account sitting in an
`OU=Disabled` container with `ACCOUNTDISABLE` set and restrictive logon hours:
`ForceChangePassword`, and `WriteProperty` over both `User-Account-Control` and
`Logon-Hours`. None of this was visible as a simple "can compromise" edge until I dumped
the raw ACEs — it's the kind of fine-grained, attribute-level delegation that's easy to
grant for legitimate helpdesk reasons and easy to forget represents a full account
takeover path. I reset the password, rewrote `logonHours` to all-`0xFF` (24/7 allowed),
and cleared `ACCOUNTDISABLE` — turning a "revoked" account back into a usable one.

**gMSA password disclosure.** `javier.mmarshall` was listed as a principal allowed to
read the password of a Group Managed Service Account, `Mirage-Service$`. Reading gMSA
passwords is a documented, intended LDAP operation for authorized principals — the
"vulnerability" is purely that the authorization was granted too broadly.

**ESC10 + targeted ACL = certificate-based impersonation of the DC.** This is the chain's
centerpiece. Two AD CS registry settings on the DC made it vulnerable to **ESC10 (Case
2)**: `CertificateMappingMethods` includes the UPN-mapping bit, and Kerberos
`StrongCertificateBindingEnforcement` is set to *Compatibility* rather than *Full*. In
plain terms: a certificate's Subject Alternative Name (UPN) is trusted to identify an
account, without cross-checking the certificate's embedded SID against that account's
real SID.

Separately, `Mirage-Service$` (the gMSA whose password I now had) held `WriteProperty`
over the `Public-Information` property set of `mark.bbond` — which includes
`userPrincipalName`. So: authenticate as `Mirage-Service$`, temporarily rewrite
`mark.bbond`'s UPN to `DC01$@mirage.htb` (the Domain Controller's own machine account
UPN), then — still as `mark.bbond` — request a certificate from the domain CA (which
grants `Enroll` to Authenticated Users). Because of ESC10, the issued certificate carries
the UPN `DC01$@mirage.htb` and is treated as proof of the DC's machine-account identity.
Revert the UPN immediately afterward to leave no lasting modification on `mark.bbond`.

**RBCD + DCSync.** Authenticating with that certificate produces a session as `DC01$`.
Any machine account is allowed to write its own
`msDS-AllowedToActOnBehalfOfOtherIdentity` attribute — so as `DC01$`, I configured
Resource-Based Constrained Delegation granting `nathan.aadam` the right to impersonate
arbitrary users *to* `DC01$`. From `nathan.aadam`, an S4U2Self/S4U2Proxy request produced
a service ticket for `cifs/dc01.mirage.htb` *as the Domain Controller*. Domain Controller
computer accounts have `GetChanges`/`GetChangesAll` (DCSync) rights by default, so that
ticket was enough to dump the `Administrator` NTLM hash via `secretsdump`. A final
`getTGT` with that hash and a WinRM session gave `root.txt`.

## Key Takeaways

1. **DNS dynamic updates and scavenging are a dangerous combination.** A zone that
   accepts anonymous updates plus scavenging that removes "stale" records for offline
   hosts creates a recurring window where an attacker can claim a trusted internal
   hostname. This maps to MITRE ATT&CK T1584.002 (Acquire Infrastructure: DNS
   Server) / T1557 (Adversary-in-the-Middle) in spirit, even though it's "just" a DNS
   record.
2. **Redacted logs aren't a substitute for not transmitting secrets in the clear.**
   The NATS server's debug output redacted the password; the TCP stream did not. Any
   place that "redacts for safety" but still sends plaintext over the wire (or into
   another log a different user can read, as with the `auth_logs` JetStream stream) is
   a credential leak waiting to be found.
3. **Fine-grained ACL delegation (logon hours, UAC bits, force-password-reset) is
   functionally equivalent to full account control** if the target account can later be
   used as a stepping stone. "Helpdesk can unlock/re-enable accounts" is a reasonable
   business requirement that's very hard to scope safely in AD's ACL model.
4. **ESC10 is subtle because it's a *registry* misconfiguration, not a template
   misconfiguration** — it won't show up in a certificate-template-focused review.
   Combined with even a narrow `WriteProperty` over `userPrincipalName`, it lets an
   attacker mint a certificate for *any* account whose UPN they can (temporarily)
   control, including machine accounts.
5. **RBCD is "self-service" by design** — any computer object can configure delegation
   onto itself — which is fine until an attacker can authenticate *as* that computer
   account even briefly. A few seconds of impersonation is enough to leave a durable
   delegation relationship that survives long after the certificate trick is reverted.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nsupdate` / `dig` | Confirm and abuse insecure dynamic DNS updates | `update add <host> A <ip>` |
| `nats-server` / `nats` CLI | Stand up rogue broker; query streams on real broker | `stream ls`, `stream get -j` |
| `tcpdump` | Capture plaintext creds redacted from application logs | `-w capture.pcap port 4222` |
| `impacket-GetUserSPNs` / `john` | Kerberoast and crack TGS hash | `-request`, `--format=krb5tgs` |
| `evil-winrm` | Kerberos-authenticated WinRM shell | `-r <realm>` with `KRB5CCNAME` |
| `RunasCs` | Run command under alternate logon session | `-l 9` (NewCredentials) for `qwinsta` |
| `RemotePotato0` + `socat` | Coerce/relay another session's NTLM auth | `-m 2 -s 1 -x <ip> -p <port>` |
| `net rpc password` / `ldapmodify` / `bloodyAD` | DACL abuse: reset password, fix logon hours, clear ACCOUNTDISABLE | `remove uac ... -f ACCOUNTDISABLE` |
| `netexec` (`--gmsa`, `daclread`) | Read gMSA password; enumerate raw ACEs | `-M daclread -o TARGET=...` |
| `certipy` | ESC10 cert request and PKINIT/Schannel auth as DC machine account | `req -ca ...`, `auth -pfx ... -ldap-shell` |
| `impacket-getST` / `impacket-secretsdump` | S4U2Proxy via RBCD; DCSync | `-impersonate`, `-just-dc-user` |
