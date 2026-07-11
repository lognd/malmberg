# Web Dashboard

> **Implementation note:** the page table below describes an earlier
> HTMX/Jinja2 design. What actually shipped is a single self-contained page
> (`GET /dashboard`, `malmberg_server.api.web.render_dashboard_html`) with
> inline CSS/JS and no build step or external CDNs -- see
> `docs/software/api-reference.md` for the current, accurate endpoint list.
> It folds browse/upload/stats/recycle-bin/controls/programmed-slideshows
> into one page rather than the separate `/ui/*` routes below.
>
> **Second accessor:** the same page is also served by the Display itself at
> its own `GET /dashboard`, so a user in front of the frame does not need to
> know the server's address. The Display proxies library calls (`/media*`,
> `/stats`) to its paired server and answers slideshow controls
> (Previous/Next/Pause/Show/Restart) directly, so browsing, showing a photo,
> viewing details, deleting, and restoring from the recycle bin all work
> identically from either accessor. See "Display-hosted dashboard" in
> `docs/software/api-reference.md`.

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
