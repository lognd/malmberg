# Web Dashboard

A small HTMX frontend served by the Server at `/ui`. No separate build step;
templates are Jinja2, served by FastAPI's `TemplateResponse`. Designed to be
usable from a phone browser on the same LAN.

## Pages

| Path | Content |
|------|---------|
| `/ui` | Overview: disk usage, paired displays, last ingest, system mode |
| `/ui/media` | Browseable media library with thumbnails; hide/delete actions |
| `/ui/trash` | Soft-deleted files; restore or permanently delete |
| `/ui/ingest` | Manual upload form; USB and cloud sync status |
| `/ui/cloud` | Cloud provider management; add/remove accounts |
| `/ui/displays` | Connected displays; remote slideshow control per display |
| `/ui/schedule` | Drag-and-drop playlist scheduling; push to display |
| `/ui/logs` | Streamed log tail; event filter; download log archive |
| `/ui/review` | Privacy filter review queue (only shown if filter is active) |
| `/ui/backup` | Backup history, retention visualization, manual trigger |
| `/ui/settings` | Hot-editable subset of `server.toml` |

The dashboard requires no authentication beyond being on the same LAN and
having a paired device. A future version may add optional password protection.
