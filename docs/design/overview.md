# Overview

## 1. System Summary

Malmberg is a self-hosted media display system composed of two roles:

- **Server** (`malmberg_server`) -- a low-power Linux machine (e.g. mini-PC or
  NUC) with mirrored ZFS storage. Stores photos and videos; exposes an HTTPS
  API; ingests files from phones, USB drives, and cloud sources.
- **Display** (`malmberg_display`) -- one or more single-board computers (e.g.
  Raspberry Pi Zero 2 W) connected to a screen. Discovers the Server on the LAN
  automatically, pulls media, and cycles through a configurable slideshow.

A shared library (`malmberg_core`) provides models, networking primitives, and
logging used by both roles.

The target end-user is non-technical. Every interaction that is not
developer-facing must be operable by someone unfamiliar with Linux or
networking.

## 2. Package Structure

```
src/
  malmberg_core/        -- shared primitives (no role-specific logic)
    logging/            -- split stdout/stderr handlers, configurable via TOML
    models/             -- Tag, MediaItem, and other shared Pydantic models
    networking/         -- MAC address, UDP broadcast helpers
    hal/                -- Hardware Abstraction Layer (see architecture.md)
    compat.py           -- tomllib fallback, Self re-export
    version.py          -- single source of version string

  malmberg_server/      -- file server role
    app/                -- ServerApp, ServerConfig
    api/                -- FastAPI routes
    ingest/             -- USB watcher, cloud sync, upload handler
      cloud/            -- per-provider plugins (iCloud, Google Photos, ...)
    setup/              -- idempotent Ubuntu provisioning script
    backup/             -- ZFS snapshot / slave-sync logic
    ui/                 -- status panel driver (I2C/SPI e-ink or OLED)

  malmberg_display/     -- display role
    app/                -- DisplayApp, DisplayConfig
    api/                -- FastAPI routes (for Server -> Display handshake)
    display/            -- Displayable protocol, PictureDisplay, VideoDisplay, WebDisplay
    slideshow/          -- Slideshow orchestrator, producers
    setup/              -- idempotent Ubuntu/Raspberry Pi provisioning script
    ui/                 -- on-screen overlay, button input, status panel driver
```

Optional extras (not installed unless explicitly requested):

```
extras/
  privacy_filter/       -- face/object detection; separate pip extra [privacy]
```
