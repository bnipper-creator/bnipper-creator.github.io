---
title: "Principal — HTB Writeup"
date: 2026-06-12
draft: false
---

**Difficulty:** Medium | **OS:** Linux | **Date:** June 2026

## Overview

Principal is a medium-difficulty Linux box built around a single idea applied twice:
a system can faithfully verify a *cryptographic envelope* while completely
ignoring the *identity claim* sealed inside it. The foothold abuses an
authentication-bypass vulnerability in the pac4j-jwt library (tracked as
CVE-2026-29000), where an encrypted-but-unsigned token sails past signature
verification. The privilege escalation abuses an SSH Certificate Authority
configuration that trusts any certificate the CA signs without checking *who*
the certificate claims to be. Both bugs are really the same bug, wearing
different clothes — which is what makes this box such a clean teaching example.

## Kill Chain Summary

1. Enumerate a Jetty web app on port 8080 ("Principal Internal Platform"),
   identify it as running `pac4j-jwt/6.0.3`.
2. Pull the public encryption key from `/api/auth/jwks`.
3. Exploit CVE-2026-29000 to forge an admin-level authentication token without
   ever knowing a password or holding the signing key.
4. Use the forged admin session to read user lists and a leaked credential
   from the application's settings page.
5. Password-spray SSH with that credential — one service account reuses it.
6. SSH in as that account, find it belongs to a group with read access to an
   SSH CA private key.
7. Forge a new SSH certificate naming `root` as the principal, sign it with
   the stolen CA key, and authenticate as root.

## Recon & Enumeration

A standard `nmap -sC -sV` sweep showed only two open ports: SSH (22) and an
HTTP service on 8080 fronted by Jetty. The HTTP service redirected to `/login`
and immediately advertised its stack in the `X-Powered-By` header:
`pac4j-jwt/6.0.3`. That header is a gift — pac4j is a Java security/auth
framework, and having the exact minor version up front makes vulnerability
research trivial.

Rather than blind directory brute-forcing, I went straight for the client-side
JavaScript at `/static/js/app.js`. Front-end bundles for "internal platform"
style apps are frequently undermin­ified and littered with comments describing
the auth flow — and this one was no exception. It documented the entire token
lifecycle: login returns a JWE (JSON Web Encryption) token, encrypted with
RSA-OAEP-256/A128GCM, wrapping an inner JWT that's *supposed* to be signed with
RS256. It also pointed at `/api/auth/jwks`, which served the RSA **public
encryption key** used to seal tokens.

That's an interesting asymmetry worth sitting with: the server published its
encryption public key (so clients/attackers can construct valid JWEs), but the
*signing* key for the inner JWT was nowhere to be found. Normally that's fine —
you can encrypt a token to the server, but you can't forge a *valid* one
because you can't sign the payload. Unless, of course, the server doesn't
actually require a signature in every code path.

## Foothold

This is where CVE-2026-29000 comes in. The vulnerability lives in pac4j-jwt's
`JwtAuthenticator` when an application is configured to use *both* JWE
encryption and JWS signing for its tokens (a very common "defense in depth"
setup). The validation logic looks roughly like this:

1. Receive a JWE token, decrypt it with the server's RSA private key.
2. Take the decrypted payload and call `toSignedJWT()` on it to get a signed
   JWT object for signature verification.
3. **If the decrypted payload is an unsigned "PlainJWT"** — a JWT with header
   `{"alg":"none"}` and an empty signature segment — `toSignedJWT()` returns
   `null`, because a plain JWT isn't a *signed* JWT.
4. The code then checks `if (signedJWT != null)` before running signature
   verification.
5. When that's `null`, the entire signature check is skipped. The decrypted
   claims are trusted as-is.

In other words: as long as you can produce something the server will
successfully *decrypt*, you can put whatever claims you want inside it, and
nothing ever checks who actually signed those claims — because nothing was
signed at all, and the code silently treats "nothing to verify" as "verified."

This is the textbook failure mode for hybrid encrypt+sign schemes: encryption
proves the message reached the right *recipient* (confidentiality), but only a
signature proves who the message came from (authenticity/integrity). The bug
collapses those two guarantees into one and only checks the first.

Exploitation is mechanical once you have the public encryption key from the
JWKS endpoint:

1. Build a JSON payload with the claims the app expects — `sub: admin`,
   `role: ROLE_ADMIN`, the right `iss`, and a fresh `iat`/`exp`.
2. Base64url-encode a `{"alg":"none"}` header and the payload, and join them
   with dots and a trailing empty signature segment — `header.payload.` — to
   form a PlainJWT.
3. Wrap that PlainJWT as the plaintext of a JWE, encrypted with the server's
   RSA public key using the exact `alg`/`enc`/`kid` the server expects
   (`RSA-OAEP-256` / `A128GCM` / the `kid` from JWKS), with `cty: JWT` in the
   protected header so the server knows to unwrap an inner JWT.
4. Send the resulting compact JWE as a Bearer token.

The server decrypted it fine (it has the matching private key), unwrapped a
PlainJWT, found nothing to verify, and handed back a 200 with
`"username": "admin", "role": "ROLE_ADMIN"`. No credentials, no signing key,
full admin session — purely from knowing the *public* key and the claims
schema, both of which were handed to us by the front-end bundle.

From the admin dashboard, `/api/users` enumerated every account on the
platform, and `/api/settings` exposed an "encryption key" value in its
security section. That value turned out to be a password — a clear case of a
secret meant for one purpose (token encryption configuration) being reused as
a literal account credential elsewhere. A quick SSH password spray across the
harvested usernames found exactly one hit: a service account whose password
matched the leaked value. That got us a shell and the user flag.

## Privilege Escalation

The compromised service account belonged to a secondary group with read access
to a directory containing SSH Certificate Authority material: a CA private key
and its corresponding public key. A README in that directory explained the
intent — the CA is trusted by `sshd` to issue short-lived certificates for
automated deployment logins.

Checking the sshd configuration revealed the second half of the "envelope
without identity" theme: `TrustedUserCAKeys` pointed at the CA's public key,
but there was **no** `AuthorizedPrincipalsFile` and **no**
`AuthorizedPrincipalsCommand` configured. Per OpenSSH's certificate
authentication model, when neither of those is set, sshd falls back to
checking whether the *username being logged in as* appears among the
certificate's `principals` — and it accepts **any** certificate that the
trusted CA signed, regardless of who requested it or what it's "for."
`PermitRootLogin prohibit-password` blocked password-based root logins, but
said nothing about certificate-based ones.

Holding the CA's private key meant we could mint our own certificate. The
attack was:

```bash
ssh-keygen -t ed25519 -f /tmp/pwn -N ""
ssh-keygen -s /opt/principal/ssh/ca -I "pwn-root" -n root -V +1h /tmp/pwn.pub
ssh -i /tmp/pwn root@localhost
```

The `-n root` flag sets the certificate's principal list to `root`. sshd
verified the certificate's signature against the trusted CA (valid — we signed
it with the real CA key), saw `root` in the principals, and — with no
allowlist to consult — happily logged us in as root.

Structurally, this is identical to the foothold: the *cryptographic envelope*
(a CA-signed certificate, or a JWE that decrypts cleanly) was perfectly valid,
and the system stopped checking right there. Neither layer asked the follow-up
question that actually matters for authorization: *valid according to whom,
asserting what, on whose behalf?*

## Key Takeaways

1. **Encryption and authentication are different guarantees — don't let one
   substitute for the other.** A successfully-decrypted message tells you it
   reached the intended recipient. It tells you nothing about who sent it
   unless it's *also* signed and that signature is *actually checked*. The
   pac4j bug exists because a library treated "I couldn't verify a signature"
   (null) the same as "there was nothing to verify" instead of "this is
   unauthenticated, reject it."

2. **"Defense in depth" can create a logical OR instead of an AND.** Combining
   JWE + JWS sounds stricter than either alone, but if the code path for "no
   signature present" silently bypasses the signature check rather than
   failing closed, you've built a system where *either* layer being absent
   defeats the other layer too. Fail-closed defaults matter most exactly where
   two controls overlap.

3. **Front-end bundles are reconnaissance gold for internal apps.** The
   client-side JS here documented the entire token format, claim schema, and
   API surface — effectively a spec for building the exploit payload. Treat
   `app.js`/source maps on internal tools as part of your attack surface, not
   an afterthought after directory brute-forcing comes up empty.

4. **`TrustedUserCAKeys` without `AuthorizedPrincipalsFile`/`Command` is a
   common, severe SSH CA misconfiguration.** This maps to a recurring theme in
   MITRE ATT&CK around Valid Accounts (T1078) and certificate-based persistence
   — if you operate an SSH CA for automation, the principal allowlist isn't
   optional, it's the entire access-control layer. Without it, possession of
   the CA key (or, worse, anyone who can get the CA to sign *anything*) is
   equivalent to root.

5. **Secrets get reused across boundaries more often than designers intend.**
   A value labeled as a JWT "encryption key" in an admin settings panel turned
   out to double as a live SSH password for a service account. Any exposed
   secret — even one that looks scoped to a narrow technical purpose — is
   worth testing against every other credential surface you can reach.

## Tools & Techniques

| Tool | Purpose | Notable flags used |
|---|---|---|
| `nmap` | Initial port/service enumeration | `-sC -sV -Pn` |
| `curl` | Pulling `app.js`, JWKS, and authenticated API endpoints | `-H "Authorization: Bearer ..."` |
| `jwcrypto` (Python) | Constructing the forged JWE-wrapped PlainJWT for CVE-2026-29000 | `jwe.JWE(...).serialize(compact=True)` |
| `nxc` (NetExec) | SSH password spray against harvested usernames | `nxc ssh <ip> -u users.txt -p '<pw>'` |
| `ssh-keygen` | Generating an attacker keypair and forging an SSH certificate with the stolen CA key | `-s <ca> -I <id> -n root -V +1h` |
