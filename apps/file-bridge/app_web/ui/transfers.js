// Transfer queue in the dock: live rows (progress, speed, time left, cancel/retry), an overall summary in the dock
// bar, and NB.transfer() which asks once about conflicts before anything is replaced.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var jobs = new Map(), afterBatch = [];
  var ACTIVE = { queued: 1, running: 1, paused: 1 };
  var STATUS = { queued: "Waiting", running: "", paused: "Paused", completed: "Done", failed: "Failed", cancelled: "Cancelled" };

  function speed(bps) { return bps ? NB.humanSize(Math.round(bps)) + "/s" : ""; }
  function eta(s) {
    if (s == null || !isFinite(s)) { return ""; }
    s = Math.round(s);
    return s < 60 ? s + " s left" : s < 3600 ? Math.round(s / 60) + " min left" : Math.round(s / 3600) + " h left";
  }

  function counts() {
    var active = 0, failed = 0, done = 0, total = 0, bytes = 0, rate = 0;
    jobs.forEach(function (j) {
      if (ACTIVE[j.status]) { active++; total += j.total || 0; bytes += j.done || 0; rate += j.status === "running" ? j.speed || 0 : 0; }
      if (j.status === "failed") { failed++; }
      if (j.status === "completed") { done++; }
    });
    return { active: active, failed: failed, done: done, total: total, bytes: bytes, rate: rate };
  }

  function summary() {
    var c = counts(), meta = $("#dockMeta"), count = $("#transferCount");
    count.textContent = String(c.active);
    count.classList.toggle("busy", c.active > 0);
    var bar = $(".dock-progress");
    if (c.active) {
      var pct = c.total ? Math.min(100, c.bytes / c.total * 100) : 0;
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "dock-progress";
        bar.setAttribute("role", "progressbar");
        bar.setAttribute("aria-label", "All transfers");
        bar.innerHTML = '<b aria-hidden="true"><i></i></b><span class="num"></span>';
        meta.parentNode.insertBefore(bar, meta);
      }
      bar.setAttribute("aria-valuenow", String(Math.round(pct)));
      bar.querySelector("i").style.transform = "scaleX(" + (pct / 100) + ")";
      bar.querySelector("span").textContent = c.active + (c.active === 1 ? " transfer" : " transfers") + (c.rate ? " · " + speed(c.rate) : "");
      meta.hidden = true;
    } else {
      if (bar) { bar.remove(); }
      meta.hidden = false;
    }
  }

  function rowHTML(j) {
    var pct = j.total ? Math.min(100, (j.done || 0) / j.total * 100) : j.status === "completed" ? 100 : 0;
    var detail = j.status === "running"
      ? [NB.humanSize(j.done || 0) + (j.total ? " of " + NB.humanSize(j.total) : ""), speed(j.speed), eta(j.eta)].filter(Boolean).join(" · ")
      : j.status === "failed" ? (j.error || "Failed") : STATUS[j.status];
    var actions = ACTIVE[j.status]
      ? '<button type="button" class="icon ghost sm" data-x="cancel" aria-label="Cancel ' + esc(j.name) + '" title="Cancel">' + ICO("close") + "</button>"
      : j.status === "failed" || j.status === "cancelled"
        ? '<button type="button" class="icon ghost sm" data-x="retry" aria-label="Retry ' + esc(j.name) + '" title="Retry">' + ICO("sync") + "</button>" : "";
    return '<div class="xfer ' + esc(j.status) + '" data-id="' + esc(j.id) + '">' +
      '<span class="xfer-dir" title="' + (j.dir === "up" ? "Upload" : "Download") + '">' + ICO(j.dir === "up" ? "upload" : "download") + "</span>" +
      '<span class="xfer-main"><span class="xfer-name" title="' + esc(j.src + " → " + j.dst) + '">' + esc(j.name) + "</span>" +
      '<span class="xfer-bar" role="progressbar" aria-label="' + esc(j.name) + '" aria-valuenow="' + Math.round(pct) + '" aria-valuemin="0" aria-valuemax="100"><i style="transform:scaleX(' + (pct / 100) + ')"></i></span></span>' +
      '<span class="xfer-detail num">' + esc(detail) + "</span>" + '<span class="xfer-act">' + actions + "</span></div>";
  }

  NB.renderTransfers = function (body) {
    if (!jobs.size) {
      body.innerHTML = '<div class="dock-empty">No transfers yet. Select files and press F5, or drag them to the other pane.</div>';
      return;
    }
    var c = counts(), list = Array.from(jobs.values()).reverse();
    body.innerHTML = '<div class="xfer-tools"><span class="muted num">' + c.active + " active · " + c.done + " done" + (c.failed ? " · " + c.failed + " failed" : "") + "</span>" +
      (c.failed ? '<button type="button" class="sm" data-x="retry_failed">Retry failed</button>' : "") +
      '<button type="button" class="sm ghost" data-x="clear">Clear finished</button></div>' +
      '<div class="xfer-list">' + list.map(rowHTML).join("") + "</div>";
  };
  function redraw() {
    summary();
    var body = $("#dockBody");
    if (!$("#dock").classList.contains("collapsed") && $("#dockTabTransfers").getAttribute("aria-selected") === "true") {
      var scroll = body.scrollTop;
      NB.renderTransfers(body);
      body.scrollTop = scroll;
    }
  }
  var queued = false;
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(function () { queued = false; redraw(); }); } }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("#dockBody [data-x]");
    if (!b) { return; }
    var x = b.getAttribute("data-x"), row = b.closest("[data-id]"), id = row && row.getAttribute("data-id");
    var call = x === "cancel" ? NB.api("xfer.cancel", { id: id }) : x === "retry" ? NB.api("xfer.retry", { id: id })
      : x === "retry_failed" ? NB.api("xfer.retry_failed") : NB.api("xfer.clear");
    call.then(function (r) {
      if (!r.ok) { NB.toast(r.error); }
      if (x === "clear") { NB.api("xfer.list").then(load); }
    });
  });

  function load(r) { if (r.ok) { jobs.clear(); r.data.forEach(function (j) { jobs.set(j.id, j); }); schedule(); } }
  NB.on("xfer.jobs", function (batch) { batch.forEach(function (j) { jobs.set(j.id, j); }); schedule(); });
  NB.on("xfer.cleared", function () { NB.api("xfer.list").then(load); });
  NB.on("xfer.batch_done", function (p) {
    NB.toast(p.failed ? p.failed + " of " + (p.done + p.failed) + " transfers failed. See the dock for details." : "Transfers finished.", p.failed ? "" : "ok");
    var run = afterBatch.splice(0);
    run.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
  });

  // ---- start a transfer: check conflicts, ask once, then queue
  NB.transfer = function (direction, items, dest, after) {
    NB.api("xfer.plan", { direction: direction, items: items, dest: dest }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      var conflicts = r.data.conflicts;
      (conflicts.length ? askConflict(direction, conflicts) : Promise.resolve(null)).then(function (policy) {
        if (policy === false) { return; }
        NB.api("xfer.start", { direction: direction, items: items, dest: dest, policy: policy }).then(function (s) {
          if (!s.ok) { NB.toast(s.error); return; }
          if (after) { afterBatch.push(after); }
          NB.toast((direction === "upload" ? "Uploading " : "Downloading ") + s.data.queued + (s.data.queued === 1 ? " file" : " files") + "…", "ok");
          if ($("#dock").classList.contains("collapsed")) { NB.setDock(true, "transfers"); }
        });
      });
    });
  };
  function askConflict(direction, conflicts) {
    return new Promise(function (resolve) {
      var where = direction === "upload" ? "on the server" : "on this computer";
      var body = document.createElement("div"), done = false;
      var shown = conflicts.slice(0, 6).map(function (c) { return '<li class="mono">' + esc(c.name) + "</li>"; }).join("") +
        (conflicts.length > 6 ? '<li class="muted">and ' + (conflicts.length - 6) + " more</li>" : "");
      body.innerHTML = '<ul class="conflict-list">' + shown + "</ul>" +
        '<div class="choice" role="radiogroup" aria-label="What to do">' +
        '<label><input type="radio" name="pol" value="rename" checked><span><b>Keep both</b><small>Save the new copy under a new name</small></span></label>' +
        '<label><input type="radio" name="pol" value="skip"><span><b>Skip</b><small>Leave the existing files as they are</small></span></label>' +
        '<label><input type="radio" name="pol" value="overwrite"><span><b>Replace</b><small>Overwrite the existing files</small></span></label></div>' +
        '<div class="modal-actions"><button type="button" data-a="no">Cancel</button><button type="button" class="pri" data-a="go">Continue</button></div>';
      var m = NB.modal({
        title: conflicts.length === 1 ? "“" + conflicts[0].name + "” already exists" : conflicts.length + " items already exist",
        sub: "They're already " + where + ". Your choice applies to all of them.",
        body: body, initialFocus: "input[checked]", onClose: function () { if (!done) { resolve(false); } }
      });
      body.querySelector("[data-a=no]").addEventListener("click", function () { m.close(); });
      body.querySelector("[data-a=go]").addEventListener("click", function () {
        done = true;
        var v = body.querySelector("input[name=pol]:checked").value;
        m.close();
        resolve(v);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    NB.api("xfer.list").then(load);
    NB.on("dock_render", function (body) { NB.renderTransfers(body); });
  });
})();
