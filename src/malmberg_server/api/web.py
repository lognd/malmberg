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
  }
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
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.25rem 0.7rem;
    font-size: 0.78rem;
    color: var(--muted);
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
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.15rem 0.55rem;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .month-chip b { color: var(--aqua); font-weight: 700; }
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
  /* Year filter */
  #year-filter-row {
    margin-top: 0.9rem;
  }
  #year-filter-row .yf-label {
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
    min-height: 40px;
    min-width: 44px;
    padding: 0 0.7rem;
    font-size: 0.8rem;
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
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
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
    align-items: center;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 0.85rem;
    padding: 0.7rem 0.85rem;
    border-radius: 6px;
    border: 1px solid var(--aqua);
    background: var(--bg-alt);
  }
  #bulk-bar.show { display: flex; }
  #bulk-count {
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--aqua);
    margin-right: auto;
  }
  #bulk-bar button {
    min-height: 40px;
    padding: 0 0.8rem;
    font-size: 0.8rem;
    font-weight: 700;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
  }
  #bulk-hard-delete {
    color: var(--muted);
    border-color: transparent;
    background: transparent;
    font-weight: 400;
    font-size: 0.72rem;
    min-height: 32px;
    padding: 0 0.4rem;
    text-decoration: underline;
    opacity: 0.6;
  }
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
  <h1>Malmberg Dashboard</h1>

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
      <div id="year-filter-row">
        <div class="yf-label">Show a year on the frame</div>
        <div id="year-filter-buttons"></div>
      </div>
      <div id="control-hint">Controls disabled: set MALMBERG_DISPLAY_URL
      on the server to enable.</div>
      <div id="restart-row">
        <div class="yf-label">Trouble? Restart a device</div>
        <button id="btn-restart-display" type="button" class="danger-btn">
          Restart display
        </button>
        <button id="btn-restart-server" type="button" class="danger-btn">
          Restart server
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
          placeholder="Search by filename or year (e.g. 2006)">
        <button id="refresh-btn" type="button">Refresh</button>
        <button id="select-toggle-btn" type="button">Select</button>
      </div>
      <div id="results-summary"></div>
      <div id="bulk-bar">
        <span id="bulk-count">0 selected</span>
        <button id="bulk-select-all" type="button">Select all on page</button>
        <button id="bulk-add-playlist" type="button">Add to slideshow</button>
        <button id="bulk-soft-delete" type="button">Delete (recoverable)</button>
        <button id="bulk-hard-delete" type="button">Delete permanently</button>
        <button id="bulk-clear" type="button">Clear selection</button>
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
      <button id="trash-toggle-btn" type="button">Show recycle bin</button>
      <div id="trash-panel">
        <div id="trash-empty">Recycle bin is empty.</div>
        <div class="grid" id="trash-grid"></div>
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
          var chip = document.createElement("span");
          chip.className = "year-chip";
          chip.innerHTML = "<b></b> " + year;
          chip.querySelector("b").textContent = String(data.by_year[year]);
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
            var chip = document.createElement("span");
            chip.className = "month-chip";
            chip.innerHTML = "<b></b> ";
            chip.querySelector("b").textContent = String(byMonthData[ym]);
            chip.appendChild(
              document.createTextNode(MONTH_NAMES[mi] || ym.slice(5, 7))
            );
            monthsEl.appendChild(chip);
          });
          group.appendChild(yearEl);
          group.appendChild(monthsEl);
          byMonth.appendChild(group);
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
      var img = document.createElement("img");
      img.src = "/media/" + itemId + "/thumb?size=160";
      img.alt = "Now showing";
      nowThumbWrap.appendChild(img);
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
          runControl(allBtn, "/control/play-all", "POST", undefined,
            "...", "Now playing the whole library.");
        });
        yearFilterButtons.appendChild(allBtn);
        Object.keys(data.by_year || {}).sort().forEach(function (year) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = year;
          btn.addEventListener("click", function () {
            runControl(
              btn,
              "/control/play-query?q=" + encodeURIComponent(year),
              "POST",
              undefined,
              "...",
              "Now showing " + year + "."
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
    page: 1, q: "", hasNext: false, total: 0, items: [],
    selectMode: false, selected: {},
  };
  var searchDebounce = null;

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
    selectToggleBtn.textContent = state.selectMode ? "Done selecting" : "Select";
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
      img.src = "/media/" + item.id + "/thumb";
      img.alt = item.filename;
      img.loading = "lazy";
      tile.appendChild(img);

      if (state.selectMode) {
        var mark = document.createElement("div");
        mark.className = "select-mark";
        mark.textContent = selected ? "\\u2713" : "";
        tile.appendChild(mark);
        tile.addEventListener("click", function () {
          toggleItemSelected(item.id);
        });
      } else {
        tile.addEventListener("click", function () { openModal(item.id); });
      }

      grid.appendChild(tile);
    });
  }

  function loadGrid() {
    var params = "page=" + state.page + "&page_size=" + PAGE_SIZE +
      "&sort=recent";
    if (state.q) params += "&q=" + encodeURIComponent(state.q);

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
    }, 350);
  });

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

  bulkAddPlaylist.addEventListener("click", function () {
    var ids = selectedIds();
    if (ids.length === 0) return;
    renderPlaylistPicker(bulkPlaylistPicker, function (name) {
      fetch("/playlists/" + encodeURIComponent(name) + "/items/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ids }),
      })
        .then(function (r) { return r.json(); })
        .then(function () {
          showToast(
            "Added " + ids.length + " item(s) to \\"" + name + "\\".", "ok"
          );
          bulkPlaylistPicker.innerHTML = "";
          loadPlaylists();
        })
        .catch(function () { showToast("Could not add to slideshow.", "err"); });
    });
  });

  /* ---- Reusable playlist picker (existing list + create-new) ---- */
  function renderPlaylistPicker(container, onPick) {
    container.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.id = "playlist-picker show";
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
              "/control/playlist/" + encodeURIComponent(pl.name),
              "POST",
              undefined,
              "...",
              "Playing slideshow \\"" + pl.name + "\\" on the display."
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
        if (item.kind === "video") {
          modalImg.style.display = "none";
          modalVideo.className = "show";
          modalVideo.src = "/media/" + item.id;
        } else {
          modalVideo.className = "";
          modalImg.style.display = "";
          modalImg.src = "/media/" + item.id;
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

  actAddPlaylist.addEventListener("click", function () {
    if (!modalItem) return;
    var itemId = modalItem.id;
    var filename = modalItem.filename;
    renderPlaylistPicker(modalPlaylistPicker, function (name) {
      fetch("/playlists/" + encodeURIComponent(name) + "/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId }),
      })
        .then(function (r) { return r.json(); })
        .then(function () {
          showToast(
            "Added \\"" + filename + "\\" to \\"" + name + "\\".", "ok"
          );
          modalPlaylistPicker.innerHTML = "";
          loadPlaylists();
        })
        .catch(function () { showToast("Could not add to slideshow.", "err"); });
    });
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
    var yearFilterRow = document.getElementById("year-filter-row");
    if (yearFilterRow) yearFilterRow.style.display = "none";
    var playlistsSection = document.getElementById("playlists-section");
    if (playlistsSection) playlistsSection.style.display = "none";
    var bulkAddPlaylistBtn = document.getElementById("bulk-add-playlist");
    if (bulkAddPlaylistBtn) bulkAddPlaylistBtn.style.display = "none";
    var actAddPlaylistBtn = document.getElementById("act-add-playlist");
    if (actAddPlaylistBtn) actAddPlaylistBtn.style.display = "none";
  }

  loadStats();
  refreshStatus();
  loadGrid();
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
