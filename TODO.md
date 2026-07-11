# Malmberg -- status (all self-completable goals DONE)

## Display -- live
- [x] Pro rendering (rotation, aspect-fit + Gaussian blur, smooth crossfade)
- [x] Dark-glass overlay (opaque), labeled Date, top-right time+date, glued clock
- [x] Toast feedback on control taps; "Connecting..." status; video fix
- [x] Manual controls preempt the queue instantly; exact "show this photo"
- [x] Previous = real multi-step rewind; loud "no earlier photos"
- [x] Fast-forward glitch fixed

## Dashboard (/dashboard) -- live
- [x] One page: upload, browse, search, stats, modal, bulk multi-select, playlists
- [x] Full-box responsive grid (6/4/3/2 cols, all divide 24); mobile-friendly
- [x] Per-tile "x" removed (delete via modal + bulk only)
- [x] Multi-display dropdown (greyed with one display)
- [x] One-click "play a year on the frame" + "All"
- [x] "Delete forever" small/de-emphasized + explicit permanent confirmation
- [x] Live now-showing thumbnail; clear DISPLAY vs LIBRARY separation
- [x] Gruvbox (logand.app) styling

## Backend -- live + verified
- [x] EXIF sub-IFD dates; lazy on-the-fly metadata (no re-ingest for new fields)
- [x] Cached thumbnails; soft (trash) + hard (permanent) delete
- [x] Programmed slideshows saved server-side; play/manage
- [x] Multi-display roster + select; play-by-query (year) filter
- [x] 29 sideways photos un-rotated; 80 photos dated, schema v1

## Infra -- live
- [x] Auto-update health-check + rollback (both machines); Wi-Fi watchdog; quiet logs

## Only remaining item (needs YOU -- router setting)
- [ ] DHCP reservation for the Pi (192.168.68.55) so MALMBERG_DISPLAY_URL stays valid
