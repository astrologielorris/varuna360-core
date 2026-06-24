# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in Varuna360 Core,
please report it **privately**. Do **not** open a public GitHub issue.

**Preferred channel:** email **security@360heartsinthesky.com** with:

- A description of the issue and its impact
- Steps to reproduce (including any proof-of-concept code)
- The commit hash or version number you tested against
- Whether you want to be credited in the advisory

We will acknowledge your report within a reasonable timeframe and work
with you on a coordinated disclosure.

## Scope

In-scope:

- Remote code execution via crafted chart files (`.chtk`)
- Local privilege escalation through Varuna360 Core
- Sensitive data leakage (secrets, personal data, filesystem access)
- Dependency vulnerabilities that affect Varuna360 Core

Out-of-scope:

- The proprietary Varuna360 Pro edition (reported separately)
- Social engineering, physical attacks, or denial-of-service via
  resource exhaustion
- Issues in third-party services linked from the project

## Known sensitive defaults

- `managers/license_manager.py` contains a **public** Firebase REST API
  key and a **public** RSA verification key. Both are intended to be
  embedded in the client and are not secrets. Server-side API
  restrictions enforce the actual security boundary.

Thank you for helping keep Varuna360 Core safe.
