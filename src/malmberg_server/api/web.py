"""Self-contained HTML pages served by the server: bulk upload and dashboard.

Both pages are single-file (inline CSS/JS, no external CDNs/fonts/scripts)
because the server box is often offline from the wider internet.
"""

from __future__ import annotations

UPLOAD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Malmberg - Bulk Upload</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f5f7;
    --panel: #ffffff;
    --text: #1b1d21;
    --muted: #6b7280;
    --accent: #3b6ef6;
    --ok: #1f9d55;
    --warn: #b3811b;
    --err: #d64545;
    --border: #e2e4e9;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #101114;
      --panel: #1a1c20;
      --text: #eceef1;
      --muted: #9aa0aa;
      --border: #2b2e34;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 1rem;
  }
  main {
    max-width: 640px;
    margin: 0 auto;
  }
  h1 {
    font-size: 1.4rem;
    margin: 0.25rem 0 0.25rem;
  }
  p.sub {
    color: var(--muted);
    margin: 0 0 1.25rem;
    font-size: 0.95rem;
  }
  #dropzone {
    background: var(--panel);
    border: 2px dashed var(--border);
    border-radius: 16px;
    padding: 2.5rem 1rem;
    text-align: center;
    color: var(--muted);
    transition: border-color 0.15s, background 0.15s;
  }
  #dropzone.drag {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 8%, var(--panel));
  }
  #dropzone .hint {
    font-size: 0.9rem;
    margin-top: 0.5rem;
  }
  #picker-btn {
    display: inline-block;
    margin-top: 1rem;
    padding: 0.85rem 1.6rem;
    font-size: 1rem;
    font-weight: 600;
    color: #fff;
    background: var(--accent);
    border: none;
    border-radius: 999px;
    cursor: pointer;
    min-height: 48px;
  }
  #picker-btn:active { opacity: 0.85; }
  input[type="file"] { display: none; }
  #summary {
    margin-top: 1.25rem;
    display: none;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.9rem 1rem;
    font-size: 0.95rem;
  }
  #summary.show { display: block; }
  #summary b { font-weight: 700; }
  #list {
    margin-top: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .row {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.7rem 0.9rem;
  }
  .row .name {
    font-size: 0.92rem;
    font-weight: 600;
    word-break: break-all;
  }
  .row .status {
    font-size: 0.82rem;
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
  footer {
    margin-top: 2rem;
    text-align: center;
    color: var(--muted);
    font-size: 0.75rem;
  }
</style>
</head>
<body>
<main>
  <h1>Bulk Upload</h1>
  <p class="sub">Pick or drop many photos and videos.
  Each file uploads as its own request.</p>

  <div id="dropzone">
    <div>Drag and drop files here</div>
    <div class="hint">or</div>
    <button id="picker-btn" type="button">Choose files</button>
    <input id="file-input" type="file" multiple accept="image/*,video/*">
  </div>

  <div id="summary"></div>
  <div id="list"></div>

  <footer>Malmberg self-hosted photo frame</footer>
</main>
<script>
(function () {
  "use strict";
  var dropzone = document.getElementById("dropzone");
  var picker = document.getElementById("picker-btn");
  var input = document.getElementById("file-input");
  var list = document.getElementById("list");
  var summary = document.getElementById("summary");

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

    summary.className = "show";
    summary.textContent = "Uploading 0 / " + files.length + "...";

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
      list.appendChild(row);
      return row;
    });

    var idx = 0;
    function next() {
      if (idx >= files.length) return;
      var myIdx = idx++;
      uploadOne(files[myIdx], rows[myIdx], function (kind) {
        completed++;
        results[kind]++;
        summary.textContent =
          "Uploaded " + completed + " / " + total +
          "  (ok: " + results.ok + ", already exists: " + results.dup +
          ", failed: " + results.err + ")";
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
})();
</script>
</body>
</html>
"""

DASHBOARD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Malmberg - Dashboard</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f5f7;
    --panel: #ffffff;
    --text: #1b1d21;
    --muted: #6b7280;
    --accent: #3b6ef6;
    --border: #e2e4e9;
    --danger: #d64545;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #101114;
      --panel: #1a1c20;
      --text: #eceef1;
      --muted: #9aa0aa;
      --border: #2b2e34;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 1rem;
  }
  main { max-width: 900px; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin: 0.25rem 0 1rem; }
  section {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1rem;
    margin-bottom: 1.25rem;
  }
  section h2 {
    font-size: 1rem;
    margin: 0 0 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  #now-playing {
    font-size: 1.05rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
    word-break: break-word;
  }
  #now-meta {
    color: var(--muted);
    font-size: 0.85rem;
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
    min-height: 52px;
    font-size: 1rem;
    font-weight: 600;
    border: none;
    border-radius: 12px;
    background: var(--accent);
    color: #fff;
    cursor: pointer;
  }
  .controls button:active { opacity: 0.85; }
  .controls button:disabled {
    background: var(--border);
    color: var(--muted);
    cursor: not-allowed;
  }
  #control-hint {
    margin-top: 0.6rem;
    font-size: 0.82rem;
    color: var(--muted);
    display: none;
  }
  #control-hint.show { display: block; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 0.5rem;
  }
  .grid img {
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: var(--border);
  }
  #refresh-btn {
    margin-bottom: 0.75rem;
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text);
    cursor: pointer;
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
  <h1>Dashboard</h1>

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
    <h2>Recent photos</h2>
    <button id="refresh-btn" type="button">Refresh</button>
    <div class="grid" id="grid"></div>
  </section>

  <footer>Malmberg self-hosted photo frame</footer>
</main>
<script>
(function () {
  "use strict";
  var nowPlaying = document.getElementById("now-playing");
  var nowMeta = document.getElementById("now-meta");
  var hint = document.getElementById("control-hint");
  var btnPrev = document.getElementById("btn-prev");
  var btnNext = document.getElementById("btn-next");
  var btnPause = document.getElementById("btn-pause");
  var grid = document.getElementById("grid");
  var refreshBtn = document.getElementById("refresh-btn");

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

  function loadGrid() {
    grid.innerHTML = "";
    fetch("/media?page=1&page_size=24&sort=recent")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.items || []).forEach(function (item) {
          var img = document.createElement("img");
          img.src = "/media/" + item.id;
          img.alt = item.filename;
          img.loading = "lazy";
          grid.appendChild(img);
        });
      })
      .catch(function () {
        grid.innerHTML = "<div>Could not load recent photos.</div>";
      });
  }

  refreshBtn.addEventListener("click", loadGrid);

  refreshStatus();
  loadGrid();
  setInterval(refreshStatus, 5000);
})();
</script>
</body>
</html>
"""
