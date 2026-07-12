"""Self-contained dashboard HTML page served by the server.

The page is single-file (inline CSS/JS, no external CDNs/fonts/scripts)
because the server box is often offline from the wider internet. It is
the single source of truth for the web UI: upload, stats, search/browse,
lightbox details, bulk selection, programmed slideshows, and live
display controls all live here.

Styling follows the Gruvbox Dark palette and monospace-forward,
terminal-flavored aesthetic used across the owner's other projects
(see logand.app docs/design/09-design-system.md), with system
monospace fallbacks since no external fonts may be loaded.

The page is deliberately split into two visually distinct domains so a
non-technical user cannot confuse them: a "Control the photo frame"
area (live display controls) and a "Manage the photo library" area
(stored files: upload, browse, delete, programmed slideshows).
"""

from __future__ import annotations

from typing import Literal

DashboardRole = Literal["server", "display"]

_DASHBOARD_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Malmberg - Dashboard</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #282828;
    --bg-alt: #32302f;
    --panel: #3c3836;
    --text: #ebdbb2;
    --muted: #a89984;
    --accent: #fe8019;
    --ok: #b8bb26;
    --warn: #d79921;
    --err: #fb4934;
    --aqua: #8ec07c;
    --purple: #d3869b;
    --border: #504945;
    --fg: #ebdbb2;
  }
  /* Base form controls so every input/select/textarea matches the theme
     (several were added without local styling and fell back to browser
     defaults -- white boxes, wrong font). */
  input[type="text"], input[type="search"], input[type="number"],
  input:not([type]), select, textarea {
    font-family: inherit;
    font-size: 0.9rem;
    color: var(--text);
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.5rem 0.6rem;
    box-sizing: border-box;
    min-height: 40px;
  }
  input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--accent);
  }
  input::placeholder { color: var(--muted); }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo,
      Consolas, "Liberation Mono", monospace;
    font-size: 16px;
    background: var(--bg);
    color: var(--text);
    padding: 1rem;
  }
  main { max-width: 900px; margin: 0 auto; }
  h1 {
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    margin: 0.25rem 0 1rem;
    color: var(--text);
  }
  .domain {
    border: 2px solid var(--border);
    border-radius: 8px;
    padding: 0.9rem 0.9rem 0.2rem;
    margin-bottom: 1.4rem;
  }
  .domain-display { border-color: var(--accent); }
  .domain-library { border-color: var(--aqua); }
  .domain-head {
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
  }
  .domain-display .domain-head { color: var(--accent); }
  .domain-library .domain-head { color: var(--aqua); }
  .domain-sub {
    font-size: 0.78rem;
    color: var(--muted);
    margin-bottom: 0.9rem;
  }
  section {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem;
    margin-bottom: 1.1rem;
  }
  section h2 {
    font-size: 0.85rem;
    font-weight: 700;
    margin: 0 0 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  a { color: var(--accent); }
  /* Stats */
  #stats-count {
    font-size: 1.9rem;
    font-weight: 700;
    color: var(--accent);
    line-height: 1;
  }
  #stats-count .label {
    font-size: 0.85rem;
    font-weight: 400;
    color: var(--muted);
    margin-left: 0.5rem;
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 0.6rem;
    margin-top: 0.85rem;
  }
  .stat-tile {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.6rem 0.7rem;
  }
  .stat-tile .n {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text);
  }
  .stat-tile .k {
    font-size: 0.72rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 0.1rem;
  }
  #by-year {
    margin-top: 0.85rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .year-chip {
    font-family: inherit;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    min-height: 44px;
    font-size: 0.9rem;
    color: var(--muted);
    cursor: pointer;
  }
  .year-chip:hover, .year-chip:focus-visible {
    border-color: var(--accent);
    color: var(--text);
    outline: none;
  }
  .year-chip b { color: var(--aqua); font-weight: 700; }
  /* By-month breakdown (year groups, month chips) */
  #by-month { margin-top: 0.85rem; }
  .month-group {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.35rem 0;
    border-top: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .month-group:first-child { border-top: none; }
  .month-group .mg-year {
    font-weight: 700;
    color: var(--accent);
    min-width: 3.2rem;
    font-size: 0.85rem;
  }
  .month-group .mg-months {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }
  .month-chip {
    font-family: inherit;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    min-height: 40px;
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
  }
  .month-chip:hover, .month-chip:focus-visible {
    border-color: var(--accent);
    color: var(--text);
    outline: none;
  }
  .month-chip b { color: var(--aqua); font-weight: 700; }
  /* By-place breakdown, same chip look as by-year */
  #by-place {
    margin-top: 0.85rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .place-chip {
    font-family: inherit;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    min-height: 44px;
    font-size: 0.9rem;
    color: var(--muted);
    cursor: pointer;
  }
  .place-chip:hover, .place-chip:focus-visible {
    border-color: var(--accent);
    color: var(--text);
    outline: none;
  }
  .place-chip b { color: var(--aqua); font-weight: 700; }
  #place-search-row #place-input { flex: 1 1 auto; }
  #person-search-row #person-input { flex: 1 1 auto; }
  /* By-person breakdown, same chip look as by-place */
  #by-person {
    margin-top: 0.6rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  /* People section: collapsible header + compact cards */
  .people-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .people-head h2 { margin: 0; }
  .collapse-btn {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--muted);
    cursor: pointer;
  }
  #people-body.collapsed { display: none; }
  #people-show-small-row {
    display: flex;
    gap: 0.45rem;
    align-items: flex-start;
    margin-top: 0.7rem;
    font-size: 0.78rem;
    color: var(--muted);
  }
  .people-grid {
    margin-top: 0.85rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem;
    /* Cap the height so a big library of faces scrolls inside the section
       instead of pushing the photo library far down the page. */
    max-height: 30rem;
    overflow-y: auto;
    padding: 0.2rem;
    align-content: flex-start;
  }
  .people-grid.maximized { max-height: none; overflow-y: visible; }
  .person-card {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.6rem;
    width: 148px;
    text-align: center;
  }
  /* The photo IS the primary control: tapping it opens the review modal.
     Kept as a real <button> for keyboard access and a visible focus ring. */
  .person-card .person-photo-btn {
    display: block;
    width: 100%;
    padding: 0;
    margin: 0;
    border: 2px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
    cursor: pointer;
    min-height: 132px;
  }
  .person-card .person-photo-btn:hover,
  .person-card .person-photo-btn:focus-visible {
    border-color: var(--accent);
    outline: none;
  }
  .person-card .person-photo-btn img {
    width: 100%;
    height: 132px;
    object-fit: cover;
    border-radius: 6px;
    background: var(--bg);
    display: block;
  }
  .person-card .person-name {
    font-size: 0.9rem;
    font-weight: 700;
    margin-top: 0.5rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .person-card .person-name.unnamed { color: var(--muted); font-weight: 400; }
  .person-card .person-count {
    font-size: 0.75rem;
    color: var(--muted);
    margin: 0.15rem 0 0.5rem;
  }
  /* Big, obvious naming control right on the card -- no tiny action row. */
  .person-card .person-name-btn {
    width: 100%;
    min-height: 44px;
    font-size: 0.85rem;
    font-weight: 700;
    padding: 0.4rem 0.5rem;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: 6px;
    color: var(--accent);
    cursor: pointer;
  }
  .person-card .person-name-btn:hover,
  .person-card .person-name-btn:focus-visible {
    background: var(--accent);
    color: #282828;
    outline: none;
  }
  .person-card .person-name-edit { margin-top: 0.5rem; display: none; }
  .person-card .person-name-edit.show { display: block; }
  .person-card .person-name-edit input {
    width: 100%;
    font-size: 0.9rem;
    min-height: 44px;
    padding: 0.4rem;
    box-sizing: border-box;
    margin-bottom: 0.35rem;
  }
  .person-card .person-name-edit button {
    width: 100%;
    min-height: 44px;
    font-size: 0.85rem;
    font-weight: 700;
  }
  /* Review modal (per-person face review + green boxes + overrides) */
  #review-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    display: none;
    z-index: 60;
    overflow-y: auto;
    padding: 1rem;
  }
  #review-backdrop.show { display: block; }
  #review-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    max-width: 760px;
    margin: 1rem auto;
    padding: 1rem;
    position: relative;
  }
  #review-close {
    position: absolute;
    top: 0.4rem;
    right: 0.6rem;
    font-size: 1.6rem;
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
  }
  #review-title { font-size: 1.2rem; font-weight: 700; margin-bottom: 0.7rem; }
  .review-tools {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.7rem;
    flex-wrap: wrap;
  }
  .review-tools input {
    flex: 1 1 auto;
    min-width: 10rem;
    font-size: 1rem;
    min-height: 48px;
  }
  .review-tools button {
    min-height: 48px;
    padding: 0.4rem 1.1rem;
    font-size: 0.9rem;
    font-weight: 700;
  }
  #review-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1rem;
    margin-top: 0.9rem;
  }
  .review-face { text-align: center; }
  .review-face-imgwrap {
    position: relative;
    display: inline-block;
    max-width: 100%;
    line-height: 0;
    cursor: zoom-in;
  }
  .review-face-imgwrap img {
    max-width: 100%;
    border-radius: 6px;
    display: block;
  }
  /* Corner brackets, not a solid box: the markers sit OUTSIDE the face
     (the drawn rect is padded beyond the bbox in JS) so the face itself
     stays fully visible, with a dark outline for contrast on light
     backgrounds too. */
  .review-face-box {
    position: absolute;
    pointer-events: none;
  }
  .review-face-box .corner {
    position: absolute;
    width: 22%;
    height: 22%;
    max-width: 26px;
    max-height: 26px;
    border-color: #b8bb26;
    filter: drop-shadow(0 0 1px #1d2021) drop-shadow(0 0 1px #1d2021);
  }
  .review-face-box .corner.tl {
    top: 0; left: 0;
    border-top: 4px solid #b8bb26;
    border-left: 4px solid #b8bb26;
  }
  .review-face-box .corner.tr {
    top: 0; right: 0;
    border-top: 4px solid #b8bb26;
    border-right: 4px solid #b8bb26;
  }
  .review-face-box .corner.bl {
    bottom: 0; left: 0;
    border-bottom: 4px solid #b8bb26;
    border-left: 4px solid #b8bb26;
  }
  .review-face-box .corner.br {
    bottom: 0; right: 0;
    border-bottom: 4px solid #b8bb26;
    border-right: 4px solid #b8bb26;
  }
  .review-face-zoom-hint {
    margin-top: 0.3rem;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .review-face button {
    margin-top: 0.5rem;
    width: 100%;
    min-height: 44px;
    font-size: 0.8rem;
    font-weight: 700;
    padding: 0.4rem 0.5rem;
    background: var(--bg-alt);
    border: 1px solid var(--err);
    border-radius: 6px;
    color: var(--err);
    cursor: pointer;
  }
  .review-face button:hover, .review-face button:focus-visible {
    background: var(--err);
    color: #282828;
    outline: none;
  }
  /* Zoomed face view: a big crop-and-enlarge of one face, opened by
     tapping a review photo. Dependency-free (plain canvas). */
  #face-zoom-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.85);
    display: none;
    z-index: 70;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  #face-zoom-backdrop.show { display: flex; }
  #face-zoom-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem;
    max-width: 92vw;
    max-height: 92vh;
    text-align: center;
    position: relative;
  }
  #face-zoom-close {
    position: absolute;
    top: 0.4rem;
    right: 0.6rem;
    font-size: 1.8rem;
    min-width: 44px;
    min-height: 44px;
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
  }
  #face-zoom-canvas {
    max-width: 80vw;
    max-height: 75vh;
    border-radius: 8px;
    background: var(--bg-alt);
  }
  #face-zoom-hint {
    margin-top: 0.6rem;
    font-size: 0.85rem;
    color: var(--muted);
  }
  #frame-place-row, #frame-person-row { margin-top: 0.4rem; }
  /* Upload section */
  #dropzone {
    border: 2px dashed var(--border);
    border-radius: 6px;
    padding: 2rem 1rem;
    text-align: center;
    color: var(--muted);
    transition: border-color 0.15s, background 0.15s;
  }
  #dropzone.drag {
    border-color: var(--accent);
    background: var(--bg-alt);
  }
  #dropzone .hint {
    font-size: 0.85rem;
    margin-top: 0.5rem;
  }
  button {
    font-family: inherit;
  }
  #picker-btn {
    display: inline-block;
    margin-top: 1rem;
    padding: 0.8rem 1.5rem;
    font-size: 0.95rem;
    font-weight: 700;
    color: #282828;
    background: var(--accent);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    min-height: 44px;
  }
  #picker-btn:active { opacity: 0.85; }
  input[type="file"] { display: none; }
  #upload-summary {
    margin-top: 1rem;
    display: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.85rem 1rem;
    font-size: 0.9rem;
    background: var(--bg-alt);
  }
  #upload-summary.show { display: block; }
  #upload-list {
    margin-top: 1rem;
    display: flex;
    /* Newest-finished rows appear at the top so the last uploads stay in view. */
    flex-direction: column-reverse;
    justify-content: flex-end;
    gap: 0.6rem;
    /* Cap the height so 100+ files scroll inside the box instead of running
       off the end of the page; the list stays scrollable. */
    max-height: 22rem;
    overflow-y: auto;
    padding-right: 0.3rem;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.7rem 0.9rem;
  }
  .row .thumb {
    width: 40px;
    height: 40px;
    flex: 0 0 40px;
    border-radius: 4px;
    object-fit: cover;
    background: var(--bg);
    display: none;
  }
  .row.ok .thumb { display: block; }
  .row .body { flex: 1 1 auto; min-width: 0; }
  .row .name {
    font-size: 0.88rem;
    font-weight: 700;
    word-break: break-all;
  }
  .row .status {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 0.15rem;
  }
  .bar-track {
    margin-top: 0.5rem;
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    width: 0%;
    background: var(--accent);
    transition: width 0.1s linear;
  }
  .row.ok .bar-fill { background: var(--ok); }
  .row.ok .status { color: var(--ok); }
  .row.dup .bar-fill { background: var(--warn); }
  .row.dup .status { color: var(--warn); }
  .row.err .bar-fill { background: var(--err); }
  .row.err .status { color: var(--err); }
  /* Now playing / controls */
  #now-playing-row {
    display: flex;
    gap: 0.85rem;
    align-items: center;
  }
  #now-thumb-wrap {
    width: 72px;
    height: 72px;
    flex: 0 0 auto;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  #now-thumb-wrap .now-thumb-btn {
    width: 100%;
    height: 100%;
    padding: 0;
    margin: 0;
    border: none;
    background: none;
    cursor: pointer;
    display: block;
  }
  #now-thumb-wrap .now-thumb-btn:hover,
  #now-thumb-wrap .now-thumb-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  #now-thumb-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  #now-thumb-wrap .placeholder {
    color: var(--muted);
    font-size: 1.4rem;
  }
  #now-playing {
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
    word-break: break-word;
  }
  #now-meta {
    color: var(--muted);
    font-size: 0.82rem;
  }
  .controls {
    display: flex;
    gap: 0.6rem;
    margin-top: 1rem;
    flex-wrap: wrap;
  }
  .controls button {
    flex: 1 1 auto;
    min-width: 90px;
    min-height: 48px;
    font-size: 0.92rem;
    font-weight: 700;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
    transition: opacity 0.1s, transform 0.05s;
  }
  .controls button:active { opacity: 0.8; transform: scale(0.98); }
  .controls button:disabled {
    color: var(--muted);
    cursor: not-allowed;
    opacity: 0.5;
  }
  .controls button.busy {
    opacity: 0.6;
    cursor: wait;
  }
  #control-hint {
    margin-top: 0.6rem;
    font-size: 0.8rem;
    color: var(--muted);
    display: none;
  }
  #control-hint.show { display: block; }
  #play-all-row { margin-top: 0.7rem; }
  #play-all-row button {
    width: 100%;
    min-height: 44px;
    font-size: 0.85rem;
    font-weight: 700;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-alt);
    color: var(--aqua);
    cursor: pointer;
  }
  /* Display selector */
  #display-select-row {
    margin-top: 0.9rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
  }
  #display-select-row label {
    font-size: 0.8rem;
    color: var(--muted);
  }
  #display-select {
    flex: 1 1 160px;
    min-height: 44px;
    padding: 0 0.6rem;
    font-family: inherit;
    font-size: 0.88rem;
    background: var(--bg-alt);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  #display-select:disabled {
    color: var(--muted);
    opacity: 0.6;
    cursor: not-allowed;
  }
  /* Frame filter group (year/place/person -> play on frame) */
  #frame-filter-group {
    margin-top: 0.9rem;
  }
  #frame-filter-group .yf-label {
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 0.4rem;
  }
  #year-filter-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  #year-filter-buttons button {
    min-height: 44px;
    min-width: 48px;
    padding: 0 0.8rem;
    font-size: 0.9rem;
    font-weight: 700;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
  }
  #year-filter-buttons button.yf-all {
    color: var(--aqua);
    border-color: var(--aqua);
  }
  #year-filter-buttons button.yf-active {
    background: var(--accent);
    color: #282828;
    border-color: var(--accent);
  }
  /* Independent AND-ed filter boxes (Time / Place / Person) */
  .filter-box-row {
    margin-top: 0.9rem;
  }
  .filter-box-row label {
    display: block;
    font-weight: 700;
    margin-bottom: 0.3rem;
  }
  .filter-box-row input {
    width: 100%;
    min-height: 48px;
    font-size: 1rem;
    padding: 0.4rem 0.7rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    box-sizing: border-box;
  }
  /* Compact, browsable preview strip under "Show on the frame" */
  #frame-preview-wrap { margin-top: 0.8rem; }
  #frame-preview-label {
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 0.4rem;
  }
  .preview-grid {
    grid-template-columns: repeat(6, 1fr);
    max-height: 11rem;
    overflow: hidden;
  }
  @media (max-width: 520px) {
    .preview-grid { grid-template-columns: repeat(4, 1fr); }
  }
  #frame-preview-empty {
    font-size: 0.85rem;
    color: var(--muted);
    display: none;
  }
  #frame-play-row { margin-top: 0.6rem; }
  #frame-search-play-btn {
    min-height: 44px;
    padding: 0.4rem 1rem;
  }
  #frame-quick-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 0.4rem;
  }
  #frame-quick-row #year-filter-buttons { margin: 0; }
  #loop-toggle-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 0.7rem;
    font-size: 0.85rem;
    color: var(--muted);
  }
  #loop-toggle-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
  }
  #loop-toggle-row input { width: 20px; height: 20px; }
  /* Page header + help button */
  #page-head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  #page-head-row h1 { margin: 0.25rem 0; }
  /* Inline, click-to-open help tips: a small "?" next to a control or
     description that reveals a plain-language explanation in context.
     Replaces the old auto-popup walkthrough. */
  .help { position: relative; display: inline-block; vertical-align: middle; }
  .cloud-card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.9rem 1rem;
    margin-bottom: 0.9rem;
    background: var(--bg-alt);
  }
  .cloud-card-head {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  .cloud-card-head h3 { margin: 0; font-size: 1.05rem; }
  .cloud-badge {
    font-size: 0.75rem;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-weight: 700;
  }
  .cloud-badge.ok { background: #2f6b34; color: #eaffea; }
  .cloud-badge.off { background: #6b2f2f; color: #ffeaea; }
  .cloud-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 1.2rem;
    margin: 0.7rem 0;
  }
  .cloud-stat-val { font-size: 1.4rem; font-weight: 700; }
  .cloud-stat-lbl { font-size: 0.75rem; color: var(--muted); }
  .help-tip {
    width: 28px;
    height: 28px;
    min-height: 28px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--accent);
    background: var(--bg-alt);
    color: var(--accent);
    font-weight: 700;
    font-size: 0.9rem;
    line-height: 1;
    cursor: pointer;
  }
  .help-tip:hover, .help-tip:focus-visible {
    background: var(--accent); color: #282828; outline: none;
  }
  .help-bubble {
    display: none;
    position: absolute;
    z-index: 90;
    left: 0;
    top: calc(100% + 6px);
    width: max-content;
    max-width: min(300px, 80vw);
    background: var(--panel);
    border: 1px solid var(--accent);
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
    font-size: 0.92rem;
    font-weight: 400;
    line-height: 1.5;
    color: var(--text);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.5);
    white-space: normal;
    text-align: left;
  }
  .help.open .help-bubble { display: block; }
  /* Toasts */
  #toast-stack {
    position: fixed;
    left: 50%;
    bottom: 1rem;
    transform: translateX(-50%);
    z-index: 500;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    align-items: center;
    width: calc(100% - 2rem);
    max-width: 500px;
    pointer-events: none;
  }
  .toast {
    background: var(--panel);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    color: var(--text);
    border-radius: 6px;
    padding: 0.6rem 0.9rem;
    font-size: 0.85rem;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.18s, transform 0.18s;
  }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast.ok { border-left-color: var(--ok); }
  .toast.err { border-left-color: var(--err); }
  /* Search / browse */
  .search-row {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.85rem;
  }
  #search-input {
    flex: 1 1 200px;
    min-height: 44px;
    padding: 0 0.8rem;
    font-family: inherit;
    font-size: 0.95rem;
    background: var(--bg-alt);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  #search-input::placeholder { color: var(--muted); }
  #refresh-btn, #select-toggle-btn {
    padding: 0 1rem;
    min-height: 44px;
    font-size: 0.85rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
  }
  #select-toggle-btn {
    color: #282828;
    background: var(--accent);
    border-color: var(--accent);
  }
  #select-toggle-btn.active {
    color: #282828;
    background: var(--aqua);
    border-color: var(--aqua);
  }
  #results-summary {
    font-size: 0.82rem;
    color: var(--muted);
    margin-bottom: 0.6rem;
  }
  #restart-row {
    margin-top: 1.1rem;
    padding-top: 0.9rem;
    border-top: 1px dashed var(--border);
  }
  .danger-btn {
    margin-top: 0.5rem;
    margin-right: 0.5rem;
    padding: 0.5rem 0.8rem;
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--err);
    background: transparent;
    border: 1px solid var(--err);
    border-radius: 6px;
    cursor: pointer;
    opacity: 0.75;
  }
  .danger-btn:hover {
    opacity: 1;
  }
  #trash-panel {
    display: none;
    margin-top: 0.6rem;
  }
  #trash-panel.show {
    display: block;
  }
  #trash-empty {
    color: var(--muted);
    font-size: 0.85rem;
  }
  .trash-tile {
    position: relative;
  }
  .trash-tile img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    border-radius: 4px;
    display: block;
    opacity: 0.75;
  }
  .trash-tile .trash-actions {
    display: flex;
    gap: 0.3rem;
    margin-top: 0.25rem;
  }
  .trash-tile button {
    flex: 1;
    font-size: 0.72rem;
    padding: 0.25rem 0.3rem;
  }
  /* Grid */
  .grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 0.5rem;
  }
  @media (max-width: 720px) {
    .grid { grid-template-columns: repeat(4, 1fr); }
  }
  @media (max-width: 520px) {
    .grid { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 360px) {
    .grid { grid-template-columns: repeat(2, 1fr); }
  }
  .tile {
    position: relative;
    cursor: pointer;
  }
  .tile img {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    display: block;
  }
  .tile .select-mark {
    position: absolute;
    top: 4px;
    left: 4px;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 2px solid rgba(235, 219, 178, 0.7);
    background: rgba(40, 40, 40, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
    font-size: 0.95rem;
    font-weight: 700;
  }
  .tile.selected .select-mark {
    background: var(--aqua);
    border-color: var(--aqua);
    color: #282828;
  }
  .tile.selected img {
    outline: 3px solid var(--aqua);
    outline-offset: -3px;
  }
  .tile .play-badge {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: rgba(20, 20, 20, 0.55);
    border: 2px solid rgba(235, 219, 178, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .tile .play-badge::before {
    content: "";
    margin-left: 3px;
    border-style: solid;
    border-width: 8px 0 8px 13px;
    border-color: transparent transparent transparent var(--text);
  }
  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    margin-top: 1rem;
    flex-wrap: wrap;
  }
  .pagination button {
    min-width: 90px;
    min-height: 44px;
    padding: 0 1rem;
    font-size: 0.85rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
  }
  .pagination button:disabled {
    color: var(--muted);
    cursor: not-allowed;
    opacity: 0.5;
  }
  .pagination .page-info {
    font-size: 0.82rem;
    color: var(--muted);
  }
  /* Bulk action bar */
  #bulk-bar {
    display: none;
    flex-direction: column;
    gap: 0.7rem;
    margin-bottom: 0.85rem;
    padding: 0.85rem 0.9rem;
    border-radius: 8px;
    border: 2px solid var(--aqua);
    background: var(--bg-alt);
  }
  #bulk-bar.show { display: flex; }
  #bulk-count {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--aqua);
  }
  #bulk-bar-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.55rem;
  }
  #bulk-bar button {
    min-height: 44px;
    padding: 0 1rem;
    font-size: 0.82rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
  }
  #bulk-add-playlist {
    border-color: var(--aqua);
    color: var(--aqua);
  }
  #bulk-danger-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    /* Force the destructive actions onto their own row, flush to the left. */
    flex-basis: 100%;
    margin-left: 0;
    padding-left: 0;
  }
  #bulk-soft-delete {
    color: var(--err);
    border-color: var(--err);
    background: transparent;
    opacity: 0.85;
  }
  #bulk-hard-delete {
    color: var(--muted);
    border-color: transparent;
    background: transparent;
    font-weight: 400;
    font-size: 0.72rem;
    min-height: 32px;
    padding: 0 0.5rem;
    text-decoration: underline;
    opacity: 0.6;
  }
  #bulk-hard-delete:hover { opacity: 1; color: var(--err); }
  #bulk-hard-delete:hover { color: var(--err); opacity: 1; }
  #bulk-soft-delete { color: var(--warn); border-color: var(--warn); }
  #bulk-add-playlist { color: var(--aqua); border-color: var(--aqua); }
  /* Playlists */
  .playlist-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.6rem 0.8rem;
    margin-bottom: 0.5rem;
  }
  .playlist-row .pl-name {
    font-weight: 700;
    font-size: 0.9rem;
  }
  .playlist-row .pl-count {
    color: var(--muted);
    font-size: 0.78rem;
  }
  .playlist-row .pl-actions {
    margin-left: auto;
    display: flex;
    gap: 0.4rem;
  }
  .playlist-row button {
    min-height: 38px;
    padding: 0 0.7rem;
    font-size: 0.78rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
  }
  .playlist-row .pl-play { color: var(--accent); border-color: var(--accent); }
  .playlist-row .pl-delete { color: var(--err); border-color: var(--err); }
  #new-playlist-row {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.6rem;
  }
  #new-playlist-name {
    flex: 1 1 auto;
    min-height: 44px;
    padding: 0 0.8rem;
    font-family: inherit;
    font-size: 0.9rem;
    background: var(--bg-alt);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  #new-playlist-btn {
    min-height: 44px;
    padding: 0 1rem;
    font-size: 0.85rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--aqua);
    background: var(--bg-alt);
    color: var(--aqua);
    cursor: pointer;
  }
  #playlists-empty {
    color: var(--muted);
    font-size: 0.82rem;
  }
  /* Modal / lightbox */
  #modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(20, 18, 16, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    z-index: 200;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease;
  }
  #modal-backdrop.show {
    opacity: 1;
    pointer-events: auto;
  }
  #modal-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    max-width: 620px;
    width: 100%;
    max-height: 92vh;
    overflow-y: auto;
    transform: scale(0.94);
    transition: transform 0.18s ease;
    position: relative;
  }
  #modal-backdrop.show #modal-card {
    transform: scale(1);
  }
  #modal-close {
    position: absolute;
    top: 0.6rem;
    right: 0.6rem;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: var(--bg-alt);
    color: var(--text);
    font-size: 1.2rem;
    font-weight: 700;
    cursor: pointer;
    z-index: 2;
  }
  #modal-img-wrap {
    background: #1d1a17;
    display: flex;
    align-items: center;
    justify-content: center;
    max-height: 45vh;
    overflow: hidden;
    border-radius: 10px 10px 0 0;
  }
  #modal-img-wrap img {
    max-width: 100%;
    max-height: 45vh;
    display: block;
  }
  #modal-video {
    max-width: 100%;
    max-height: 45vh;
    display: none;
  }
  #modal-video.show {
    display: block;
  }
  #modal-body {
    padding: 1rem 1.1rem 1.2rem;
  }
  #modal-title {
    font-size: 1.05rem;
    font-weight: 700;
    margin-bottom: 0.6rem;
    word-break: break-all;
  }
  .detail-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.35rem 0.8rem;
    font-size: 0.82rem;
    margin-bottom: 0.9rem;
  }
  .detail-grid dt {
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    font-size: 0.72rem;
    padding-top: 0.1rem;
  }
  .detail-grid dd {
    margin: 0;
    word-break: break-all;
  }
  .modal-actions {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 0.9rem;
  }
  .modal-actions button {
    min-height: 46px;
    padding: 0 1rem;
    font-size: 0.88rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .orient-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
  }
  .orient-grid button {
    min-height: 48px;
    padding: 0 0.6rem;
    font-size: 0.85rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
    text-align: center;
  }
  .orient-grid button:disabled { opacity: 0.5; cursor: default; }
  #act-show { color: var(--accent); border-color: var(--accent); }
  #act-add-playlist { color: var(--aqua); border-color: var(--aqua); }
  #act-soft-delete { color: var(--warn); border-color: var(--warn); }
  #act-hard-delete {
    color: var(--muted);
    border: none;
    background: transparent;
    font-weight: 400;
    font-size: 0.78rem;
    min-height: 32px;
    text-decoration: underline;
    text-align: center;
    opacity: 0.6;
  }
  #act-hard-delete:hover { color: var(--err); opacity: 1; }
  /* Playlist picker (inline, inside modal or bulk bar) */
  #playlist-picker {
    display: none;
    margin-top: 0.5rem;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.7rem;
  }
  #playlist-picker.show { display: block; }
  #playlist-picker .pp-existing {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-bottom: 0.6rem;
    max-height: 140px;
    overflow-y: auto;
  }
  #playlist-picker button.pp-item {
    text-align: left;
    min-height: 40px;
    padding: 0 0.7rem;
    font-size: 0.82rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
  }
  #playlist-picker .pp-new-row {
    display: flex;
    gap: 0.4rem;
  }
  #playlist-picker input[type="text"] {
    flex: 1 1 auto;
    min-height: 40px;
    padding: 0 0.6rem;
    font-family: inherit;
    font-size: 0.82rem;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  #playlist-picker .pp-create {
    min-height: 40px;
    padding: 0 0.8rem;
    font-size: 0.8rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--aqua);
    background: var(--panel);
    color: var(--aqua);
    cursor: pointer;
  }
  footer {
    text-align: center;
    color: var(--muted);
    font-size: 0.75rem;
    margin-top: 1rem;
  }
  @media (max-width: 420px) {
    body { padding: 0.6rem; font-size: 15px; }
    .domain { padding: 0.7rem 0.7rem 0.1rem; }
    section { padding: 0.75rem; }
    #modal-body { padding: 0.8rem 0.85rem 1rem; }
    .modal-actions button { min-height: 44px; }
  }
</style>
</head>
<body>
<main>
  <div id="page-head-row">
    <h1>Malmberg Dashboard</h1>
    <span class="help">
      <button class="help-tip" type="button"
              aria-label="What is this page?">?</button>
      <span class="help-bubble">Top (orange) controls your TV frame. Bottom
      (green) is your photo library.</span>
    </span>
  </div>

  <div class="domain domain-display">
    <div class="domain-head">Control the photo frame</div>
    <div class="domain-sub">
      These buttons control what is showing right now on the TV / photo
      frame. Changes here happen immediately on the display.
    </div>

    <section>
      <h2>Now showing</h2>
      <div id="now-playing-row">
        <div id="now-thumb-wrap">
          <span class="placeholder">--</span>
        </div>
        <div>
          <div id="now-playing">Loading...</div>
          <div id="now-meta"></div>
        </div>
      </div>
      <div class="controls">
        <button id="btn-prev" type="button">Previous</button>
        <button id="btn-pause" type="button">Pause</button>
        <button id="btn-next" type="button">Next</button>
      </div>
      <div id="play-all-row">
        <button id="btn-play-all" type="button">Play whole library</button>
      </div>
      <div id="display-select-row">
        <label for="display-select">Which frame</label>
        <select id="display-select" disabled></select>
      </div>
      <div id="frame-filter-group">
        <div class="yf-label">
          Show on the frame
          <span class="help">
            <button class="help-tip" type="button"
                    aria-label="How to show photos on the frame">?</button>
            <span class="help-bubble">Tap a year, or type a year, month, place,
            or name, then press Show on frame.</span>
          </span>
        </div>
        <div id="frame-quick-row">
          <div id="year-filter-buttons"></div>
        </div>
        <div class="filter-box-row">
          <label for="frame-time-input">Time</label>
          <input id="frame-time-input" type="text" autocomplete="off"
            aria-label="Show photos from a time, e.g. 2006 or 2006-07"
            placeholder="e.g. 2006 or 2006-07">
        </div>
        <div class="filter-box-row">
          <label for="frame-place-input">Place</label>
          <div class="search-row" id="frame-place-search-row">
            <input id="frame-place-input" type="text" autocomplete="off"
              list="frame-place-suggestions"
              aria-label="Show photos from a place"
              placeholder="e.g. Tampa">
            <datalist id="frame-place-suggestions"></datalist>
          </div>
        </div>
        <div class="filter-box-row">
          <label for="frame-person-input">Person</label>
          <div class="search-row" id="frame-person-search-row">
            <input id="frame-person-input" type="text" autocomplete="off"
              list="frame-person-suggestions"
              aria-label="Show photos of a person"
              placeholder="By a person's name">
            <datalist id="frame-person-suggestions"></datalist>
          </div>
        </div>
        <div id="frame-play-row">
          <button id="frame-search-play-btn" type="button">Show on frame</button>
        </div>
        <div id="frame-preview-wrap">
          <div id="frame-preview-label">Preview: what this will show</div>
          <div class="grid preview-grid" id="frame-preview-grid"></div>
          <div id="frame-preview-empty">Nothing matches yet.</div>
          <div class="pagination">
            <button id="frame-preview-prev" type="button">Previous</button>
            <span class="page-info" id="frame-preview-info"></span>
            <button id="frame-preview-next" type="button">Next</button>
          </div>
        </div>
      </div>
      <div id="loop-toggle-row">
        <label id="loop-toggle-label">
          <input type="checkbox" id="loop-toggle">
          <span>Keep it looping until I stop it</span>
        </label>
        <span class="help">
          <button class="help-tip" type="button"
                  aria-label="What does looping do?">?</button>
          <span class="help-bubble">On: repeats until you press Play whole
          library. Off: plays once, then all photos return.</span>
        </span>
      </div>
      <div id="control-hint">Controls disabled: set MALMBERG_DISPLAY_URL
      on the server to enable.</div>
      <div id="restart-row">
        <div class="yf-label">Frame frozen or acting up? Restart it.</div>
        <button id="btn-restart-display" type="button" class="danger-btn">
          Restart display
        </button>
      </div>
    </section>
  </div>

  <div class="domain domain-library">
    <div class="domain-head">Manage the photo library</div>
    <div class="domain-sub">
      This is where photos and videos are stored on the server. Nothing
      here changes what is on the TV until you press a "play" or
      "display it now" button.
    </div>

    <section>
      <h2>Library</h2>
      <div id="stats-count">-- <span class="label">photos and videos</span></div>
      <div class="stats-grid" id="stats-grid"></div>
      <div id="by-year"></div>
      <div id="by-month"></div>
      <div id="by-place"></div>
      <div id="by-person"></div>
    </section>

    <section>
      <h2>
        Search by time, place, or person
        <span class="help">
          <button class="help-tip" type="button"
                  aria-label="How search works">?</button>
          <span class="help-bubble">Fill any boxes; the grid shows photos
          matching all of them. Empty boxes are ignored.</span>
        </span>
      </h2>
      <div class="filter-box-row">
        <label for="time-input">Time</label>
        <input id="time-input" type="text" autocomplete="off"
          aria-label="Filter by time, e.g. 2006 or 2006-07"
          placeholder="e.g. 2006 or 2006-07">
      </div>
      <div class="filter-box-row">
        <label for="place-input">Place</label>
        <div class="search-row" id="place-search-row">
          <input id="place-input" type="text" autocomplete="off"
            list="place-suggestions"
            aria-label="Filter by place"
            placeholder="e.g. Tampa">
          <datalist id="place-suggestions"></datalist>
        </div>
      </div>
      <div class="filter-box-row">
        <label for="person-input">Person</label>
        <div class="search-row" id="person-search-row">
          <input id="person-input" type="text" autocomplete="off"
            list="person-suggestions"
            aria-label="Filter by a person's name"
            placeholder="By a person's name">
          <datalist id="person-suggestions"></datalist>
        </div>
      </div>
    </section>

    <section id="people-section">
      <div class="people-head">
        <h2>People</h2>
        <button id="people-maximize" type="button" class="collapse-btn">
          Maximize
        </button>
        <button id="people-toggle" type="button" class="collapse-btn">Hide</button>
      </div>
      <div id="people-body">
        <div class="domain-sub">
          Faces detected in your photos are grouped automatically. Name a
          person to search and play their photos; open Review to check which
          face is meant, fix a wrong grouping, or merge duplicates. New
          uploads are scanned in the background, so a new face can take a
          little while to appear.
        </div>
        <div id="people-grid" class="people-grid"></div>
        <div id="people-empty" class="domain-sub">No people to name yet.</div>
        <label id="people-show-small-row">
          <input type="checkbox" id="people-show-small">
          <span>Also show small, uncertain groups (fewer than 3 photos).</span>
        </label>
      </div>
    </section>

    <section id="cloud-section">
      <div class="people-head">
        <h2>Cloud photos</h2>
        <span class="help">
          <button class="help-tip" type="button"
                  aria-label="What is cloud photo sync?">?</button>
          <span class="help-bubble">Malmberg can copy photos down from your
          cloud accounts (Google Photos, iCloud) into this server, then --
          only after checking the copy here matches byte-for-byte -- offer to
          remove them from the cloud to free up space. Nothing is ever deleted
          from the cloud without your explicit confirmation.</span>
        </span>
      </div>
      <div class="domain-sub">
        Connect an account with the setup scripts, then sync on a timer or on
        demand. Cleanup only ever touches photos verified as safely stored
        here.
      </div>
      <div id="cloud-providers"></div>
      <div id="cloud-empty" class="domain-sub">
        No cloud providers are enabled. See the operations guide to connect
        Google Photos or iCloud.
      </div>
    </section>

    <section>
      <h2>Upload</h2>
      <div id="dropzone">
        <div>Drag and drop photos or videos here</div>
        <div class="hint">or</div>
        <button id="picker-btn" type="button">Choose files</button>
        <input id="file-input" type="file" multiple accept="image/*,video/*">
      </div>
      <div id="upload-summary"></div>
      <div id="upload-list"></div>
    </section>

    <section>
      <h2>Browse photos</h2>
      <div class="search-row">
        <input id="search-input" type="text"
          placeholder="Search by filename, year, or place (e.g. 2006 or Tampa)">
        <button id="refresh-btn" type="button">Refresh</button>
        <button id="select-toggle-btn" type="button">Bulk Select</button>
      </div>
      <div id="results-summary"></div>
      <div id="bulk-bar">
        <span id="bulk-count">0 selected</span>
        <div id="bulk-bar-actions">
          <button id="bulk-select-all" type="button">Select all on page</button>
          <button id="bulk-add-playlist" type="button">Add to slideshow</button>
          <button id="bulk-clear" type="button">Clear selection</button>
          <div id="bulk-danger-group">
            <button id="bulk-soft-delete" type="button">Delete (recoverable)</button>
            <button id="bulk-hard-delete" type="button">Delete permanently</button>
          </div>
        </div>
      </div>
      <div id="bulk-playlist-picker"></div>
      <div class="grid" id="grid"></div>
      <div class="pagination">
        <button id="page-prev" type="button">Previous</button>
        <span class="page-info" id="page-info"></span>
        <button id="page-next" type="button">Next</button>
      </div>
    </section>

    <section id="playlists-section">
      <h2>Programmed slideshows</h2>
      <div id="playlists-list"></div>
      <div id="playlists-empty">No programmed slideshows yet.</div>
      <div id="new-playlist-row">
        <input id="new-playlist-name" type="text"
          placeholder="New slideshow name">
        <button id="new-playlist-btn" type="button">Create</button>
      </div>
    </section>

    <section>
      <h2>Recycle bin</h2>
      <div class="domain-sub">
        Photos deleted with "Delete (recoverable)" land here. Restore them,
        or delete them permanently.
      </div>
      <button id="trash-toggle-btn" type="button" class="collapse-btn"
              aria-label="Show or hide the recycle bin">Show recycle bin</button>
      <div id="trash-panel">
        <div id="trash-empty">Recycle bin is empty.</div>
        <div class="grid" id="trash-grid"></div>
      </div>
    </section>

    <section>
      <h2>Server maintenance</h2>
      <div id="restart-server-row">
        <div class="yf-label">Restart the server that stores your library.</div>
        <button id="btn-restart-server" type="button" class="danger-btn">
          Restart server
        </button>
      </div>
    </section>
  </div>

  <footer>Malmberg self-hosted photo frame</footer>
</main>

<div id="toast-stack"></div>

<div id="modal-backdrop">
  <div id="modal-card">
    <button id="modal-close" type="button" aria-label="Close">&times;</button>
    <div id="modal-img-wrap">
      <img id="modal-img" alt="">
      <video id="modal-video" controls preload="metadata"></video>
    </div>
    <div id="modal-body">
      <div id="modal-title"></div>
      <dl class="detail-grid" id="modal-details"></dl>
      <div class="modal-actions" id="orient-actions">
        <div class="orient-grid">
          <button id="act-rotate-left" type="button" aria-label="Rotate left">
            Rotate left
          </button>
          <button id="act-rotate-right" type="button" aria-label="Rotate right">
            Rotate right
          </button>
          <button id="act-flip-h" type="button" aria-label="Flip horizontal">
            Flip horizontal
          </button>
          <button id="act-flip-v" type="button" aria-label="Flip vertical">
            Flip vertical
          </button>
        </div>
      </div>
      <div class="modal-actions">
        <button id="act-show" type="button">Display it now</button>
        <button id="act-add-playlist" type="button">Add to a slideshow</button>
        <button id="act-soft-delete" type="button">
          Delete (recoverable, goes to trash)
        </button>
        <button id="act-hard-delete" type="button">
          Delete permanently (cannot be undone)
        </button>
      </div>
      <div id="playlist-picker"></div>
    </div>
  </div>
</div>

<div id="review-backdrop">
  <div id="review-card">
    <button id="review-close" type="button" aria-label="Close">&times;</button>
    <div id="review-title"></div>
    <div class="review-tools">
      <input id="review-name" type="text" placeholder="Name this person">
      <button id="review-name-btn" type="button">Save name</button>
    </div>
    <div class="review-tools">
      <input id="review-merge-input" type="text" autocomplete="off"
        list="review-merge-suggestions" placeholder="Merge into person (name)">
      <datalist id="review-merge-suggestions"></datalist>
      <button id="review-merge-btn" type="button">Merge</button>
    </div>
    <div class="domain-sub">
      Each photo shows green corner marks around the face grouped here (the
      marks sit just outside the face so they do not cover it). Tap a photo
      to zoom in and see the face up close. If a face is the wrong person,
      press "Not this person" to split it off.
    </div>
    <div id="review-grid"></div>
  </div>
</div>

<div id="face-zoom-backdrop">
  <div id="face-zoom-card">
    <button id="face-zoom-close" type="button"
            aria-label="Close zoomed photo">&times;</button>
    <canvas id="face-zoom-canvas"></canvas>
    <div id="face-zoom-hint">Tap anywhere outside this photo to close.</div>
  </div>
</div>

<script>
(function () {
  "use strict";

  /* ---- Role ----
     "server": served by the Server, from /dashboard. All calls are relative
     to the server (library endpoints and /control/* proxies to the paired
     display).
     "display": served by the Display itself, from its own /dashboard.
     Library endpoints (/media*, /stats) are still relative -- the display
     proxies them to its paired server -- but slideshow controls talk to the
     display's own /slideshow/* routes directly instead of round-tripping
     through a server's /control/* proxy. Multi-display selection, the
     year-filter "play query" shortcut, and programmed slideshows are
     server-only features and are hidden in this role. */
  var MALMBERG_ROLE = "__MALMBERG_ROLE__";

  /* Map a server-style /control/* control path to this role's real target. */
  function mapControlPath(path) {
    if (MALMBERG_ROLE !== "display") return path;
    if (path === "/control/status") return "/status";
    if (path === "/control/next") return "/slideshow/next";
    if (path === "/control/prev") return "/slideshow/prev";
    if (path === "/control/pause") return "/slideshow/pause";
    if (path === "/control/play-all") return "/slideshow/all";
    if (path === "/control/restart") return "/admin/restart";
    var showPrefix = "/control/show/";
    if (path.indexOf(showPrefix) === 0) {
      return "/slideshow/show/" + path.slice(showPrefix.length);
    }
    return path;
  }

  /* ---- Toasts ---- */
  var toastStack = document.getElementById("toast-stack");

  function showToast(message, kind) {
    var el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    toastStack.appendChild(el);
    window.requestAnimationFrame(function () {
      el.className += " show";
    });
    window.setTimeout(function () {
      el.className = el.className.replace(" show", "");
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 220);
    }, 3200);
  }

  /* ---- Stats ---- */
  var statsCount = document.getElementById("stats-count");
  var statsGrid = document.getElementById("stats-grid");
  var byYear = document.getElementById("by-year");
  var byMonth = document.getElementById("by-month");
  var byPlace = document.getElementById("by-place");
  var byPerson = document.getElementById("by-person");
  var MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
  ];

  function loadStats() {
    fetch("/stats")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        statsCount.innerHTML =
          data.total + ' <span class="label">photos and videos</span>';
        statsGrid.innerHTML = "";
        var tiles = [
          ["Photos", data.images],
          ["Videos", data.videos],
          ["Undated", data.undated],
          ["Earliest", data.earliest ? data.earliest.slice(0, 10) : "--"],
          ["Latest", data.latest ? data.latest.slice(0, 10) : "--"],
        ];
        tiles.forEach(function (pair) {
          var tile = document.createElement("div");
          tile.className = "stat-tile";
          tile.innerHTML =
            '<div class="n"></div><div class="k"></div>';
          tile.querySelector(".n").textContent = String(pair[1]);
          tile.querySelector(".k").textContent = pair[0];
          statsGrid.appendChild(tile);
        });
        byYear.innerHTML = "";
        Object.keys(data.by_year || {}).sort().forEach(function (year) {
          var chip = document.createElement("button");
          chip.type = "button";
          chip.className = "year-chip";
          chip.innerHTML = "<b></b> " + year;
          chip.querySelector("b").textContent = String(data.by_year[year]);
          chip.title = "Search and browse " + year;
          chip.setAttribute("aria-label", "Search and browse photos from " + year);
          chip.addEventListener("click", function () {
            timeInput.value = year;
            state.qTime = year;
            state.page = 1;
            loadGrid();
            showResultsBelow();
          });
          byYear.appendChild(chip);
        });
        // Granular month breakdown, grouped under each year (newest first).
        byMonth.innerHTML = "";
        var byMonthData = data.by_month || {};
        var monthsByYear = {};
        Object.keys(byMonthData).forEach(function (ym) {
          var y = ym.slice(0, 4);
          (monthsByYear[y] = monthsByYear[y] || []).push(ym);
        });
        Object.keys(monthsByYear).sort().reverse().forEach(function (year) {
          var group = document.createElement("div");
          group.className = "month-group";
          var yearEl = document.createElement("div");
          yearEl.className = "mg-year";
          yearEl.textContent = year;
          var monthsEl = document.createElement("div");
          monthsEl.className = "mg-months";
          monthsByYear[year].sort().forEach(function (ym) {
            var mi = parseInt(ym.slice(5, 7), 10) - 1;
            var monthName = MONTH_NAMES[mi] || ym.slice(5, 7);
            var chip = document.createElement("button");
            chip.type = "button";
            chip.className = "month-chip";
            chip.innerHTML = "<b></b> ";
            chip.querySelector("b").textContent = String(byMonthData[ym]);
            chip.appendChild(document.createTextNode(monthName));
            chip.title = "Search and browse " + monthName + " " + year;
            chip.setAttribute(
              "aria-label",
              "Search and browse photos from " + monthName + " " + year
            );
            chip.addEventListener("click", function () {
              timeInput.value = ym;
              state.qTime = ym;
              state.page = 1;
              loadGrid();
              showResultsBelow();
            });
            monthsEl.appendChild(chip);
          });
          group.appendChild(yearEl);
          group.appendChild(monthsEl);
          byMonth.appendChild(group);
        });
        byPlace.innerHTML = "";
        var byPlaceData = data.by_place || {};
        Object.keys(byPlaceData).forEach(function (place) {
          var chip = document.createElement("button");
          chip.type = "button";
          chip.className = "place-chip";
          chip.innerHTML = "<b></b> ";
          chip.querySelector("b").textContent = String(byPlaceData[place]);
          chip.appendChild(document.createTextNode(place));
          chip.title = "Search and browse " + place;
          chip.setAttribute("aria-label", "Search and browse photos from " + place);
          chip.addEventListener("click", function () {
            placeInput.value = place;
            state.qPlace = place;
            state.page = 1;
            loadGrid();
            showResultsBelow();
          });
          byPlace.appendChild(chip);
        });
        byPerson.innerHTML = "";
        var byPersonData = data.by_person || {};
        Object.keys(byPersonData).forEach(function (name) {
          var chip = document.createElement("button");
          chip.type = "button";
          chip.className = "place-chip";
          chip.innerHTML = "<b></b> ";
          chip.querySelector("b").textContent = String(byPersonData[name]);
          chip.appendChild(document.createTextNode(name));
          chip.title = "Search and browse photos of " + name;
          chip.setAttribute("aria-label", "Search and browse photos of " + name);
          chip.addEventListener("click", function () {
            personInput.value = name;
            state.qPerson = name;
            state.page = 1;
            loadGrid();
            showResultsBelow();
          });
          byPerson.appendChild(chip);
        });
      })
      .catch(function () {
        statsCount.innerHTML = '-- <span class="label">stats unavailable</span>';
      });
  }

  /* ---- Upload ---- */
  var dropzone = document.getElementById("dropzone");
  var picker = document.getElementById("picker-btn");
  var input = document.getElementById("file-input");
  var uploadList = document.getElementById("upload-list");
  var uploadSummary = document.getElementById("upload-summary");

  var CONCURRENCY = 3;

  picker.addEventListener("click", function () { input.click(); });

  input.addEventListener("change", function () {
    handleFiles(input.files);
    input.value = "";
  });

  ["dragenter", "dragover"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.remove("drag");
    });
  });
  dropzone.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files) {
      handleFiles(e.dataTransfer.files);
    }
  });

  function handleFiles(fileList) {
    var files = Array.prototype.slice.call(fileList);
    if (files.length === 0) return;

    uploadSummary.className = "show";
    uploadSummary.textContent = "Uploading 0 / " + files.length + "...";

    var results = { ok: 0, dup: 0, err: 0 };
    var completed = 0;
    var total = files.length;

    var rows = files.map(function (file) {
      var row = document.createElement("div");
      row.className = "row";
      row.innerHTML =
        '<img class="thumb" alt="">' +
        '<div class="body">' +
        '<div class="name"></div>' +
        '<div class="status">Queued</div>' +
        '<div class="bar-track"><div class="bar-fill"></div></div>' +
        '</div>';
      row.querySelector(".name").textContent = file.name;
      uploadList.appendChild(row);
      return row;
    });

    var idx = 0;
    function next() {
      if (idx >= files.length) return;
      var myIdx = idx++;
      uploadOne(files[myIdx], rows[myIdx], function (kind) {
        completed++;
        results[kind]++;
        uploadSummary.textContent =
          "Uploaded " + completed + " / " + total +
          "  (ok: " + results.ok + ", already exists: " + results.dup +
          ", failed: " + results.err + ")";
        if (completed === total) {
          loadStats();
          loadGrid();
        }
        next();
      });
    }
    for (var i = 0; i < Math.min(CONCURRENCY, files.length); i++) next();
  }

  function uploadOne(file, row, done) {
    var statusEl = row.querySelector(".status");
    var fillEl = row.querySelector(".bar-fill");
    statusEl.textContent = "Uploading...";

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload", true);

    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        var pct = Math.round((e.loaded / e.total) * 100);
        fillEl.style.width = pct + "%";
      }
    };

    xhr.onload = function () {
      if (xhr.status === 200) {
        row.className = "row ok";
        fillEl.style.width = "100%";
        statusEl.textContent = "Uploaded";
        try {
          var item = JSON.parse(xhr.responseText);
          if (item && item.id) {
            var thumb = row.querySelector(".thumb");
            thumb.src = "/media/" + item.id + "/thumb?size=80";
          }
        } catch (e) { /* no thumbnail if the body is not JSON */ }
        done("ok");
      } else if (xhr.status === 409) {
        row.className = "row dup";
        fillEl.style.width = "100%";
        statusEl.textContent = "Already exists";
        done("dup");
      } else {
        row.className = "row err";
        statusEl.textContent = "Failed (" + xhr.status + ")";
        done("err");
      }
    };
    xhr.onerror = function () {
      row.className = "row err";
      statusEl.textContent = "Network error";
      done("err");
    };

    var form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  }

  /* ---- Now playing / live display controls ---- */
  var nowPlaying = document.getElementById("now-playing");
  var nowMeta = document.getElementById("now-meta");
  var nowThumbWrap = document.getElementById("now-thumb-wrap");
  var hint = document.getElementById("control-hint");
  var btnPrev = document.getElementById("btn-prev");
  var btnNext = document.getElementById("btn-next");
  var btnPause = document.getElementById("btn-pause");
  var btnPlayAll = document.getElementById("btn-play-all");
  var displaySelect = document.getElementById("display-select");
  var yearFilterButtons = document.getElementById("year-filter-buttons");

  var lastCurrentItemId = null;
  var lastDisplaysKey = null;

  function setControlsDisabled(disabled) {
    btnPrev.disabled = disabled;
    btnNext.disabled = disabled;
    btnPause.disabled = disabled;
    btnPlayAll.disabled = disabled;
    hint.className = disabled ? "show" : "";
  }

  function setNowThumb(itemId) {
    if (itemId === lastCurrentItemId) return;
    lastCurrentItemId = itemId;
    nowThumbWrap.innerHTML = "";
    if (itemId) {
      // The now-showing photo is a real library item: make it a big clickable
      // button that opens that photo's options (details / delete / show).
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "now-thumb-btn";
      btn.setAttribute("aria-label", "See options for the photo now showing");
      btn.title = "Tap to see this photo's options";
      btn.addEventListener("click", function () { openModal(itemId); });
      var img = document.createElement("img");
      img.src = "/media/" + itemId + "/thumb?size=160";
      img.alt = "Now showing";
      btn.appendChild(img);
      nowThumbWrap.appendChild(btn);
    } else {
      var ph = document.createElement("span");
      ph.className = "placeholder";
      ph.textContent = "--";
      nowThumbWrap.appendChild(ph);
    }
  }

  function updateDisplaySelect(displays, selected) {
    displays = displays || [];
    var key = JSON.stringify(displays) + "|" + selected;
    if (key === lastDisplaysKey) return;
    lastDisplaysKey = key;
    displaySelect.innerHTML = "";
    displays.forEach(function (d) {
      var opt = document.createElement("option");
      opt.value = d.name;
      opt.textContent = d.name;
      if (d.name === selected) opt.selected = true;
      displaySelect.appendChild(opt);
    });
    displaySelect.disabled = displays.length <= 1;
  }

  function refreshStatus() {
    fetch(mapControlPath("/control/status"))
      .then(function (r) {
        if (r.status === 503) {
          setControlsDisabled(true);
          nowPlaying.textContent = "Display not configured";
          nowMeta.textContent = "";
          setNowThumb(null);
          return null;
        }
        setControlsDisabled(false);
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        nowPlaying.textContent = data.current_item || "(nothing playing)";
        nowMeta.textContent =
          (data.paused ? "Paused" : "Playing") +
          "  -  queue depth " + data.queue_depth +
          "  -  history " + data.history_count;
        btnPause.textContent = data.paused ? "Resume" : "Pause";
        setNowThumb(data.current_item_id || null);
        updateDisplaySelect(data.displays, data.selected);
      })
      .catch(function () {
        setControlsDisabled(true);
        nowPlaying.textContent = "Unable to reach display";
        nowMeta.textContent = "";
        setNowThumb(null);
      });
  }

  displaySelect.addEventListener("change", function () {
    var name = displaySelect.value;
    if (!name) return;
    fetch("/control/select/" + encodeURIComponent(name), { method: "POST" })
      .then(function (r) {
        if (r.ok) {
          showToast("Now controlling \\"" + name + "\\".", "ok");
        } else {
          showToast("Could not switch display.", "err");
        }
      })
      .catch(function () { showToast("Could not switch display.", "err"); })
      .then(function () { refreshStatus(); });
  });

  var loopToggle = document.getElementById("loop-toggle");
  function isLoop() { return !!(loopToggle && loopToggle.checked); }
  function loopNote(base) {
    return isLoop()
      ? base + ' It will keep looping; press "Play whole library" to stop.'
      : base + " It plays once, then all photos come back.";
  }

  /* ---- Show-on-frame: three independent Time / Place / Person boxes that
     AND together (same layout as the library search), driving a small
     browsable preview of exactly what "Show on frame" will play. ---- */
  var frameTimeInput = document.getElementById("frame-time-input");
  var framePlaceInput = document.getElementById("frame-place-input");
  var framePersonInput = document.getElementById("frame-person-input");
  var framePlaceSuggestions =
    document.getElementById("frame-place-suggestions");
  var framePersonSuggestions =
    document.getElementById("frame-person-suggestions");
  var framePreviewGrid = document.getElementById("frame-preview-grid");
  var framePreviewEmpty = document.getElementById("frame-preview-empty");
  var framePreviewPrev = document.getElementById("frame-preview-prev");
  var framePreviewNext = document.getElementById("frame-preview-next");
  var framePreviewInfo = document.getElementById("frame-preview-info");
  var FRAME_PREVIEW_PAGE_SIZE = 12;
  var framePreviewState = { page: 1, hasNext: false, total: 0 };

  /* Read the three frame boxes into {time, place, person} (trimmed). */
  function frameFilters() {
    return {
      time: frameTimeInput.value.trim(),
      place: framePlaceInput.value.trim(),
      person: framePersonInput.value.trim(),
    };
  }

  function frameHasFilter(f) {
    return !!(f.time || f.place || f.person);
  }

  /* Build the shared &q_time=&q_place=&q_person= query fragment. */
  function frameParams(f) {
    var parts = [];
    if (f.time) parts.push("q_time=" + encodeURIComponent(f.time));
    if (f.place) parts.push("q_place=" + encodeURIComponent(f.place));
    if (f.person) parts.push("q_person=" + encodeURIComponent(f.person));
    return parts.join("&");
  }

  /* A short plain-language label of the current frame filters, for toasts. */
  function frameLabel(f) {
    var bits = [];
    if (f.time) bits.push(f.time);
    if (f.place) bits.push(f.place);
    if (f.person) bits.push(f.person);
    return bits.join(", ");
  }

  function renderFramePreview(items) {
    framePreviewGrid.innerHTML = "";
    items.forEach(function (item) {
      var tile = document.createElement("div");
      tile.className = "tile";
      var img = document.createElement("img");
      img.src = "/media/" + item.id + "/thumb?size=200";
      img.alt = item.filename;
      img.loading = "lazy";
      tile.appendChild(img);
      framePreviewGrid.appendChild(tile);
    });
  }

  function loadFramePreview(page) {
    framePreviewState.page = page || 1;
    var f = frameFilters();
    if (!frameHasFilter(f)) {
      framePreviewGrid.innerHTML = "";
      framePreviewEmpty.style.display = "none";
      framePreviewInfo.textContent = "";
      framePreviewPrev.disabled = true;
      framePreviewNext.disabled = true;
      return;
    }
    var params = frameParams(f) +
      "&page=" + framePreviewState.page +
      "&page_size=" + FRAME_PREVIEW_PAGE_SIZE + "&sort=recent";
    fetch("/media?" + params)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var items = data.items || [];
        framePreviewState.hasNext = !!data.has_next;
        framePreviewState.total = data.total || 0;
        renderFramePreview(items);
        framePreviewEmpty.style.display = items.length ? "none" : "block";
        framePreviewInfo.textContent = framePreviewState.total
          ? "Page " + framePreviewState.page + " of " +
            Math.max(1, Math.ceil(framePreviewState.total / FRAME_PREVIEW_PAGE_SIZE))
          : "";
        framePreviewPrev.disabled = framePreviewState.page <= 1;
        framePreviewNext.disabled = !framePreviewState.hasNext;
      })
      .catch(function () {
        framePreviewGrid.innerHTML = "";
        framePreviewEmpty.textContent = "Could not load preview.";
        framePreviewEmpty.style.display = "block";
      });
  }

  framePreviewPrev.addEventListener("click", function () {
    if (framePreviewState.page > 1) {
      loadFramePreview(framePreviewState.page - 1);
    }
  });
  framePreviewNext.addEventListener("click", function () {
    if (framePreviewState.hasNext) {
      loadFramePreview(framePreviewState.page + 1);
    }
  });

  function setActiveYear(btn) {
    var all = yearFilterButtons.querySelectorAll("button");
    for (var i = 0; i < all.length; i++) all[i].classList.remove("yf-active");
    if (btn) btn.classList.add("yf-active");
  }

  function loadYearFilter() {
    fetch("/stats")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        yearFilterButtons.innerHTML = "";
        var allBtn = document.createElement("button");
        allBtn.type = "button";
        allBtn.className = "yf-all";
        allBtn.textContent = "All";
        allBtn.addEventListener("click", function () {
          setActiveYear(allBtn);
          runControl(allBtn, "/control/play-all", "POST", undefined,
            "...", "Now playing the whole library.");
        });
        yearFilterButtons.appendChild(allBtn);
        Object.keys(data.by_year || {}).sort().forEach(function (year) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = year;
          btn.addEventListener("click", function () {
            setActiveYear(btn);
            frameTimeInput.value = year;
            framePlaceInput.value = "";
            framePersonInput.value = "";
            loadFramePreview(1);
            runControl(
              btn,
              "/control/play-query?q_time=" + encodeURIComponent(year) +
                "&loop=" + isLoop(),
              "POST",
              undefined,
              "...",
              loopNote("Now showing " + year + ".")
            );
          });
          yearFilterButtons.appendChild(btn);
        });
      })
      .catch(function () {});
  }

  /* Runs a control action with immediate button feedback (busy state,
     disable while in flight) followed by a toast confirming what
     happened, then refreshes status so the "now showing" area stays
     in sync with the display (which preempts immediately). */
  function runControl(btn, path, method, body, busyText, okMessage) {
    path = mapControlPath(path);
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.className += " busy";
    btn.textContent = busyText;

    var opts = { method: method || "POST" };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }

    fetch(path, opts)
      .then(function (r) {
        if (r.status === 503) {
          showToast("Display not configured.", "err");
          return null;
        }
        if (!r.ok) {
          showToast("Could not reach the display. Try again.", "err");
          return null;
        }
        showToast(
          typeof okMessage === "function" ? okMessage() : okMessage,
          "ok"
        );
        return r.json().catch(function () { return null; });
      })
      .catch(function () {
        showToast("Could not reach the display. Try again.", "err");
      })
      .then(function () {
        btn.disabled = false;
        btn.className = btn.className.replace(" busy", "");
        btn.textContent = originalText;
        refreshStatus();
      });
  }

  btnPrev.addEventListener("click", function () {
    runControl(btnPrev, "/control/prev", "POST", undefined,
      "...", "Skipped to the previous photo.");
  });
  btnNext.addEventListener("click", function () {
    runControl(btnNext, "/control/next", "POST", undefined,
      "...", "Skipped to the next photo.");
  });
  var btnRestartDisplay = document.getElementById("btn-restart-display");
  var btnRestartServer = document.getElementById("btn-restart-server");

  btnRestartDisplay.addEventListener("click", function () {
    if (!window.confirm(
      "Restart the display now? It will be unavailable for a few seconds."
    )) return;
    runControl(btnRestartDisplay, "/control/restart", "POST", undefined,
      "...", "Restarting the display.");
  });

  btnRestartServer.addEventListener("click", function () {
    if (!window.confirm(
      "Restart the server now? It will be unavailable for a few seconds."
    )) return;
    var path = MALMBERG_ROLE === "display"
      ? "/control/restart-server"
      : "/admin/restart";
    runControl(btnRestartServer, path, "POST", undefined,
      "...", "Restarting the server.");
  });

  btnPause.addEventListener("click", function () {
    var willResume = btnPause.textContent === "Resume";
    runControl(btnPause, "/control/pause", "POST", undefined,
      "...", willResume ? "Resumed the slideshow." : "Paused the slideshow.");
  });
  btnPlayAll.addEventListener("click", function () {
    runControl(btnPlayAll, "/control/play-all", "POST", undefined,
      "...", "Now playing the whole library.");
  });

  /* ---- Browse / search grid, server-side paginated ---- */
  var grid = document.getElementById("grid");
  var refreshBtn = document.getElementById("refresh-btn");
  var searchInput = document.getElementById("search-input");
  var resultsSummary = document.getElementById("results-summary");
  var pagePrev = document.getElementById("page-prev");
  var pageNext = document.getElementById("page-next");
  var pageInfo = document.getElementById("page-info");
  var selectToggleBtn = document.getElementById("select-toggle-btn");
  var bulkBar = document.getElementById("bulk-bar");
  var bulkCount = document.getElementById("bulk-count");
  var bulkSelectAll = document.getElementById("bulk-select-all");
  var bulkClear = document.getElementById("bulk-clear");
  var bulkSoftDelete = document.getElementById("bulk-soft-delete");
  var bulkHardDelete = document.getElementById("bulk-hard-delete");
  var bulkAddPlaylist = document.getElementById("bulk-add-playlist");
  var bulkPlaylistPicker = document.getElementById("bulk-playlist-picker");

  var PAGE_SIZE = 24;
  var state = {
    page: 1, q: "", qTime: "", qPlace: "", qPerson: "",
    hasNext: false, total: 0, items: [],
    selectMode: false, selected: {},
  };
  var searchDebounce = null;

  /* When a filter/search runs, the tall People section can hide the
     results below it -- collapse it and scroll the grid into view so the
     photos the user just asked for are immediately visible. */
  function showResultsBelow() {
    if (peopleBody && !peopleBody.classList.contains("collapsed")) {
      peopleBody.classList.add("collapsed");
      peopleToggle.textContent = "Show";
    }
    var target = document.getElementById("results-summary");
    if (target && target.scrollIntoView) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    showToast("Showing results below.", "ok");
  }

  function totalPages() {
    return Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  }

  function updateBulkBar() {
    var ids = Object.keys(state.selected);
    bulkBar.className = state.selectMode ? "show" : "";
    bulkCount.textContent = ids.length + " selected";
    if (!state.selectMode) bulkPlaylistPicker.innerHTML = "";
  }

  function toggleSelectMode() {
    state.selectMode = !state.selectMode;
    selectToggleBtn.className = state.selectMode ? "active" : "";
    selectToggleBtn.textContent = state.selectMode ? "Done selecting" : "Bulk Select";
    if (!state.selectMode) {
      state.selected = {};
    }
    updateBulkBar();
    renderGrid();
  }

  function toggleItemSelected(itemId) {
    if (state.selected[itemId]) {
      delete state.selected[itemId];
    } else {
      state.selected[itemId] = true;
    }
    updateBulkBar();
    renderGrid();
  }

  selectToggleBtn.addEventListener("click", toggleSelectMode);
  bulkClear.addEventListener("click", function () {
    state.selected = {};
    updateBulkBar();
    renderGrid();
  });
  bulkSelectAll.addEventListener("click", function () {
    state.items.forEach(function (item) { state.selected[item.id] = true; });
    updateBulkBar();
    renderGrid();
  });

  function renderGrid() {
    grid.innerHTML = "";
    state.items.forEach(function (item) {
      var tile = document.createElement("div");
      var selected = !!state.selected[item.id];
      tile.className = "tile" + (selected ? " selected" : "");

      var img = document.createElement("img");
      var gridV = mediaVersionParam(item);
      img.src = "/media/" + item.id + "/thumb" + (gridV ? "?" + gridV : "");
      img.alt = item.filename;
      img.loading = "lazy";
      tile.appendChild(img);

      if (item.kind === "video") {
        var badge = document.createElement("div");
        badge.className = "play-badge";
        tile.appendChild(badge);
      }

      if (state.selectMode) {
        var mark = document.createElement("div");
        mark.className = "select-mark";
        mark.textContent = selected ? "\\u2713" : "";
        tile.appendChild(mark);
        tile.addEventListener("click", function () {
          if (consumeLongPressSuppression()) return;
          toggleItemSelected(item.id);
        });
      } else {
        tile.addEventListener("click", function () {
          if (consumeLongPressSuppression()) return;
          openModal(item.id);
        });
      }

      attachLongPress(tile, item);
      grid.appendChild(tile);
    });
  }

  /* ---- Long-press to enter bulk-select (touch and mouse) ----
     A long-press re-renders the grid mid-gesture (to show the selection
     mark), which replaces the tile element before the browser's follow-up
     "click" fires. That click then lands on the freshly-rendered tile in
     the same spot, so a single shared flag (not a per-tile closure) is
     used to swallow exactly that one click, wherever it lands. */
  var LONG_PRESS_MS = 500;
  var LONG_PRESS_MOVE_TOLERANCE = 12;
  var suppressNextTileClick = false;
  var suppressResetTimer = null;

  function consumeLongPressSuppression() {
    if (!suppressNextTileClick) return false;
    suppressNextTileClick = false;
    if (suppressResetTimer) {
      window.clearTimeout(suppressResetTimer);
      suppressResetTimer = null;
    }
    return true;
  }

  function attachLongPress(tile, item) {
    var pressTimer = null;
    var startX = 0;
    var startY = 0;

    function clearPressTimer() {
      if (pressTimer) {
        window.clearTimeout(pressTimer);
        pressTimer = null;
      }
    }

    tile.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      startX = e.clientX;
      startY = e.clientY;
      clearPressTimer();
      pressTimer = window.setTimeout(function () {
        pressTimer = null;
        suppressNextTileClick = true;
        // Safety net: if no click follows (e.g. touch cancel quirks),
        // do not let the suppression leak into an unrelated later tap.
        suppressResetTimer = window.setTimeout(function () {
          suppressNextTileClick = false;
        }, 600);
        if (!state.selectMode) {
          state.selectMode = true;
          selectToggleBtn.className = "active";
          selectToggleBtn.textContent = "Done selecting";
        }
        if (!state.selected[item.id]) {
          state.selected[item.id] = true;
        }
        updateBulkBar();
        renderGrid();
      }, LONG_PRESS_MS);
    });

    tile.addEventListener("pointermove", function (e) {
      if (!pressTimer) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      if (Math.sqrt(dx * dx + dy * dy) > LONG_PRESS_MOVE_TOLERANCE) {
        clearPressTimer();
      }
    });

    tile.addEventListener("pointerup", clearPressTimer);
    tile.addEventListener("pointercancel", clearPressTimer);
    tile.addEventListener("pointerleave", clearPressTimer);
  }

  function loadGrid() {
    var params = "page=" + state.page + "&page_size=" + PAGE_SIZE +
      "&sort=recent";
    if (state.q) params += "&q=" + encodeURIComponent(state.q);
    if (state.qTime) params += "&q_time=" + encodeURIComponent(state.qTime);
    if (state.qPlace) params += "&q_place=" + encodeURIComponent(state.qPlace);
    if (state.qPerson) params += "&q_person=" + encodeURIComponent(state.qPerson);

    fetch("/media?" + params)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.hasNext = !!data.has_next;
        state.total = data.total || 0;
        state.items = data.items || [];

        renderGrid();

        if (state.total === 0) {
          resultsSummary.textContent = state.q
            ? "No photos match \\"" + state.q + "\\"."
            : "No photos yet.";
        } else {
          var start = (state.page - 1) * PAGE_SIZE + 1;
          var end = Math.min(state.page * PAGE_SIZE, state.total);
          resultsSummary.textContent =
            "Showing " + start + "-" + end + " of " + state.total;
        }
        pageInfo.textContent = "Page " + state.page + " of " + totalPages();
        pagePrev.disabled = state.page <= 1;
        pageNext.disabled = !state.hasNext;
      })
      .catch(function () {
        grid.innerHTML = "<div>Could not load photos.</div>";
        resultsSummary.textContent = "";
      });
  }

  refreshBtn.addEventListener("click", function () {
    loadStats();
    loadGrid();
  });

  searchInput.addEventListener("input", function () {
    var value = searchInput.value;
    if (searchDebounce) window.clearTimeout(searchDebounce);
    searchDebounce = window.setTimeout(function () {
      state.q = value.trim();
      state.page = 1;
      loadGrid();
      if (state.q) showResultsBelow();
    }, 350);
  });

  /* ---- Library search boxes (filter the browse grid only) ----
     Time / Place / Person are independent boxes that AND together via
     separate q_time / q_place / q_person params -- filling in more than
     one narrows the results to items matching ALL of them. */
  var timeInput = document.getElementById("time-input");
  var placeInput = document.getElementById("place-input");
  var placeSuggestions = document.getElementById("place-suggestions");
  var personInput = document.getElementById("person-input");
  var personSuggestions = document.getElementById("person-suggestions");
  var timeDebounce = null;
  var placeDebounce = null;
  var personDebounce = null;

  function fillDatalist(el, values) {
    el.innerHTML = "";
    (values || []).forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v;
      el.appendChild(opt);
    });
  }

  function loadPlaceSuggestions(prefix, into) {
    fetch("/places?q=" + encodeURIComponent(prefix) + "&limit=10")
      .then(function (r) { return r.json(); })
      .then(function (places) { fillDatalist(into, places); })
      .catch(function () {});
  }

  function loadPersonSuggestions(prefix, into) {
    fetch("/people/suggest?q=" + encodeURIComponent(prefix) + "&limit=10")
      .then(function (r) { return r.json(); })
      .then(function (names) { fillDatalist(into, names); })
      .catch(function () {});
  }

  timeInput.addEventListener("input", function () {
    if (timeDebounce) window.clearTimeout(timeDebounce);
    timeDebounce = window.setTimeout(function () {
      state.qTime = timeInput.value.trim();
      state.page = 1;
      loadGrid();
      if (state.qTime) showResultsBelow();
    }, 350);
  });

  placeInput.addEventListener("input", function () {
    if (placeDebounce) window.clearTimeout(placeDebounce);
    placeDebounce = window.setTimeout(function () {
      loadPlaceSuggestions(placeInput.value.trim(), placeSuggestions);
      state.qPlace = placeInput.value.trim();
      state.page = 1;
      loadGrid();
      if (state.qPlace) showResultsBelow();
    }, 350);
  });

  personInput.addEventListener("input", function () {
    if (personDebounce) window.clearTimeout(personDebounce);
    personDebounce = window.setTimeout(function () {
      loadPersonSuggestions(personInput.value.trim(), personSuggestions);
      state.qPerson = personInput.value.trim();
      state.page = 1;
      loadGrid();
      if (state.qPerson) showResultsBelow();
    }, 350);
  });

  loadPlaceSuggestions("", placeSuggestions);
  loadPersonSuggestions("", personSuggestions);

  /* ---- Frame Time / Place / Person boxes: same AND layout as the library
     search, but they drive the preview + "Show on frame" (play-query with
     q_time / q_place / q_person) instead of the browse grid. ---- */
  var frameSearchPlayBtn = document.getElementById("frame-search-play-btn");
  var frameTimeDebounce = null;
  var framePlaceDebounce = null;
  var framePersonDebounce = null;

  frameTimeInput.addEventListener("input", function () {
    if (frameTimeDebounce) window.clearTimeout(frameTimeDebounce);
    frameTimeDebounce = window.setTimeout(function () {
      setActiveYear(null);
      loadFramePreview(1);
    }, 350);
  });

  framePlaceInput.addEventListener("input", function () {
    if (framePlaceDebounce) window.clearTimeout(framePlaceDebounce);
    framePlaceDebounce = window.setTimeout(function () {
      loadPlaceSuggestions(framePlaceInput.value.trim(), framePlaceSuggestions);
      loadFramePreview(1);
    }, 350);
  });

  framePersonInput.addEventListener("input", function () {
    if (framePersonDebounce) window.clearTimeout(framePersonDebounce);
    framePersonDebounce = window.setTimeout(function () {
      loadPersonSuggestions(
        framePersonInput.value.trim(), framePersonSuggestions
      );
      loadFramePreview(1);
    }, 350);
  });

  function playFrameSearch() {
    var f = frameFilters();
    if (!frameHasFilter(f)) {
      showToast("Fill in a time, place, or name first.", "err");
      return;
    }
    loadFramePreview(1);
    runControl(frameSearchPlayBtn,
      "/control/play-query?" + frameParams(f) + "&loop=" + isLoop(),
      "POST", undefined, "...",
      loopNote('Now showing "' + frameLabel(f) + '".'));
  }
  frameSearchPlayBtn.addEventListener("click", playFrameSearch);
  [frameTimeInput, framePlaceInput, framePersonInput].forEach(function (el) {
    el.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") playFrameSearch();
    });
  });

  loadPlaceSuggestions("", framePlaceSuggestions);
  loadPersonSuggestions("", framePersonSuggestions);
  loadFramePreview(1);

  /* ---- People: compact collapsible cards, naming, review, merge ---- */
  var peopleGrid = document.getElementById("people-grid");
  var peopleEmpty = document.getElementById("people-empty");
  var peopleToggle = document.getElementById("people-toggle");
  var peopleBody = document.getElementById("people-body");
  var peopleShowSmall = document.getElementById("people-show-small");
  var peopleCache = [];

  peopleToggle.addEventListener("click", function () {
    var collapsed = peopleBody.classList.toggle("collapsed");
    peopleToggle.textContent = collapsed ? "Show" : "Hide";
  });
  var peopleMaximize = document.getElementById("people-maximize");
  peopleMaximize.addEventListener("click", function () {
    var max = peopleGrid.classList.toggle("maximized");
    peopleMaximize.textContent = max ? "Scroll box" : "Maximize";
  });
  peopleShowSmall.addEventListener("change", loadPeople);

  function postName(personId, newName) {
    return fetch("/people/" + personId + "/name", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
  }

  function refreshPersonDatalists() {
    loadPersonSuggestions("", personSuggestions);
    loadPersonSuggestions("", framePersonSuggestions);
  }

  function makePersonCard(person) {
    var card = document.createElement("div");
    card.className = "person-card";

    /* The photo is the primary click target -- tapping it opens the
       review modal directly (no small button row to misclick). */
    var photoBtn = document.createElement("button");
    photoBtn.type = "button";
    photoBtn.className = "person-photo-btn";
    photoBtn.setAttribute(
      "aria-label",
      "Review photos of " + (person.name || "this unnamed person")
    );
    var img = document.createElement("img");
    img.src = person.sample_item_id
      ? "/media/" + person.sample_item_id + "/thumb?size=200" : "";
    img.alt = person.name || "Unnamed person";
    photoBtn.appendChild(img);
    photoBtn.addEventListener("click", function () { openReview(person); });
    card.appendChild(photoBtn);

    var nameEl = document.createElement("div");
    nameEl.className = "person-name" + (person.name ? "" : " unnamed");
    nameEl.textContent = person.name || "Unnamed person";
    card.appendChild(nameEl);

    var count = document.createElement("div");
    count.className = "person-count";
    count.textContent = person.count + " photo" + (person.count === 1 ? "" : "s");
    card.appendChild(count);

    /* One big, obvious naming control -- no cramped inline buttons. */
    var nameBtn = document.createElement("button");
    nameBtn.type = "button";
    nameBtn.className = "person-name-btn";
    nameBtn.textContent = person.name ? "Rename this person" : "Name this person";

    var editWrap = document.createElement("div");
    editWrap.className = "person-name-edit";
    var editInput = document.createElement("input");
    editInput.type = "text";
    editInput.placeholder = "Name this person";
    editInput.setAttribute("aria-label", "Name this person");
    editInput.value = person.name || "";
    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save name";
    editWrap.appendChild(editInput);
    editWrap.appendChild(saveBtn);
    card.appendChild(nameBtn);
    card.appendChild(editWrap);

    nameBtn.addEventListener("click", function () {
      var showing = editWrap.classList.toggle("show");
      if (showing) editInput.focus();
    });
    function saveEditedName() {
      var newName = editInput.value.trim();
      if (!newName) { showToast("Type a name first.", "err"); return; }
      postName(person.id, newName)
        .then(function (r) {
          if (!r.ok) throw new Error("failed");
          showToast('Named "' + newName + '".', "ok");
          loadPeople(); loadStats(); refreshPersonDatalists();
        })
        .catch(function () { showToast("Could not save name.", "err"); });
    }
    saveBtn.addEventListener("click", saveEditedName);
    editInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") saveEditedName();
    });
    return card;
  }

  function loadPeople() {
    var minCount = peopleShowSmall.checked ? 1 : 3;
    fetch("/people?min_count=" + minCount)
      .then(function (r) { return r.json(); })
      .then(function (people) {
        peopleCache = people || [];
        peopleGrid.innerHTML = "";
        peopleEmpty.style.display = peopleCache.length ? "none" : "block";
        peopleCache.forEach(function (person) {
          peopleGrid.appendChild(makePersonCard(person));
        });
      })
      .catch(function () {});
  }

  /* ---- Person review modal (green boxes + reassign + merge) ---- */
  var reviewBackdrop = document.getElementById("review-backdrop");
  var reviewClose = document.getElementById("review-close");
  var reviewTitle = document.getElementById("review-title");
  var reviewGrid = document.getElementById("review-grid");
  var reviewName = document.getElementById("review-name");
  var reviewNameBtn = document.getElementById("review-name-btn");
  var reviewMergeInput = document.getElementById("review-merge-input");
  var reviewMergeSuggestions = document.getElementById("review-merge-suggestions");
  var reviewMergeBtn = document.getElementById("review-merge-btn");
  var reviewPerson = null;

  function closeReview() {
    reviewBackdrop.classList.remove("show");
    reviewPerson = null;
  }
  reviewClose.addEventListener("click", closeReview);
  reviewBackdrop.addEventListener("click", function (ev) {
    if (ev.target === reviewBackdrop) closeReview();
  });

  /* Padding applied around the face bbox before drawing the corner
     markers, so the lines sit outside the face instead of on top of it
     (a fraction of the bbox's own size, both axes). */
  var FACE_BOX_PAD = 0.12;

  function paddedBox(bbox, iw, ih) {
    var w = bbox[2] - bbox[0];
    var h = bbox[3] - bbox[1];
    var px = w * FACE_BOX_PAD;
    var py = h * FACE_BOX_PAD;
    return [
      Math.max(0, bbox[0] - px),
      Math.max(0, bbox[1] - py),
      Math.min(iw || bbox[2] + px, bbox[2] + px),
      Math.min(ih || bbox[3] + py, bbox[3] + py),
    ];
  }

  function makeCornerBox() {
    var box = document.createElement("div");
    box.className = "review-face-box";
    ["tl", "tr", "bl", "br"].forEach(function (pos) {
      var corner = document.createElement("div");
      corner.className = "corner " + pos;
      box.appendChild(corner);
    });
    return box;
  }

  function renderFaceBox(row) {
    var wrap = document.createElement("div");
    wrap.className = "review-face";
    var imgwrap = document.createElement("div");
    imgwrap.className = "review-face-imgwrap";
    imgwrap.setAttribute("role", "button");
    imgwrap.setAttribute("tabindex", "0");
    imgwrap.setAttribute("aria-label", "Zoom in on this face");
    var img = document.createElement("img");
    img.src = "/media/" + row.item_id + "/thumb?size=400";
    var box = makeCornerBox();
    imgwrap.appendChild(img);
    imgwrap.appendChild(box);
    wrap.appendChild(imgwrap);
    function place() {
      var iw = row.img_w || img.naturalWidth;
      var ih = row.img_h || img.naturalHeight;
      if (!iw || !ih || !img.clientWidth) return;
      var sx = img.clientWidth / iw;
      var sy = img.clientHeight / ih;
      var pb = paddedBox(row.bbox, iw, ih);
      box.style.left = (pb[0] * sx) + "px";
      box.style.top = (pb[1] * sy) + "px";
      box.style.width = ((pb[2] - pb[0]) * sx) + "px";
      box.style.height = ((pb[3] - pb[1]) * sy) + "px";
    }
    img.addEventListener("load", place);
    function openZoom() { openFaceZoom(row); }
    imgwrap.addEventListener("click", openZoom);
    imgwrap.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openZoom(); }
    });
    var zoomHint = document.createElement("div");
    zoomHint.className = "review-face-zoom-hint";
    zoomHint.textContent = "Tap photo to zoom in";
    wrap.appendChild(zoomHint);
    var detach = document.createElement("button");
    detach.type = "button";
    detach.textContent = "Not this person";
    detach.addEventListener("click", function () {
      fetch("/faces/" + row.face_id + "/reassign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_id: null }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("failed");
          showToast("Removed from this person.", "ok");
          openReview(reviewPerson); loadPeople(); loadStats();
        })
        .catch(function () { showToast("Could not update.", "err"); });
    });
    wrap.appendChild(detach);
    return wrap;
  }

  /* ---- Face zoom: crop-and-enlarge the face region on a canvas so an
     elderly user can see clearly who it is. Corner markers are redrawn
     on the canvas so they still show in the zoomed view. ---- */
  var faceZoomBackdrop = document.getElementById("face-zoom-backdrop");
  var faceZoomClose = document.getElementById("face-zoom-close");
  var faceZoomCanvas = document.getElementById("face-zoom-canvas");

  function closeFaceZoom() { faceZoomBackdrop.classList.remove("show"); }
  faceZoomClose.addEventListener("click", closeFaceZoom);
  faceZoomBackdrop.addEventListener("click", function (ev) {
    if (ev.target === faceZoomBackdrop) closeFaceZoom();
  });

  function openFaceZoom(row) {
    var img = new Image();
    img.onload = function () {
      var iw = row.img_w || img.naturalWidth;
      var ih = row.img_h || img.naturalHeight;
      var pb = paddedBox(row.bbox, iw, ih);
      var cropW = Math.max(1, pb[2] - pb[0]);
      var cropH = Math.max(1, pb[3] - pb[1]);
      // Enlarge the crop to a comfortably large canvas.
      var targetW = Math.min(900, Math.max(400, cropW * 4));
      var scale = targetW / cropW;
      var targetH = cropH * scale;
      faceZoomCanvas.width = targetW;
      faceZoomCanvas.height = targetH;
      var ctx = faceZoomCanvas.getContext("2d");
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(
        img,
        pb[0], pb[1], cropW, cropH,
        0, 0, targetW, targetH
      );
      // Redraw the face's own corner markers, scaled into crop space.
      var bx = (row.bbox[0] - pb[0]) * scale;
      var by = (row.bbox[1] - pb[1]) * scale;
      var bw = (row.bbox[2] - row.bbox[0]) * scale;
      var bh = (row.bbox[3] - row.bbox[1]) * scale;
      var cl = Math.min(bw, bh) * 0.22;
      ctx.strokeStyle = "#b8bb26";
      ctx.lineWidth = 5;
      ctx.lineCap = "square";
      function corner(x0, y0, dx, dy) {
        ctx.beginPath();
        ctx.moveTo(x0, y0 + dy * cl);
        ctx.lineTo(x0, y0);
        ctx.lineTo(x0 + dx * cl, y0);
        ctx.stroke();
      }
      corner(bx, by, 1, 1);
      corner(bx + bw, by, -1, 1);
      corner(bx, by + bh, 1, -1);
      corner(bx + bw, by + bh, -1, -1);
      faceZoomBackdrop.classList.add("show");
    };
    img.src = "/media/" + row.item_id + "/thumb?size=1200";
  }

  function openReview(person) {
    reviewPerson = person;
    reviewTitle.textContent = "Review: " + (person.name || "Unnamed person");
    reviewName.value = person.name || "";
    reviewMergeInput.value = "";
    reviewBackdrop.classList.add("show");
    reviewMergeSuggestions.innerHTML = "";
    peopleCache.forEach(function (p) {
      if (p.id !== person.id && p.name) {
        var opt = document.createElement("option");
        opt.value = p.name;
        reviewMergeSuggestions.appendChild(opt);
      }
    });
    reviewGrid.textContent = "Loading...";
    fetch("/people/" + person.id + "/photos")
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        reviewGrid.innerHTML = "";
        (rows || []).forEach(function (row) {
          reviewGrid.appendChild(renderFaceBox(row));
        });
        if (!rows || !rows.length) reviewGrid.textContent = "No photos.";
      })
      .catch(function () { reviewGrid.textContent = "Could not load photos."; });
  }

  reviewNameBtn.addEventListener("click", function () {
    if (!reviewPerson) return;
    var newName = reviewName.value.trim();
    if (!newName) { showToast("Type a name first.", "err"); return; }
    postName(reviewPerson.id, newName)
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        showToast('Named "' + newName + '".', "ok");
        reviewPerson.name = newName;
        reviewTitle.textContent = "Review: " + newName;
        loadPeople(); loadStats(); refreshPersonDatalists();
      })
      .catch(function () { showToast("Could not save name.", "err"); });
  });

  reviewMergeBtn.addEventListener("click", function () {
    if (!reviewPerson) return;
    var targetName = reviewMergeInput.value.trim();
    if (!targetName) { showToast("Choose a person to merge into.", "err"); return; }
    var target = null;
    peopleCache.forEach(function (p) {
      if (p.name && p.name.toLowerCase() === targetName.toLowerCase()
          && p.id !== reviewPerson.id) target = p;
    });
    if (!target) { showToast("No matching person to merge into.", "err"); return; }
    fetch("/people/" + target.id + "/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from_id: reviewPerson.id }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        showToast('Merged into "' + target.name + '".', "ok");
        closeReview(); loadPeople(); loadStats();
      })
      .catch(function () { showToast("Could not merge.", "err"); });
  });

  loadPeople();

  pagePrev.addEventListener("click", function () {
    if (state.page > 1) {
      state.page -= 1;
      loadGrid();
    }
  });
  pageNext.addEventListener("click", function () {
    if (state.hasNext) {
      state.page += 1;
      loadGrid();
    }
  });

  /* ---- Bulk actions ---- */
  function selectedIds() {
    return Object.keys(state.selected);
  }

  bulkSoftDelete.addEventListener("click", function () {
    var ids = selectedIds();
    if (ids.length === 0) return;
    if (!window.confirm("Delete " + ids.length + " item(s)? "
      + "This is recoverable (goes to trash).")) return;
    fetch("/media/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids, permanent: false }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        showToast(
          "Deleted " + (data.deleted || []).length + " item(s).", "ok"
        );
        state.selected = {};
        updateBulkBar();
        loadStats();
        loadGrid();
      })
      .catch(function () { showToast("Bulk delete failed.", "err"); });
  });

  bulkHardDelete.addEventListener("click", function () {
    var ids = selectedIds();
    if (ids.length === 0) return;
    if (!window.confirm("Permanently delete " + ids.length + " item(s)? "
      + "This CANNOT be undone.")) return;
    if (!window.confirm("Are you sure? This will erase " + ids.length
      + " file(s) forever.")) return;
    fetch("/media/bulk-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids, permanent: true }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        showToast(
          "Permanently deleted " + (data.deleted || []).length
          + " item(s).", "ok"
        );
        state.selected = {};
        updateBulkBar();
        loadStats();
        loadGrid();
      })
      .catch(function () { showToast("Bulk delete failed.", "err"); });
  });

  /* ---- Remembered slideshow target ----
     Like "Add to playlist" on a music app: once the user picks a
     slideshow, later "Add to slideshow" taps go straight there without
     reopening the picker. Deliberately NOT persisted (plain var, resets
     on reload) and times out after a few minutes so a stale target never
     silently receives photos. */
  var REMEMBER_PLAYLIST_TIMEOUT_MS = 5 * 60 * 1000;
  var rememberedPlaylistName = null;
  var rememberedPlaylistAt = 0;

  function rememberPlaylist(name) {
    rememberedPlaylistName = name;
    rememberedPlaylistAt = Date.now();
  }

  function getRememberedPlaylist() {
    if (!rememberedPlaylistName) return null;
    if (Date.now() - rememberedPlaylistAt > REMEMBER_PLAYLIST_TIMEOUT_MS) {
      rememberedPlaylistName = null;
      return null;
    }
    return rememberedPlaylistName;
  }

  /* Small fixed bottom bar confirming a direct add, with a clearly
     labeled way to change the remembered target for next time. */
  var changeBar = null;
  var changeBarHideTimer = null;

  function hideChangeBar() {
    if (changeBarHideTimer) {
      window.clearTimeout(changeBarHideTimer);
      changeBarHideTimer = null;
    }
    if (changeBar && changeBar.parentNode) {
      changeBar.parentNode.removeChild(changeBar);
    }
    changeBar = null;
  }

  function showChangeBar(message, onChangeSlideshow) {
    hideChangeBar();
    changeBar = document.createElement("div");
    changeBar.setAttribute("role", "status");
    changeBar.style.position = "fixed";
    changeBar.style.left = "0";
    changeBar.style.right = "0";
    changeBar.style.bottom = "0";
    changeBar.style.zIndex = "600";
    changeBar.style.display = "flex";
    changeBar.style.alignItems = "center";
    changeBar.style.justifyContent = "center";
    changeBar.style.flexWrap = "wrap";
    changeBar.style.gap = "0.7rem";
    changeBar.style.padding = "0.7rem 1rem";
    changeBar.style.background = "var(--panel)";
    changeBar.style.borderTop = "2px solid var(--aqua)";
    changeBar.style.boxShadow = "0 -2px 12px rgba(0, 0, 0, 0.35)";

    var text = document.createElement("span");
    text.textContent = message;
    text.style.color = "var(--text)";
    text.style.fontSize = "0.9rem";
    text.style.fontWeight = "700";
    changeBar.appendChild(text);

    var changeBtn = document.createElement("button");
    changeBtn.type = "button";
    changeBtn.textContent = "Change slideshow";
    changeBtn.style.minHeight = "44px";
    changeBtn.style.padding = "0 1.1rem";
    changeBtn.style.fontSize = "0.85rem";
    changeBtn.style.fontWeight = "700";
    changeBtn.style.borderRadius = "6px";
    changeBtn.style.border = "1px solid var(--aqua)";
    changeBtn.style.background = "transparent";
    changeBtn.style.color = "var(--aqua)";
    changeBtn.style.cursor = "pointer";
    changeBtn.addEventListener("click", function () {
      hideChangeBar();
      onChangeSlideshow();
    });
    changeBar.appendChild(changeBtn);

    var dismissBtn = document.createElement("button");
    dismissBtn.type = "button";
    dismissBtn.textContent = "Dismiss";
    dismissBtn.setAttribute("aria-label", "Dismiss");
    dismissBtn.style.minHeight = "44px";
    dismissBtn.style.padding = "0 0.9rem";
    dismissBtn.style.fontSize = "0.85rem";
    dismissBtn.style.borderRadius = "6px";
    dismissBtn.style.border = "1px solid var(--border)";
    dismissBtn.style.background = "transparent";
    dismissBtn.style.color = "var(--muted)";
    dismissBtn.style.cursor = "pointer";
    dismissBtn.addEventListener("click", hideChangeBar);
    changeBar.appendChild(dismissBtn);

    document.body.appendChild(changeBar);
    changeBarHideTimer = window.setTimeout(hideChangeBar, 6000);
  }

  function bulkAddToPlaylist(name, ids) {
    fetch("/playlists/" + encodeURIComponent(name) + "/items/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        rememberPlaylist(name);
        bulkPlaylistPicker.innerHTML = "";
        loadPlaylists();
        showChangeBar(
          "Added " + ids.length + " to \\"" + name + "\\".",
          function () {
            var freshIds = selectedIds();
            if (freshIds.length === 0) {
              showToast("Select one or more photos first.", "err");
              return;
            }
            renderPlaylistPicker(bulkPlaylistPicker, function (pickedName) {
              bulkAddToPlaylist(pickedName, freshIds);
            });
          }
        );
      })
      .catch(function () { showToast("Could not add to slideshow.", "err"); });
  }

  bulkAddPlaylist.addEventListener("click", function () {
    var ids = selectedIds();
    if (ids.length === 0) {
      showToast("Select one or more photos first.", "err");
      return;
    }
    var remembered = getRememberedPlaylist();
    if (remembered) {
      bulkAddToPlaylist(remembered, ids);
      return;
    }
    renderPlaylistPicker(bulkPlaylistPicker, function (name) {
      bulkAddToPlaylist(name, ids);
    });
  });

  /* ---- Reusable playlist picker (existing list + create-new) ---- */
  function renderPlaylistPicker(container, onPick) {
    container.innerHTML = "";
    // The container itself is hidden until it holds a picker; reveal it.
    container.classList.add("show");
    var wrap = document.createElement("div");
    wrap.className = "show";
    wrap.style.marginTop = "0.5rem";
    wrap.style.background = "var(--bg-alt)";
    wrap.style.border = "1px solid var(--border)";
    wrap.style.borderRadius = "6px";
    wrap.style.padding = "0.7rem";

    var existing = document.createElement("div");
    existing.className = "pp-existing";
    fetch("/playlists")
      .then(function (r) { return r.json(); })
      .then(function (playlists) {
        if (playlists.length === 0) {
          var none = document.createElement("div");
          none.style.color = "var(--muted)";
          none.style.fontSize = "0.8rem";
          none.textContent = "No slideshows yet -- create one below.";
          existing.appendChild(none);
        }
        playlists.forEach(function (pl) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "pp-item";
          btn.textContent = pl.name + " (" + pl.count + ")";
          btn.addEventListener("click", function () { onPick(pl.name); });
          existing.appendChild(btn);
        });
      })
      .catch(function () {});
    wrap.appendChild(existing);

    var newRow = document.createElement("div");
    newRow.className = "pp-new-row";
    var nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "New slideshow name";
    var createBtn = document.createElement("button");
    createBtn.type = "button";
    createBtn.className = "pp-create";
    createBtn.textContent = "Create + add";
    createBtn.addEventListener("click", function () {
      var name = nameInput.value.trim();
      if (!name) return;
      fetch("/playlists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name }),
      })
        .then(function (r) {
          if (r.ok || r.status === 409) {
            onPick(name);
          } else {
            showToast("Could not create slideshow.", "err");
          }
        })
        .catch(function () { showToast("Could not create slideshow.", "err"); });
    });
    newRow.appendChild(nameInput);
    newRow.appendChild(createBtn);
    wrap.appendChild(newRow);

    container.appendChild(wrap);
  }

  /* ---- Programmed slideshows section ---- */
  var playlistsList = document.getElementById("playlists-list");
  var playlistsEmpty = document.getElementById("playlists-empty");
  var newPlaylistName = document.getElementById("new-playlist-name");
  var newPlaylistBtn = document.getElementById("new-playlist-btn");

  function loadPlaylists() {
    fetch("/playlists")
      .then(function (r) { return r.json(); })
      .then(function (playlists) {
        playlistsList.innerHTML = "";
        playlistsEmpty.style.display = playlists.length === 0 ? "block" : "none";
        playlists.forEach(function (pl) {
          var row = document.createElement("div");
          row.className = "playlist-row";

          var name = document.createElement("span");
          name.className = "pl-name";
          name.textContent = pl.name;
          row.appendChild(name);

          var count = document.createElement("span");
          count.className = "pl-count";
          count.textContent = pl.count + " item(s)";
          row.appendChild(count);

          var actions = document.createElement("div");
          actions.className = "pl-actions";

          var playBtn = document.createElement("button");
          playBtn.type = "button";
          playBtn.className = "pl-play";
          playBtn.textContent = "Play on display";
          playBtn.addEventListener("click", function () {
            runControl(
              playBtn,
              "/control/playlist/" + encodeURIComponent(pl.name) +
                "?loop=" + isLoop(),
              "POST",
              undefined,
              "...",
              loopNote("Playing slideshow \\"" + pl.name + "\\".")
            );
          });
          actions.appendChild(playBtn);

          var delBtn = document.createElement("button");
          delBtn.type = "button";
          delBtn.className = "pl-delete";
          delBtn.textContent = "Delete";
          delBtn.addEventListener("click", function () {
            if (!window.confirm("Delete slideshow \\"" + pl.name + "\\"? "
              + "The photos themselves are not deleted.")) return;
            fetch("/playlists/" + encodeURIComponent(pl.name), {
              method: "DELETE",
            })
              .then(function (r) {
                if (r.ok) {
                  showToast("Deleted slideshow \\"" + pl.name + "\\".", "ok");
                  loadPlaylists();
                } else {
                  showToast("Could not delete slideshow.", "err");
                }
              })
              .catch(function () {
                showToast("Could not delete slideshow.", "err");
              });
          });
          actions.appendChild(delBtn);

          row.appendChild(actions);
          playlistsList.appendChild(row);
        });
      })
      .catch(function () {
        playlistsEmpty.style.display = "block";
        playlistsEmpty.textContent = "Could not load slideshows.";
      });
  }

  newPlaylistBtn.addEventListener("click", function () {
    var name = newPlaylistName.value.trim();
    if (!name) return;
    fetch("/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name }),
    })
      .then(function (r) {
        if (r.ok) {
          showToast("Created slideshow \\"" + name + "\\".", "ok");
          newPlaylistName.value = "";
          loadPlaylists();
        } else if (r.status === 409) {
          showToast("A slideshow with that name already exists.", "err");
        } else {
          showToast("Could not create slideshow.", "err");
        }
      })
      .catch(function () { showToast("Could not create slideshow.", "err"); });
  });

  /* ---- Modal / lightbox ---- */
  var modalBackdrop = document.getElementById("modal-backdrop");
  var modalCard = document.getElementById("modal-card");
  var modalClose = document.getElementById("modal-close");
  var modalImg = document.getElementById("modal-img");
  var modalVideo = document.getElementById("modal-video");
  var modalTitle = document.getElementById("modal-title");
  var modalDetails = document.getElementById("modal-details");
  var actShow = document.getElementById("act-show");
  var actAddPlaylist = document.getElementById("act-add-playlist");
  var actSoftDelete = document.getElementById("act-soft-delete");
  var actHardDelete = document.getElementById("act-hard-delete");
  var modalPlaylistPicker = document.getElementById("playlist-picker");
  var orientActions = document.getElementById("orient-actions");
  var actRotateLeft = document.getElementById("act-rotate-left");
  var actRotateRight = document.getElementById("act-rotate-right");
  var actFlipH = document.getElementById("act-flip-h");
  var actFlipV = document.getElementById("act-flip-v");

  /* Cache-bust an item's image/thumb URLs off its content digest, so a
     rewritten file (rotate/flip) is never served stale from the browser's
     HTTP cache -- the URL path is unchanged but the digest suffix is not. */
  function mediaVersionParam(item) {
    var sha = item && item.meta && item.meta.sha256;
    return sha ? ("v=" + sha.slice(0, 12)) : "";
  }

  var modalItem = null;

  function fmtDate(iso) {
    if (!iso) return null;
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, {
        year: "numeric", month: "long", day: "numeric",
        hour: "numeric", minute: "2-digit",
      });
    } catch (e) {
      return iso;
    }
  }

  function addDetail(dt, dd) {
    var t = document.createElement("dt");
    t.textContent = dt;
    var d = document.createElement("dd");
    d.textContent = dd;
    modalDetails.appendChild(t);
    modalDetails.appendChild(d);
  }

  function addDetailHtml(dt, html) {
    var t = document.createElement("dt");
    t.textContent = dt;
    var d = document.createElement("dd");
    d.innerHTML = html;
    modalDetails.appendChild(t);
    modalDetails.appendChild(d);
  }

  function openModal(itemId) {
    modalPlaylistPicker.className = "";
    modalPlaylistPicker.innerHTML = "";
    modalImg.src = "";
    modalImg.style.display = "";
    modalVideo.pause();
    modalVideo.removeAttribute("src");
    modalVideo.load();
    modalVideo.className = "";
    modalTitle.textContent = "Loading...";
    modalDetails.innerHTML = "";
    modalBackdrop.className = "show";

    fetch("/media/" + itemId + "/info")
      .then(function (r) { return r.json(); })
      .then(function (item) {
        modalItem = item;
        modalTitle.textContent = item.filename;
        orientActions.style.display = item.kind === "video" ? "none" : "";
        if (item.kind === "video") {
          modalImg.style.display = "none";
          modalVideo.className = "show";
          modalVideo.src = "/media/" + item.id;
        } else {
          var v = mediaVersionParam(item);
          modalVideo.className = "";
          modalImg.style.display = "";
          modalImg.src = "/media/" + item.id + (v ? "?" + v : "");
          modalImg.alt = item.filename;
        }

        modalDetails.innerHTML = "";
        addDetail("Kind", item.kind);
        var meta = item.meta || {};
        addDetail(
          "Date taken",
          meta.taken_at ? fmtDate(meta.taken_at) : "Unknown"
        );
        addDetail("Camera", meta.camera_model || "Unknown");
        if (meta.width && meta.height) {
          addDetail("Dimensions", meta.width + " x " + meta.height);
        }
        if (item.kind === "video" && meta.duration_s) {
          addDetail("Duration", Math.round(meta.duration_s) + " s");
        }
        if (meta.lat != null && meta.lon != null) {
          var url = "https://www.openstreetmap.org/?mlat=" + meta.lat
            + "&mlon=" + meta.lon;
          addDetailHtml(
            "Location",
            meta.lat.toFixed(5) + ", " + meta.lon.toFixed(5)
            + ' (<a href="' + url + '" target="_blank" '
            + 'rel="noopener">view on map</a>)'
          );
        } else {
          addDetail("Location", "Unknown");
        }
        addDetail("Server path", item.server_path);
        addDetail("SHA-256", meta.sha256 || "Unknown");
        addDetail("Ingested", fmtDate(meta.ingest_at) || "Unknown");
      })
      .catch(function () {
        modalTitle.textContent = "Could not load details.";
      });
  }

  function closeModal() {
    modalBackdrop.className = "";
    modalItem = null;
    modalVideo.pause();
  }

  modalClose.addEventListener("click", closeModal);
  modalBackdrop.addEventListener("click", function (e) {
    if (e.target === modalBackdrop) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modalBackdrop.className.indexOf("show") !== -1) {
      closeModal();
    }
  });

  actShow.addEventListener("click", function () {
    if (!modalItem) return;
    runControl(
      actShow,
      "/control/show/" + modalItem.id,
      "POST",
      undefined,
      "...",
      "Now showing \\"" + modalItem.filename + "\\" on the display."
    );
  });

  function actAddToPlaylist(name, itemId, filename) {
    fetch("/playlists/" + encodeURIComponent(name) + "/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        rememberPlaylist(name);
        modalPlaylistPicker.innerHTML = "";
        loadPlaylists();
        showChangeBar(
          "Added \\"" + filename + "\\" to \\"" + name + "\\".",
          function () {
            renderPlaylistPicker(modalPlaylistPicker, function (pickedName) {
              actAddToPlaylist(pickedName, itemId, filename);
            });
          }
        );
      })
      .catch(function () { showToast("Could not add to slideshow.", "err"); });
  }

  actAddPlaylist.addEventListener("click", function () {
    if (!modalItem) return;
    var itemId = modalItem.id;
    var filename = modalItem.filename;
    var remembered = getRememberedPlaylist();
    if (remembered) {
      actAddToPlaylist(remembered, itemId, filename);
      return;
    }
    renderPlaylistPicker(modalPlaylistPicker, function (name) {
      actAddToPlaylist(name, itemId, filename);
    });
  });

  function setOrientButtonsDisabled(disabled) {
    actRotateLeft.disabled = disabled;
    actRotateRight.disabled = disabled;
    actFlipH.disabled = disabled;
    actFlipV.disabled = disabled;
  }

  function doTransform(body) {
    if (!modalItem) return;
    var itemId = modalItem.id;
    setOrientButtonsDisabled(true);
    fetch("/media/" + itemId + "/transform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("transform failed");
        return r.json();
      })
      .then(function (updated) {
        modalItem = updated;
        var v = mediaVersionParam(updated);
        modalImg.src = "/media/" + itemId + (v ? "?" + v : "");
        showToast("Photo updated.", "ok");
        setOrientButtonsDisabled(false);
        loadGrid();
      })
      .catch(function () {
        showToast("Could not update the photo.", "err");
        setOrientButtonsDisabled(false);
      });
  }

  actRotateLeft.addEventListener("click", function () {
    doTransform({ rotate: -90 });
  });
  actRotateRight.addEventListener("click", function () {
    doTransform({ rotate: 90 });
  });
  actFlipH.addEventListener("click", function () {
    doTransform({ flip: "h" });
  });
  actFlipV.addEventListener("click", function () {
    doTransform({ flip: "v" });
  });

  actSoftDelete.addEventListener("click", function () {
    if (!modalItem) return;
    if (!window.confirm("Delete \\"" + modalItem.filename + "\\"? "
      + "This is recoverable (goes to trash).")) return;
    fetch("/media/" + modalItem.id, { method: "DELETE" })
      .then(function (r) {
        if (r.ok) {
          showToast("Deleted \\"" + modalItem.filename + "\\".", "ok");
          closeModal();
          loadStats();
          loadGrid();
        } else {
          showToast("Could not delete item.", "err");
        }
      })
      .catch(function () { showToast("Could not delete item.", "err"); });
  });

  actHardDelete.addEventListener("click", function () {
    if (!modalItem) return;
    if (!window.confirm("Permanently delete \\"" + modalItem.filename
      + "\\"? This CANNOT be undone.")) return;
    if (!window.confirm("Are you sure? The file will be erased forever."))
      return;
    fetch("/media/" + modalItem.id + "?permanent=true", { method: "DELETE" })
      .then(function (r) {
        if (r.ok) {
          showToast(
            "Permanently deleted \\"" + modalItem.filename + "\\".", "ok"
          );
          closeModal();
          loadStats();
          loadGrid();
        } else {
          showToast("Could not delete item.", "err");
        }
      })
      .catch(function () { showToast("Could not delete item.", "err"); });
  });

  /* ---- Recycle bin ---- */
  var trashToggleBtn = document.getElementById("trash-toggle-btn");
  var trashPanel = document.getElementById("trash-panel");
  var trashGrid = document.getElementById("trash-grid");
  var trashEmpty = document.getElementById("trash-empty");
  var trashLoaded = false;

  function renderTrashTile(item) {
    var tile = document.createElement("div");
    tile.className = "trash-tile";
    var img = document.createElement("img");
    img.src = "/media/" + item.id + "/thumb?size=160";
    img.alt = item.filename;
    tile.appendChild(img);
    var actions = document.createElement("div");
    actions.className = "trash-actions";

    var restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.textContent = "Restore";
    restoreBtn.addEventListener("click", function () {
      restoreBtn.disabled = true;
      fetch("/media/" + item.id + "/restore", { method: "POST" })
        .then(function (r) {
          if (r.ok) {
            showToast("Restored \\"" + item.filename + "\\".", "ok");
            loadTrash();
            loadStats();
            loadGrid();
          } else {
            showToast("Could not restore item.", "err");
            restoreBtn.disabled = false;
          }
        })
        .catch(function () {
          showToast("Could not restore item.", "err");
          restoreBtn.disabled = false;
        });
    });

    var deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.textContent = "Delete forever";
    deleteBtn.addEventListener("click", function () {
      if (!window.confirm("Permanently delete \\"" + item.filename
        + "\\"? This CANNOT be undone.")) return;
      deleteBtn.disabled = true;
      fetch("/media/" + item.id + "?permanent=true", { method: "DELETE" })
        .then(function (r) {
          if (r.ok) {
            showToast("Permanently deleted \\"" + item.filename + "\\".", "ok");
            loadTrash();
          } else {
            showToast("Could not delete item.", "err");
            deleteBtn.disabled = false;
          }
        })
        .catch(function () {
          showToast("Could not delete item.", "err");
          deleteBtn.disabled = false;
        });
    });

    actions.appendChild(restoreBtn);
    actions.appendChild(deleteBtn);
    tile.appendChild(actions);
    return tile;
  }

  function loadTrash() {
    fetch("/media/trash?page=1&page_size=100")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        trashGrid.innerHTML = "";
        var items = data.items || [];
        trashEmpty.style.display = items.length ? "none" : "block";
        items.forEach(function (item) {
          trashGrid.appendChild(renderTrashTile(item));
        });
      })
      .catch(function () { showToast("Could not load recycle bin.", "err"); });
  }

  trashToggleBtn.addEventListener("click", function () {
    var show = trashPanel.className.indexOf("show") === -1;
    trashPanel.className = show ? "show" : "";
    trashToggleBtn.textContent = show ? "Hide recycle bin" : "Show recycle bin";
    if (show && !trashLoaded) {
      trashLoaded = true;
      loadTrash();
    } else if (show) {
      loadTrash();
    }
  });

  /* ---- Role-specific UI: hide server-only features when hosted on the
     display itself (multi-display selection, year-shortcut play-query, and
     programmed slideshows all live server-side only). ---- */
  if (MALMBERG_ROLE === "display") {
    var displaySelectRow = document.getElementById("display-select-row");
    if (displaySelectRow) displaySelectRow.style.display = "none";
    // The whole "show on the frame" group (year/place/person play shortcuts)
    // uses /control/play-query, a server-only proxy path; hide it on the
    // display's own page. The library search boxes and stats chips stay.
    var frameFilterGroup = document.getElementById("frame-filter-group");
    if (frameFilterGroup) frameFilterGroup.style.display = "none";
    var playlistsSection = document.getElementById("playlists-section");
    if (playlistsSection) playlistsSection.style.display = "none";
    var bulkAddPlaylistBtn = document.getElementById("bulk-add-playlist");
    if (bulkAddPlaylistBtn) bulkAddPlaylistBtn.style.display = "none";
    var actAddPlaylistBtn = document.getElementById("act-add-playlist");
    if (actAddPlaylistBtn) actAddPlaylistBtn.style.display = "none";
  }

  /* ---- Cloud photos: per-provider status, sync-now, and a guarded cleanup
     flow (dry-run count -> strong confirm -> confirmed delete). Status and
     deletable are read-only and proxied in both roles; sync and delete are
     server-only writes, so their buttons are omitted on a display. ---- */
  var cloudProviders = document.getElementById('cloud-providers');
  var cloudEmpty = document.getElementById('cloud-empty');

  function cloudFmtTime(iso) {
    if (!iso) return 'never';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString();
  }

  function loadCloud() {
    if (!cloudProviders) return;
    fetch('/cloud/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var providers = (data && data.providers) || [];
        cloudProviders.innerHTML = '';
        cloudEmpty.style.display = providers.length === 0 ? 'block' : 'none';
        providers.forEach(function (p) { cloudProviders.appendChild(cloudCard(p)); });
      })
      .catch(function () {
        cloudEmpty.style.display = 'block';
        cloudEmpty.textContent = 'Could not load cloud status.';
      });
  }

  function cloudStat(label, value) {
    var wrap = document.createElement('div');
    wrap.className = 'cloud-stat';
    var v = document.createElement('div');
    v.className = 'cloud-stat-val';
    v.textContent = String(value);
    var l = document.createElement('div');
    l.className = 'cloud-stat-lbl';
    l.textContent = label;
    wrap.appendChild(v);
    wrap.appendChild(l);
    return wrap;
  }

  function cloudCard(p) {
    var card = document.createElement('div');
    card.className = 'cloud-card';

    var head = document.createElement('div');
    head.className = 'cloud-card-head';
    var title = document.createElement('h3');
    title.textContent = p.name === 'google_photos' ? 'Google Photos'
      : (p.name === 'icloud' ? 'iCloud' : p.name);
    head.appendChild(title);
    var badge = document.createElement('span');
    badge.className = 'cloud-badge ' + (p.configured ? 'ok' : 'off');
    badge.textContent = p.configured ? 'Connected'
      : (p.enabled ? 'Not set up' : 'Disabled');
    head.appendChild(badge);
    card.appendChild(head);

    var meta = document.createElement('div');
    meta.className = 'domain-sub';
    meta.textContent = 'Last sync: ' + cloudFmtTime(p.last_sync_at)
      + (p.last_error ? (' (last error: ' + p.last_error + ')') : '');
    card.appendChild(meta);

    var grid = document.createElement('div');
    grid.className = 'cloud-stats';
    grid.appendChild(cloudStat('Tracked', p.tracked));
    grid.appendChild(cloudStat('Verified', p.verified));
    grid.appendChild(cloudStat('Deleted from cloud', p.deleted_from_cloud));
    card.appendChild(grid);

    if (MALMBERG_ROLE !== 'display') {
      var actions = document.createElement('div');
      actions.className = 'controls';
      var syncBtn = document.createElement('button');
      syncBtn.type = 'button';
      syncBtn.textContent = 'Sync now';
      syncBtn.addEventListener('click', function () { cloudSyncNow(p.name); });
      actions.appendChild(syncBtn);
      var cleanBtn = document.createElement('button');
      cleanBtn.type = 'button';
      cleanBtn.className = 'danger-btn';
      cleanBtn.textContent = 'Clean up cloud';
      cleanBtn.addEventListener('click', function () { cloudCleanup(p.name); });
      actions.appendChild(cleanBtn);
      card.appendChild(actions);
    }
    return card;
  }

  function cloudSyncNow(name) {
    fetch('/cloud/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: name })
    })
      .then(function (r) { return r.json(); })
      .then(function (ack) {
        if (ack && ack.status === 'started') {
          showToast('Sync started; new photos appear as they arrive.', 'ok');
          setTimeout(loadCloud, 3000);
        } else if (ack && ack.status === 'no_providers') {
          showToast('No cloud providers are enabled.', 'err');
        } else {
          showToast('Could not start sync.', 'err');
        }
      })
      .catch(function () { showToast('Could not start sync.', 'err'); });
  }

  function cloudCleanup(name) {
    fetch('/cloud/deletable?provider=' + encodeURIComponent(name))
      .then(function (r) { return r.json(); })
      .then(function (page) {
        var n = (page && page.total) || 0;
        if (n === 0) {
          showToast('Nothing verified to clean up yet.', 'ok');
          return;
        }
        var msg = 'Permanently delete ' + n + ' photos from ' + name
          + '? They are verified to be saved on this server. '
          + 'This cannot be undone.';
        if (!window.confirm(msg)) return;
        fetch('/cloud/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: name, confirm: true })
        })
          .then(function (r) { return r.json(); })
          .then(function (report) {
            var deleted = (report && report.deleted) || 0;
            showToast('Deleted ' + deleted + ' from ' + name + '.', 'ok');
            loadCloud();
          })
          .catch(function () { showToast('Cleanup failed.', 'err'); });
      })
      .catch(function () { showToast('Could not check what is deletable.', 'err'); });
  }

  /* ---- Click-to-open help tips: tapping a "?" toggles the plain-language
     bubble next to that control; tapping anywhere else closes it. Replaces
     the old auto-popup walkthrough (dependency-free, no localStorage). ---- */
  document.addEventListener("click", function (e) {
    var tip = e.target.closest ? e.target.closest(".help-tip") : null;
    var open = document.querySelectorAll(".help.open");
    var i;
    if (tip) {
      e.preventDefault();
      var help = tip.parentNode;
      var wasOpen = help.classList.contains("open");
      for (i = 0; i < open.length; i++) open[i].classList.remove("open");
      if (!wasOpen) help.classList.add("open");
      return;
    }
    if (e.target.closest && e.target.closest(".help-bubble")) return;
    for (i = 0; i < open.length; i++) open[i].classList.remove("open");
  });

  loadStats();
  refreshStatus();
  loadGrid();
  loadCloud();
  if (MALMBERG_ROLE !== "display") {
    loadPlaylists();
    loadYearFilter();
  }
  setInterval(refreshStatus, 5000);
})();
</script>
</body>
</html>"""


def render_dashboard_html(role: DashboardRole = "server") -> str:
    """Render the single-source dashboard page for *role*.

    The Server and Display both serve this same page (see module docstring)
    so the two accessors never desync: only a JS-side ``MALMBERG_ROLE``
    constant differs, which switches whether slideshow controls target a
    server's /control/* proxy or a display's own /slideshow/* routes
    directly. Library/browse/recycle-bin calls use the same relative paths
    in both roles (the display proxies them to its paired server).
    """
    return _DASHBOARD_PAGE_TEMPLATE.replace("__MALMBERG_ROLE__", role)


DASHBOARD_PAGE_HTML = render_dashboard_html("server")
"""Pre-rendered server-role page, kept for callers that import the constant."""
