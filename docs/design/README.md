# Malmberg Design

**Version:** 0.2
**Author:** Logan Dapp
**Date:** 2026-06-27

This directory contains the authoritative design documentation for the Malmberg
system. Each file covers one concern.

| File | Contents |
|------|----------|
| [overview.md](overview.md) | System overview and package structure |
| [architecture.md](architecture.md) | Language, transport, rendering, storage, HAL, logging, config |
| [status-panels.md](status-panels.md) | Physical status panel states for both roles |
| [server.md](server.md) | Server provisioning, ingest, file API, hide policy, backup ref |
| [display.md](display.md) | Display provisioning, slideshow engine, offline mode, rendering, UI, API |
| [handshake.md](handshake.md) | Server-Display discovery, pairing PIN, and mutual TLS handshake |
| [backup.md](backup.md) | Server-Server ZFS backup protocol, master/slave election, retention |
| [privacy.md](privacy.md) | Optional privacy filter (opt-in, local-only) |
| [dashboard.md](dashboard.md) | HTMX web dashboard pages |
| [reference.md](reference.md) | Technology reference, coding standards, module ownership |

The prose above is complemented by a machine-checked model:
`design/malmberg.strata` (repo root) declares the real components, code
bindings, capabilities, data flows, trust boundaries, and claims, and is
verified by `frob sys audit` (see docs/software/testing.md for the gate
suite). The two ingress endorsement boundaries it declares are anchored
in code at `malmberg_server/ingest/upload.py` (`frob:boundary` comments).
