# Security Policy

Owner: owner
Status: **Initial draft** — to be hardened after the next full security audit
Last updated: 2026-06-20

> This document is an intentional starting point. It captures the project's
> current security posture and reporting process using known design decisions
> and sensible defaults. It will be reviewed and finalized following the next
> scheduled security audit. Anything marked _TODO_ needs owner confirmation
> before this policy is considered authoritative.

---

## Overview

**Unicorn Viz** is a desktop demoscene visualizer for Linux (Python 3.11+,
OpenGL via `moderngl`, audio via PipeWire/ALSA, optional MIDI). It runs locally
on an operator's machine and renders fullscreen visuals. It is **not** a network
service and does not accept inbound connections.

The practical security surface is therefore:

- **Local untrusted input** — config files, ANSI/CP437 art assets, audio, MIDI.
- **Outbound network** — a small, explicitly scoped set of network features
  (art fetching, optional Spotify/chat/lyrics integrations).
- **Local secrets** — optional OAuth tokens for the Spotify drop-in, an Ably
  API key for the chat drop-in.
- **Optional drop-ins** — feature modules loaded as git submodules.

---

## Supported Versions

Unicorn Viz is **pre-1.0**. Security fixes are applied to the latest `master`
and the most recent tagged release only. Older snapshots are not maintained.

| Version | Supported |
|---------|-----------|
| `master` (latest) | ✅ |
| Latest tagged release | ✅ |
| Older / pre-release tags | ❌ |

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Preferred channel:

1. **GitHub Private Vulnerability Reporting** — use the **"Report a
   vulnerability"** button under the repository's **Security** tab
   (`https://github.com/iDoMeteor/unicorn-viz/security`). This keeps the report
   private and tracked.

Alternative channel:

2. **Email** — _TODO: add a dedicated security contact address._ Until then,
   private vulnerability reporting above is the canonical channel.

When reporting, please include:

- A clear description of the issue and its security impact.
- Step-by-step reproduction (config, asset, or input that triggers it).
- Affected version / commit hash and your platform (distro, compositor, audio
  server).
- Any proof-of-concept, logs, or crash output (please redact personal data).

### What to expect

- **Acknowledgement:** we aim to acknowledge a report within _TODO: N business
  days_.
- **Assessment & fix:** we will triage severity, keep you updated, and work on a
  fix on a private branch.
- **Disclosure:** we follow **coordinated disclosure** — we ask that you give us
  reasonable time to ship a fix before any public disclosure, and we will credit
  reporters who wish to be named.

---

## Scope

**In scope:**

- The core `unicornviz/` package.
- First-party drop-ins under `drop-ins/`.
- Helper scripts under `tools/` and packaging/installer scripts.

**Out of scope (report upstream / not tracked here):**

- Vulnerabilities in third-party dependencies — report to the upstream project;
  see [Dependency & Supply-Chain](#dependency--supply-chain) below.
- Issues requiring a pre-compromised host, physical access, or a malicious OS
  account already running as the user.
- Social engineering of maintainers or operators.
- Findings that depend on the operator deliberately loading untrusted,
  attacker-supplied drop-in code (drop-ins are trusted-by-installation).

---

## Security Model & Design Decisions

These are the standing rules the codebase is built to (see `CLAUDE.md` for the
authoritative engineering policy):

### Code execution & injection
- **No `eval()` / `exec()` of configuration values.** Config is parsed with the
  stdlib `tomllib` only.
- **No shell commands constructed from user-supplied strings.** Subprocess use
  (e.g., device probing, `ffmpeg`) uses argument lists, not shell strings, and
  external probes are bounded with timeouts.

### Filesystem
- Paths from config are resolved via `pathlib.Path` and are expected to stay
  within the project root or explicitly whitelisted directories (path-traversal
  containment).

### Network
- The core application (`unicornviz/`) performs **no network requests at
  runtime**. All outbound network access lives in optional drop-ins or
  developer tooling, and is opt-in per feature:
  - `tools/fetch_acid_ans.py` — downloads ANSI art packs from 16colo.rs (a
    developer/asset tool, not the runtime hot path).
  - The optional **Spotify drop-in** (`drop-ins/spotify-01/`) — talks to the
    Spotify Web API when enabled by the operator.
  - The optional **chat drop-in** (`drop-ins/chat-01/`) — maintains a
    persistent **Ably Realtime** subscription (a managed pub/sub service) to
    receive inbound chat messages from a companion web widget. This is the
    project's only long-lived/inbound-adjacent network connection; the
    channel only carries display text (rendered as an overlay), and message
    content is not executed or parsed as anything but text.
  - The optional **lyrics drop-in** (`drop-ins/lyrics-01/`) — queries the
    public **LRCLIB** API (`https://lrclib.net/api/get`) to fetch synced
    lyrics for the currently-playing track.

### Untrusted asset parsing
- ANSI/CP437 art is parsed by a single dedicated parser
  (`unicornviz.ansi.loader.ANSIParser`); bytes are decoded as CP437, SAUCE
  records are optional and handled gracefully, and oversized/malformed art is
  clipped rather than trusted. Downloaded art is committed to the repo and
  reviewed.

### Input privacy
- MIDI note data is **not** logged at `INFO` level or above (it can carry
  identifying controller data).

---

## Secrets & Credential Handling

The only credentials the project handles are for the **optional** Spotify
integration:

- Authentication uses **Authorization Code with PKCE** — the Spotify
  **Client Secret is never stored or embedded** in runtime/client code; the
  local runtime operates on the **Client ID only**.
- Loopback redirect URIs use `http://127.0.0.1` (not `localhost`, not
  wildcards).
- Tokens are stored in **gitignored local runtime files**, with refresh logic so
  auth does not silently expire.
- Only the minimum required scopes are requested.
- A dedicated threat model for this integration lives at
  [`drop-ins/spotify-01/docs/security.md`](drop-ins/spotify-01/docs/security.md).

**No secrets, tokens, or credentials are committed to the repository.** If you
believe a secret has been committed, report it via the channel above.

---

## Dependency & Supply-Chain

- Dependencies are pinned in `requirements.txt`.
- `pip-audit` runs against the dependency set to surface known CVEs.
- `bandit` runs a static security scan over `unicornviz/` and `drop-ins/`.
- Both run as pre-commit / CI gates.
- **Policy:** security-tool findings (bandit / pip-audit) are **reported, not
  silently auto-remediated**. CVEs and static findings are reviewed by the owner,
  who decides on the remediation approach and timing. Findings are never
  suppressed with annotations without explicit review.

---

## Hardening Backlog (to finalize after the next audit)

_This section is a placeholder to be completed during the next security audit._

- [ ] Confirm/define the dedicated security contact email.
- [ ] Define concrete acknowledgement and fix-time SLAs.
- [ ] Document the threat model for ANSI/asset parsing of fully-untrusted files.
- [ ] Review installer/packaging scripts (`install.sh`, `tools/install/`) for
      privilege and path-handling assumptions.
- [ ] Review the recording/streaming subprocess (`ffmpeg`/RTMP) argument
      handling and destination validation.
- [ ] Document the webcam/audio capture permission model per platform.
- [ ] Verify drop-in submodule integrity expectations (pinned commits).
- [ ] Cross-link this policy from `README.md` and `docs/README.md`.

---

## Credits

We appreciate responsible disclosure and will acknowledge reporters who help
keep Unicorn Viz and its operators safe.
