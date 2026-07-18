# Malmberg

Malmberg is a self-hosted photo and video display system. A **Server** role runs on
a mini-PC or NUC with mirrored ZFS storage and handles ingest, deduplication, and
serving. A **Display** role runs on a Raspberry Pi connected to any screen and cycles
through a configurable slideshow. The two roles discover each other automatically
over UDP; no cloud account, no subscription, and no internet connection is required.

| | |
|---|---|
| **New here?** | [Getting started](getting-started.md) |
| **What to buy** | [Hardware overview](hardware/README.md) / [Server hardware](hardware/server.md) / [Display hardware](hardware/display.md) / [Board profiles](hardware/profiles.md) |
| **Running it** | [Provisioning](operations/provisioning.md) / [Server build (ZFS mirror)](operations/server-build.md) / [Bulk upload](operations/bulk-upload.md) / [Cloud sync](operations/cloud-sync.md) / [Troubleshooting](operations/troubleshooting.md) / [Upgrading](operations/upgrading.md) |
| **Configuring** | [Server config](software/configuration.md#server-configuration) / [Display config](software/configuration.md#display-configuration) |
| **API** | [HTTP API reference](software/api-reference.md) |
| **Development** | [Modules](software/modules.md) / [Testing](software/testing.md) / [Contributing](software/contributing.md) |
| **Design** | [Design docs](design/README.md) |

## Tested hardware

| Role | Hardware | Notes |
|------|----------|-------|
| Server | Generic x86 (any Linux machine) | Suitable for testing |
| Server | Intel NUC or mini-PC | **Recommended** for production |
| Server | Any machine with mirrored ZFS storage | Ideal for long-term reliability |
| Display | Raspberry Pi Zero 2 W | Lowest power; 512 MB RAM limits preload queue |
| Display | Raspberry Pi 4 | **Recommended** for most setups |
| Display | Raspberry Pi 5 | Best performance; supports hw video decode |

## Requirements

- Python >= 3.10 on both the server and display machines
- Linux (Ubuntu 22.04+ on the server; Raspbian Bookworm on the Pi)
- ZFS is optional for a quick-start test but strongly recommended for production
