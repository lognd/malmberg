"""Self-contained dashboard HTML page served by the server.

The page is single-file (inline CSS/JS, no external CDNs/fonts/scripts)
because the server box is often offline from the wider internet. It is
the single source of truth for the web UI: upload, stats, search/browse,
and slideshow controls all live here.

Styling follows the Gruvbox Dark palette and monospace-forward,
terminal-flavored aesthetic used across the owner's other projects
(see logand.app docs/design/09-design-system.md), with system
monospace fallbacks since no external fonts may be loaded.
"""

from __future__ import annotations

DASHBOARD_PAGE_HTML = """<!doctype html>
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
    flex-direction: column;
    gap: 0.6rem;
  }
  .row {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.7rem 0.9rem;
  }
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
  }
  .controls button:active { opacity: 0.8; }
  .controls button:disabled {
    color: var(--muted);
    cursor: not-allowed;
  }
  #control-hint {
    margin-top: 0.6rem;
    font-size: 0.8rem;
    color: var(--muted);
    display: none;
  }
  #control-hint.show { display: block; }
  /* Browse / search */
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
  #refresh-btn {
    padding: 0 1rem;
    min-height: 44px;
    font-size: 0.85rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    color: var(--text);
    cursor: pointer;
  }
  #results-summary {
    font-size: 0.82rem;
    color: var(--muted);
    margin-bottom: 0.6rem;
  }
  /* Grid */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 0.5rem;
  }
  .tile {
    position: relative;
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
  .tile .delete-btn {
    position: absolute;
    top: 4px;
    right: 4px;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: none;
    background: rgba(40, 40, 40, 0.75);
    color: var(--err);
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .tile .delete-btn:active { background: var(--err); color: #282828; }
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
  footer {
    text-align: center;
    color: var(--muted);
    font-size: 0.75rem;
    margin-top: 1rem;
  }
</style>
</head>
<body>
<main>
  <h1>Malmberg Dashboard</h1>

  <section>
    <h2>Library</h2>
    <div id="stats-count">-- <span class="label">photos and videos</span></div>
    <div class="stats-grid" id="stats-grid"></div>
    <div id="by-year"></div>
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
    <h2>Now playing</h2>
    <div id="now-playing">Loading...</div>
    <div id="now-meta"></div>
    <div class="controls">
      <button id="btn-prev" type="button">Previous</button>
      <button id="btn-pause" type="button">Pause</button>
      <button id="btn-next" type="button">Next</button>
    </div>
    <div id="control-hint">Controls disabled: set MALMBERG_DISPLAY_URL
    on the server to enable.</div>
  </section>

  <section>
    <h2>Browse photos</h2>
    <div class="search-row">
      <input id="search-input" type="text"
        placeholder="Search by filename or year (e.g. 2006)">
      <button id="refresh-btn" type="button">Refresh</button>
    </div>
    <div id="results-summary"></div>
    <div class="grid" id="grid"></div>
    <div class="pagination">
      <button id="page-prev" type="button">Previous</button>
      <span class="page-info" id="page-info"></span>
      <button id="page-next" type="button">Next</button>
    </div>
  </section>

  <footer>Malmberg self-hosted photo frame</footer>
</main>
<script>
(function () {
  "use strict";

  /* ---- Stats ---- */
  var statsCount = document.getElementById("stats-count");
  var statsGrid = document.getElementById("stats-grid");
  var byYear = document.getElementById("by-year");

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
        '<div class="name"></div>' +
        '<div class="status">Queued</div>' +
        '<div class="bar-track"><div class="bar-fill"></div></div>';
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

  /* ---- Now playing / controls ---- */
  var nowPlaying = document.getElementById("now-playing");
  var nowMeta = document.getElementById("now-meta");
  var hint = document.getElementById("control-hint");
  var btnPrev = document.getElementById("btn-prev");
  var btnNext = document.getElementById("btn-next");
  var btnPause = document.getElementById("btn-pause");

  function setControlsDisabled(disabled) {
    btnPrev.disabled = disabled;
    btnNext.disabled = disabled;
    btnPause.disabled = disabled;
    hint.className = disabled ? "show" : "";
  }

  function refreshStatus() {
    fetch("/control/status")
      .then(function (r) {
        if (r.status === 503) {
          setControlsDisabled(true);
          nowPlaying.textContent = "Display not configured";
          nowMeta.textContent = "";
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
      })
      .catch(function () {
        setControlsDisabled(true);
        nowPlaying.textContent = "Unable to reach display";
        nowMeta.textContent = "";
      });
  }

  function sendControl(path) {
    fetch(path, { method: "POST" })
      .then(function () { refreshStatus(); })
      .catch(function () { refreshStatus(); });
  }

  btnPrev.addEventListener("click", function () { sendControl("/control/prev"); });
  btnNext.addEventListener("click", function () { sendControl("/control/next"); });
  btnPause.addEventListener("click", function () { sendControl("/control/pause"); });

  /* ---- Browse / search grid, server-side paginated ---- */
  var grid = document.getElementById("grid");
  var refreshBtn = document.getElementById("refresh-btn");
  var searchInput = document.getElementById("search-input");
  var resultsSummary = document.getElementById("results-summary");
  var pagePrev = document.getElementById("page-prev");
  var pageNext = document.getElementById("page-next");
  var pageInfo = document.getElementById("page-info");

  var PAGE_SIZE = 24;
  var state = { page: 1, q: "", hasNext: false, total: 0 };
  var searchDebounce = null;

  function loadGrid() {
    var params = "page=" + state.page + "&page_size=" + PAGE_SIZE +
      "&sort=recent";
    if (state.q) params += "&q=" + encodeURIComponent(state.q);

    fetch("/media?" + params)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.hasNext = !!data.has_next;
        state.total = data.total || 0;

        grid.innerHTML = "";
        (data.items || []).forEach(function (item) {
          var tile = document.createElement("div");
          tile.className = "tile";

          var img = document.createElement("img");
          img.src = "/media/" + item.id + "/thumb";
          img.alt = item.filename;
          img.loading = "lazy";
          tile.appendChild(img);

          var del = document.createElement("button");
          del.type = "button";
          del.className = "delete-btn";
          del.title = "Delete " + item.filename;
          del.textContent = "\\u00d7";
          del.addEventListener("click", function () {
            if (!window.confirm("Delete " + item.filename + "?")) return;
            fetch("/media/" + item.id, { method: "DELETE" })
              .then(function (r) {
                if (r.ok) {
                  loadStats();
                  loadGrid();
                } else {
                  window.alert("Could not delete " + item.filename);
                }
              })
              .catch(function () {
                window.alert("Could not delete " + item.filename);
              });
          });
          tile.appendChild(del);

          grid.appendChild(tile);
        });

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
        pageInfo.textContent = "Page " + state.page;
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

  loadStats();
  refreshStatus();
  loadGrid();
  setInterval(refreshStatus, 5000);
})();
</script>
</body>
</html>
"""
