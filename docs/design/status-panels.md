# Status Panels

Both the Server and each Display support an optional small physical status
panel (e-ink or OLED, driven over I2C or SPI). The HAL reports which bus is
available; if `status_panel_bus == "none"` the panel subsystem is a no-op.

Status panels show information critical for diagnosing problems without SSH.
All text uses a large, readable font. Critical error states use inverted colors
(white-on-black on OLED; flashing border on e-ink).

## 4.1 Server Status Panel States

| State | Display |
|-------|---------|
| Starting up | `STARTING...` + version |
| Running, no peers | `RUNNING` / IP addr / disk usage / `No displays paired` |
| Running, peers active | `RUNNING` / IP addr / disk usage / `N display(s)` |
| USB ingest in progress | `USB INGEST` + file count + progress bar |
| Cloud sync in progress | `SYNCING` + provider name + item count |
| Backup running (master) | `BACKING UP` + snapshot timestamp |
| Slave syncing | `SLAVE SYNC` + progress |
| Degraded: disk > 90% | `DISK FULL` (inverted) + used/total |
| Error (unhandled exception) | `ERROR` (inverted) + short message + `Check /logs` |
| Offline (no network) | `NO NETWORK` (inverted) + last-online timestamp |

## 4.2 Display Status Panel States

| State | Display |
|-------|---------|
| Starting up | `STARTING...` + version |
| Discovering server | `SEARCHING...` + elapsed time |
| Pairing in progress | `PAIRING` + PIN |
| Online, slideshow running | `ONLINE` / server IP / current item name |
| Online, slideshow paused | `PAUSED` / server IP |
| Degraded: offline cache | `OFFLINE MODE` (inverted) + item count / `Last online: <timestamp>` |
| Cache empty, no server | `NO CONTENT` (inverted) + `Check server` |
| Error (unhandled exception) | `ERROR` (inverted) + short message + `Check /logs` |

The degraded state (`OFFLINE MODE`) is shown with inverted colors and an
explicit timestamp. This state is also reported in `GET /status` and triggers
a warning-level log event.
