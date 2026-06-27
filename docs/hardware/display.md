# Display hardware

A display is a small single-board computer connected to a screen. It runs
Raspbian Bookworm, pulls media from the server, and shows a continuous slideshow.
You can set up as many displays as you want; each pairs with the server independently.

---

## Which Pi to buy

### Raspberry Pi 5 (recommended for new builds)

The Pi 5 is the best choice for a new display build. It has enough RAM for
hardware-accelerated video decode, smooth cross-fades, and the optional
Chromium-based clock/weather overlay.

- **4 GB model** -- enough for photos, video, and web overlays
- **8 GB model** -- comfortable headroom; worth it if you plan heavy video or
  multiple simultaneous overlay tabs

**What you get with a Pi 5:**
- Hardware video decode (H.264, HEVC) via mpv
- Web overlay support (playwright + Chromium)
- Smooth cross-fades at 1080p without frame drops
- Active cooling available (the official Pi 5 case with fan is good)

### Raspberry Pi 4 (good budget option)

The Pi 4 works well for photos and video. Get the **4 GB or 8 GB model**;
the 1 GB and 2 GB models are undersized for video decode and may stutter.

- Hardware video decode available (H.264 via V4L2)
- Web overlays work on 4 GB and 8 GB
- Runs warmer than a Pi 5; use a heatsink case or active cooling

### Raspberry Pi Zero 2 W (small displays only)

The Zero 2 W costs around $15 and is tiny, which makes it attractive for
small digital photo frames. It works for photos but has real limitations:

- **No hardware video decode** -- video files are decoded in software; expect
  choppy playback on anything above 720p. Stick to photos.
- **No web overlays** -- 512 MB RAM is not enough to run Chromium. The
  provisioning script sets `playwright_supported=false` automatically.
- **Pre-load queue is limited to 2** -- the slideshow queues only 2 photos
  ahead instead of 4, to stay within RAM limits.
- **Slower SD card I/O** -- use a fast A2-rated card (Samsung Pro Endurance,
  SanDisk Extreme) to avoid stuttering during decode.

Good for: small frames, still photos only, cost-sensitive builds.  
Not good for: video, web overlays, 4K screens.

### What not to buy

- **Pi 3 or earlier** -- too slow for smooth pygame rendering at 1080p; not
  tested or supported.
- **Pi Zero (original, not Zero 2 W)** -- single-core ARMv6; far too slow.
- **Pi 400 / Pi 500** -- keyboard computers; awkward to hide behind a screen.
- **Orange Pi, Banana Pi, and similar clones** -- may work but the hardware
  detection script does not recognise them; you would need to write
  `hardware.toml` manually. No guarantees.
- **Pi 5 with a 2 GB model** -- does not exist as of 2026, but if a 2 GB
  variant appears later: avoid it for the same reasons as the Pi 4 2 GB.

---

## Screens

### HDMI screens (easiest)

Any HDMI monitor works. The display renders at whatever resolution you
configure in `display.toml` (`width` and `height`), scaled to fill the screen.

Good options for a permanent frame:

| Type | Notes |
|---|---|
| Consumer TV (32"--55") | Cheap; good brightness; HDMI CEC lets the Pi control power |
| IPS monitor (21"--27") | Better colour accuracy; good for a portrait frame |
| 10"--15" portable HDMI monitor | Compact; USB-C power; ideal for small frames |
| Waveshare HDMI display (7"--10") | Designed for Pi; compact; some include a case |

**What not to buy for HDMI:**

- **Screens with HDMI 1.4 that cap at 30 Hz** -- pygame renders at 60 Hz
  where possible; a 30 Hz cap causes stutter.
- **Monitors with aggressive auto-sleep** -- some monitors power off after
  60 seconds of no input signal. Disable this in the monitor's OSD, or the
  screen will blank between photos. The provisioning script disables the OS-side
  DPMS blanking but cannot override the monitor's own sleep timer.
- **Smart TVs as a primary display** -- smart TVs often switch inputs or show
  overlays unexpectedly. A dumb monitor or TV is more reliable for a permanent
  installation.

### DSI screens (compact builds)

The Pi 4 and Pi 5 have a DSI connector for flat-flex displays. These are
compact and eliminate the HDMI cable, making them ideal for small frames.

| Model | Size | Resolution | Notes |
|---|---|---|---|
| Official Raspberry Pi 7" Touch Display | 7" | 800x480 | Good quality; includes a stand; a bit small for photos |
| Official Raspberry Pi 7" Touch Display 2 | 7" | 1280x800 | Newer; sharper; recommended over the original |
| Waveshare DSI displays | 7"--10" | Various | Budget option; quality varies by model; check reviews |

The Pi Zero 2 W does **not** have a DSI connector. Zero 2 W builds must use HDMI.

**Set `width` and `height` in `display.toml` to match your DSI display's native
resolution.** The OS does not always report the right resolution over DSI.

---

## Cases

A case that hides the board behind the screen makes for a clean installation.

| Case | Best for |
|---|---|
| Argon ONE M.2 (Pi 4) / Argon FIVE (Pi 5) | Living room; aluminium; looks professional |
| Official Pi 5 case with fan | Any Pi 5 build; active cooling; compact |
| SmartiPi Touch 2 | Designed for the 7" official touch display; desktop stand included |
| 3D-printed frame | Custom sizes; search Printables for "Raspberry Pi photo frame" |
| No case (board hidden behind screen) | Wall-mount builds; use mounting tape or a VESA adapter |

---

## Power supplies

Always use a power supply that meets the Pi's requirements. Underpowering
causes random crashes, SD card corruption, and unexplained display glitches.

| Board | Minimum supply | Recommended |
|---|---|---|
| Pi Zero 2 W | 5V 2A (micro-USB) | Official Pi Zero PSU or any quality 5V 2A micro-USB |
| Pi 4 | 5V 3A (USB-C) | Official Pi 4 PSU (white, 15W) |
| Pi 5 | 5V 5A (USB-C, 27W) | Official Pi 5 PSU (white, 27W) -- do not substitute |

The Pi 5 in particular will throttle CPU and GPU if it does not see a 27W supply.
Use the official Pi 5 power supply or a quality USB-C PD supply that negotiates 27W.

**Do not use:**

- USB ports on a TV or monitor to power the Pi -- they typically deliver 0.5--1A,
  which is far below what any Pi needs.
- Cheap unbranded micro-USB chargers -- they often cannot sustain rated current
  and will cause undervoltage warnings and instability.
- A shared USB hub -- each Pi needs its own dedicated supply.

---

## SD cards

The SD card is the Pi's primary storage. Use a quality card; cheap cards fail
within months under continuous write load.

**Recommended: A2-rated cards**

| Brand / Model | Notes |
|---|---|
| Samsung Pro Endurance | Designed for continuous write; best choice for a 24/7 display |
| SanDisk Extreme or Extreme Pro (A2) | Fast and reliable; widely available |
| Kingston Canvas Go! Plus | Budget A2 option; decent endurance |

**Minimum size:** 16 GB (the OS + software fits in under 4 GB; the rest is for
the offline media cache).

**What not to use:**

- **SanDisk Ultra (A1, not A2)** -- slower random write than A2 cards;
  noticeably slower under load.
- **Generic / unbranded SD cards** -- fail early and without warning.
- **SD cards salvaged from cameras** -- camera cards are designed for sequential
  write, not the random I/O pattern of a Linux OS.

---

## Networking

- **Ethernet is strongly preferred** for the Pi 4 and Pi 5. The Pi 4 has a
  genuine Gigabit port (not USB-bottlenecked like the Pi 3). A wired connection
  eliminates the most common source of display dropouts and pairing failures.
- **Wi-Fi works** if running an Ethernet cable is not possible. Use the 5 GHz
  band where available and keep the Pi within a reasonable distance of your
  access point.
- **Pi Zero 2 W is Wi-Fi only** -- it has no Ethernet port. The onboard antenna
  is adequate for a room or two away from the router.

---

## Full shopping list (per display)

### Pi 5 build (recommended)

- Raspberry Pi 5 4 GB or 8 GB
- Official Raspberry Pi 5 27W USB-C power supply
- Samsung Pro Endurance 32 GB micro-SD card
- HDMI cable (micro-HDMI to standard HDMI for Pi 4/5)
- Any 1080p or higher IPS monitor or TV
- Argon FIVE case (optional but tidy)

### Pi Zero 2 W build (budget / small frame)

- Raspberry Pi Zero 2 W
- Official Pi Zero power supply (5V 2A micro-USB)
- Samsung Pro Endurance 16 GB micro-SD card
- mini-HDMI to HDMI cable
- Small HDMI monitor or portable HDMI display (720p is fine)
- 3D-printed or off-the-shelf Pi Zero frame case
