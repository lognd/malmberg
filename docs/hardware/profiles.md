# Hardware profiles

The provisioning script detects the board and writes a `hardware.toml` that
the software reads at startup. This page lists what each supported board gets
and how to override it if detection is wrong.

---

## Capability table

| Board | `hw_video_decode` | `gpio_available` | `max_preload_queue` | `playwright_supported` |
|---|---|---|---|---|
| Raspberry Pi 5 | yes | yes | 4 | yes |
| Raspberry Pi 4 (4 GB / 8 GB) | yes | yes | 4 | yes |
| Raspberry Pi 4 (1 GB / 2 GB) | yes | yes | 2 | no |
| Raspberry Pi Zero 2 W | no | yes | 2 | no |
| Generic x86 (fallback) | no | no | 4 | yes |

**Capability definitions:**

| Field | What it controls |
|---|---|
| `hw_video_decode` | Whether mpv uses hardware-accelerated video decode (`hwdec=auto`) or software decode (`hwdec=no`). Disable on boards where hardware decode causes green frames or crashes. |
| `gpio_available` | Whether the button input driver tries to open `/dev/gpiomem`. Always `false` on x86. |
| `max_preload_queue` | Depth of the slideshow preload queue. Lower values reduce peak RAM usage on constrained boards. |
| `playwright_supported` | Whether the setup script offers to install Chromium for web overlays (clock, weather). Set `false` on boards with less than 1 GB RAM. |

---

## How detection works

The provisioning script reads `/proc/device-tree/model` (present on Raspberry Pi
boards) and matches against known strings:

| `/proc/device-tree/model` contains | Detected as |
|---|---|
| `Raspberry Pi 5` | pi-5 |
| `Raspberry Pi 4` | pi-4 |
| `Raspberry Pi Zero 2` | pi-zero-2w |
| anything else / file absent | generic-x86 (fallback) |

If the file is absent or unreadable, the fallback profile is used with a warning
logged. The fallback profile is safe on any hardware: `hw_video_decode=false`,
`gpio_available=false`, `playwright_supported=true` (x86 has enough RAM),
`max_preload_queue=4`.

---

## Overriding detection

Edit `/etc/malmberg/hardware.toml` after provisioning. The file is plain TOML:

```toml
name = "pi-4"
hw_video_decode = true
gpio_available = true
status_panel_bus = "none"
max_preload_queue = 4
playwright_supported = true
```

Common reasons to edit manually:

- You have a Pi 4 2 GB and want to enable `playwright_supported` anyway (risky;
  Chromium will be killed by the OOM killer if memory pressure is high).
- Detection failed (file not found) but you are actually on a Pi 4 and want
  hardware decode.
- You have attached an I2C or SPI status panel and need to set `status_panel_bus`.

The software re-reads `hardware.toml` on each startup; restart the service after
editing.

---

## Status panel bus

`status_panel_bus` controls the optional physical status display (e-ink or OLED).

| Value | Meaning |
|---|---|
| `"none"` | No physical status panel; all panel operations are no-ops |
| `"i2c"` | Panel is wired to the Pi's I2C bus (GPIO 2/3, pins 3/5) |
| `"spi"` | Panel is wired to the Pi's SPI bus |

The detection script sets this to `"none"` for all profiles by default because
panel wiring varies. Set it manually if you have a panel attached.

Supported panel drivers: `luma.oled`, `luma.eink` (install separately; not
included in the base package).

---

## Running on unsupported hardware

Malmberg will run on any Linux machine that can run Python 3.10 and pygame.
If your board is not automatically detected:

1. Run setup normally; it will use the generic-x86 fallback.
2. Check the printed summary for any warnings about capabilities.
3. Edit `/etc/malmberg/hardware.toml` to set the correct values for your board.
4. `sudo systemctl restart malmberg-display`

If you get it working on a board not listed here, consider opening a pull request
to add detection support.
