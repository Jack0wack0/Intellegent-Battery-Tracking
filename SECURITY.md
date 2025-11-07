# Security policy

This document explains how to report security issues, what to expect after you report, and the basic security practices we recommend for deploying the project. It is intentionally concise — if you discover a vulnerability or have sensitive information to share, please follow the reporting steps below.

## Reporting a Vulnerability


We're a small, two-person project. If you find a security problem, thanks — please tell us. Here's the easiest ways to get it to us:

- Preferred: create a GitHub Security Advisory for this repo (it's private and keeps sensitive details out of public issues).
- If you don't have access to that, open a GitHub issue titled `SECURITY: short description` and we'll follow up there. If the issue is sensitive, tell us in the issue and we'll ask you for a private way to share details (PGP, temporary file, or direct contact).

When you report, helpful info includes:
- A short description of the issue and what you see vs what you expected
- Which files or components are affected (e.g. `MachineA_BatteryCart/input_listener.py`)
- Steps to reproduce or a minimal proof-of-concept (POC)
- Which version or commit the problem appears in

Please do not paste private keys, passwords, or tokens into a public issue. If you must share sensitive details, wait for a private channel from us.

## What to Expect


- We'll try to acknowledge within a few days (usually within 72 hours).
- We'll triage and tell you what we're planning to do (fix, mitigation, or schedule it).

If the issue is serious and affects user data or allows remote compromise, we'll treat it as high priority and aim to fix it quickly.

## Severity & Response Guidance (high-level)


Severity:
- Critical: remote code execution, wide data exposure, leaked credentials — we'll act immediately.
- High: privilege escalation or sensitive data access — high priority.
- Medium/Low: smaller issues that we will schedule into normal work.

## Recommended Security Practices for Deployers


Practical tips we follow and recommend:
- Don't commit secrets. Keep `.env` local and in `.gitignore`.
- Give Firebase/Drive service accounts only the permissions they need.
- Rotate keys if you think they may have been exposed.
- Keep the Pi/VM up to date and run services as a non-root user.
- Use a firewall to block unnecessary inbound access.


## Incident Response Tips (quick)


If something bad happens quickly:
- Revoke/rotate exposed keys immediately.
- Isolate the affected machine, collect logs, and avoid changing evidence until we triage.
- We'll coordinate next steps once we know what happened.

## Supported Versions & End-of-Life


We don't maintain multiple supported releases. Security fixes go into `main`. If you're on a fork or pinned commit you'll need to merge fixes yourself.

## Contact


Contact:

1. Open a GitHub Security Advisory (private) if you can.
2. Otherwise open a GitHub issue titled `SECURITY: ...` and we'll respond.

If you need a private channel to share secrets, post in the issue that it's sensitive and we will ask you for a secure way to transmit details (PGP or similar).

---