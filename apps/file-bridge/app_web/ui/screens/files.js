// Files: this computer on the left, the server on the right. Virtualized lists, full keyboard control,
// drag between panes, F5 copy to the other pane, conflict choice before anything is replaced.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var ROW_H = 32;
  var sizeFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
  var dateFmt = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  var KIND_ICON = { d: "files", f: "doc", l: "link", o: "doc" };

  function humanSize(n) {
    if (n == null) { return ""; }
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return (i === 0 ? String(v) : sizeFmt.format(v)) + " " + u[i];
  }
  NB.humanSize = humanSize;
  function joinPath(side, folder, name) {
    if (side === "remote") { return folder === "/" ? "/" + name : folder.replace(/\/+$/, "") + "/" + name; }
    var sep = folder.indexOf("\\") >= 0 || /^[A-Za-z]:/.test(folder) ? "\\" : "/";
    return folder.replace(/[\\/]+$/, "") + sep + name;
  }

  // ======================================================================== Pane
  function Pane(side, host, screen) {
    this.side = side;
    this.screen = screen;
    this.path = null;
    this.parent = null;
    this.items = [];          // [name, kind, size, mtime, perms]
    this.view = [];           // indices into items, after filter + sort
    this.selected = new Set(); // names
    this.focus = 0;
    this.anchor = 0;
    this.sort = NB.uiState("sort-" + side) || { key: "name", dir: 1 };
    this.hidden = !!NB.uiState("hidden-" + side);
    this.filter = "";
    this.typed = "";
    this.el = host;
    this.build();
  }
  Pane.prototype.label = function () {
    return this.side === "local" ? "This computer" : (NB.conn.profile ? NB.conn.profile.name : "Server");
  };
  Pane.prototype.build = function () {
    var s = this.side, id = "pane-" + s;
    this.el.className = "pane " + s;
    this.el.innerHTML =
      '<div class="pane-head">' +
        '<div class="pane-title">' + ICO(s === "local" ? "window" : "servers") + '<span class="pane-name"></span>' +
          (s === "remote" ? '<span class="chip acc pane-badge" hidden></span>' : "") + "</div>" +
        '<div class="pane-tools">' +
          (s === "local" ? '<button type="button" class="icon ghost sm" data-act="places" aria-label="Drives and places" title="Drives and places" aria-haspopup="menu">' + ICO("window") + "</button>" : "") +
          '<button type="button" class="icon ghost sm" data-act="up" aria-label="Up one folder" title="Up one folder (Backspace)">' + ICO("up") + "</button>" +
          '<button type="button" class="icon ghost sm" data-act="refresh" aria-label="Refresh" title="Refresh (Ctrl+R)">' + ICO("refresh") + "</button>" +
          '<button type="button" class="icon ghost sm" data-act="mkdir" aria-label="New folder" title="New folder (F7)">' + ICO("folderplus") + "</button>" +
          '<button type="button" class="icon ghost sm" data-act="hidden" aria-pressed="' + this.hidden + '" aria-label="Show hidden files" title="Show hidden files">' + ICO("eye") + "</button>" +
          '<input type="search" class="pane-filter" placeholder="Filter…" aria-label="Filter ' + (s === "local" ? "local" : "server") + ' files" autocomplete="off" spellcheck="false">' +
        "</div></div>" +
      '<nav class="crumbs" aria-label="' + (s === "local" ? "Local" : "Server") + ' folder"></nav>' +
      '<div class="cols" role="presentation">' +
        '<button type="button" class="col name" data-sort="name">Name</button>' +
        '<button type="button" class="col size" data-sort="size">Size</button>' +
        '<button type="button" class="col date" data-sort="mtime">Modified</button></div>' +
      '<div class="list" tabindex="0" role="listbox" aria-multiselectable="true" id="' + id + '-list" aria-label=""></div>' +
      '<div class="pane-empty" hidden></div>' +
      '<div class="pane-foot num" aria-live="polite"></div>';
    this.list = $(".list", this.el);
    this.vl = new NB.VList(this.list, { rowHeight: ROW_H, render: this.row.bind(this) });
    this.bind();
    this.updateHead();
  };
  Pane.prototype.updateHead = function () {
    $(".pane-name", this.el).textContent = this.label();
    this.list.setAttribute("aria-label", this.label() + " files");
    var badge = $(".pane-badge", this.el);
    if (badge) {
      var p = NB.conn.profile;
      badge.hidden = !p;
      if (p) { badge.textContent = p.protocol.toUpperCase(); }
    }
    $$(".col", this.el).forEach(function (b) {
      var on = b.getAttribute("data-sort") === this.sort.key;
      b.setAttribute("aria-sort", on ? (this.sort.dir > 0 ? "ascending" : "descending") : "none");
      b.classList.toggle("on", on);
    }, this);
  };
  Pane.prototype.row = function (i) {
    var it = this.items[this.view[i]], name = it[0], sel = this.selected.has(name), foc = i === this.focus;
    var date = it[3] ? dateFmt.format(new Date(it[3] * 1000)) : "";
    return '<div class="row' + (sel ? " sel" : "") + (foc ? " foc" : "") + (it[1] === "d" ? " dir" : "") + '" role="option" id="' +
      this.side + "-r-" + i + '" data-i="' + i + '" aria-selected="' + sel + '" aria-setsize="' + this.view.length + '" aria-posinset="' + (i + 1) +
      '" draggable="true">' + ICO(KIND_ICON[it[1]] || "doc") + '<span class="nm">' + esc(name) + '</span><span class="sz num">' +
      (it[1] === "d" ? "" : humanSize(it[2])) + '</span><span class="dt num">' + esc(date) + "</span></div>";
  };

  // ---- data
  Pane.prototype.load = function (path, keepSelection) {
    var self = this;
    if (this.side === "remote" && NB.conn.status !== "connected") { this.showDisconnected(); return Promise.resolve(); }
    this.list.setAttribute("aria-busy", "true");
    if (!this.items.length || this.path == null) { this.showLoading(path || this.path); }
    var token = this.loadToken = (this.loadToken || 0) + 1;
    return NB.api("fs." + this.side + ".list", { path: path || this.path, hidden: this.hidden }).then(function (r) {
      if (token !== self.loadToken) { return; }      // a newer request replaced this one
      self.list.removeAttribute("aria-busy");
      if (!r.ok) { NB.toast(r.error); if (self.path == null || !self.items.length) { self.showError(r.error); } return; }
      var changed = r.data.path !== self.path;
      self.path = r.data.path;
      self.parent = r.data.parent;
      self.items = r.data.items;
      if (changed && !keepSelection) { self.selected.clear(); self.focus = 0; self.filter = ""; $(".pane-filter", self.el).value = ""; }
      NB.uiState("path-" + self.side + (self.side === "remote" && NB.conn.profile ? "-" + NB.conn.profile.id : ""), self.path);
      (r.data.warnings || []).forEach(function (w) { NB.toast(w); });
      self.apply();
      self.crumbs();
    });
  };
  Pane.prototype.apply = function () {
    var items = this.items, f = this.filter.toLowerCase(), key = this.sort.key, dir = this.sort.dir;
    var view = [];
    for (var i = 0; i < items.length; i++) { if (!f || items[i][0].toLowerCase().indexOf(f) >= 0) { view.push(i); } }
    var col = key === "size" ? 2 : key === "mtime" ? 3 : 0;
    view.sort(function (a, b) {
      var A = items[a], B = items[b];
      if ((A[1] === "d") !== (B[1] === "d")) { return A[1] === "d" ? -1 : 1; }
      if (col === 0) { return dir * A[0].localeCompare(B[0], undefined, { numeric: true, sensitivity: "base" }); }
      return dir * ((A[col] || 0) - (B[col] || 0)) || A[0].localeCompare(B[0]);
    });
    this.view = view;
    this.focus = Math.min(this.focus, Math.max(0, view.length - 1));
    var empty = $(".pane-empty", this.el);
    empty.hidden = view.length > 0;
    if (!view.length) { empty.innerHTML = '<p class="muted">' + (f ? "No names match the filter." : "This folder is empty.") + "</p>"; }
    this.list.hidden = false;
    this.vl.setCount(view.length);
    this.updateHead();
    this.foot();
    this.aria();
  };
  Pane.prototype.foot = function () {
    var dirs = 0, files = 0, bytes = 0, selBytes = 0, sel = 0, self = this;
    this.view.forEach(function (i) {
      var it = self.items[i];
      if (it[1] === "d") { dirs++; } else { files++; bytes += it[2] || 0; }
      if (self.selected.has(it[0])) { sel++; selBytes += it[1] === "d" ? 0 : it[2] || 0; }
    });
    $(".pane-foot", this.el).textContent = sel
      ? sel + " selected" + (selBytes ? " · " + humanSize(selBytes) : "") + " of " + this.view.length
      : dirs + (dirs === 1 ? " folder" : " folders") + " · " + files + (files === 1 ? " file" : " files") + (bytes ? " · " + humanSize(bytes) : "");
  };
  Pane.prototype.crumbs = function () {
    var nav = $(".crumbs", this.el), p = this.path || "", parts, html = "", acc;
    if (this.side === "remote") {
      parts = p.split("/").filter(Boolean);
      acc = p.charAt(0) === "/" ? "" : null;
      html += p.charAt(0) === "/" ? '<button type="button" class="crumb" data-path="/">/</button>' : "";
      parts.forEach(function (seg, i) {
        acc = acc === null ? seg : acc + "/" + seg;
        html += (i || p.charAt(0) === "/" ? '<span class="sep" aria-hidden="true">' + ICO("chevron") + "</span>" : "") +
          '<button type="button" class="crumb" data-path="' + esc(acc.charAt(0) === "/" || p.charAt(0) !== "/" ? acc : "/" + acc) + '">' + esc(seg) + "</button>";
      });
    } else {
      var win = /^[A-Za-z]:/.test(p) || p.indexOf("\\") >= 0, sep = win ? "\\" : "/";
      parts = p.split(/[\\/]+/).filter(Boolean);
      acc = win ? "" : "/";
      if (!win) { html += '<button type="button" class="crumb" data-path="/">/</button>'; }
      parts.forEach(function (seg, i) {
        acc = win ? (i === 0 ? seg + sep : acc.replace(/[\\/]+$/, "") + sep + seg) : (acc === "/" ? "/" + seg : acc + "/" + seg);
        html += (i || !win ? '<span class="sep" aria-hidden="true">' + ICO("chevron") + "</span>" : "") +
          '<button type="button" class="crumb" data-path="' + esc(acc) + '">' + esc(seg) + "</button>";
      });
    }
    nav.innerHTML = html;
    var last = nav.lastElementChild;
    if (last) { last.setAttribute("aria-current", "location"); nav.scrollLeft = nav.scrollWidth; }
  };
  // Type or paste a folder path (click the empty part of the path bar, or Ctrl+L). Enter goes there, Esc cancels.
  Pane.prototype.editPath = function () {
    if (this.side === "remote" && NB.conn.status !== "connected") { return; }
    var self = this, nav = $(".crumbs", this.el), done = false;
    nav.innerHTML = '<input class="crumb-edit mono" autocomplete="off" spellcheck="false" aria-label="Go to folder">';
    var input = nav.firstChild;
    input.value = this.path || "";
    input.focus();
    input.select();
    function finish(go) {
      if (done) { return; }
      done = true;
      var target = input.value.trim();
      if (go && target && target !== self.path) { self.load(target).then(function () { self.crumbs(); }); } else { self.crumbs(); }
      if (go) { self.list.focus(); }
    }
    input.addEventListener("keydown", function (e) {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); self.list.focus(); }
    });
    input.addEventListener("blur", function () { finish(false); });
  };
  // Drives (C:, D: … on Windows; / and mounted disks elsewhere) and the usual folders.
  Pane.prototype.places = function (x, y) {
    var self = this;
    NB.api("fs.local.roots").then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      var entries = r.data.drives.map(function (d) { return ["p:" + d.path, d.label]; });
      entries.push(["-"]);
      r.data.places.forEach(function (p) { entries.push(["p:" + p.path, p.label]); });
      entries.push(["-"], ["type", "Type a path…", "Ctrl+L"]);
      NB.contextMenu(x, y, entries, function (id) {
        if (id === "type") { self.editPath(); return; }
        self.load(id.slice(2));
        self.list.focus();
      });
    });
  };
  Pane.prototype.showDisconnected = function () {
    this.path = null;
    this.items = [];
    this.view = [];
    this.vl.setCount(0);
    $(".crumbs", this.el).innerHTML = "";
    $(".pane-foot", this.el).textContent = "";
    this.updateHead();
    var empty = $(".pane-empty", this.el);
    empty.hidden = false;
    this.list.hidden = true;
    var connecting = NB.conn.status === "connecting";
    empty.innerHTML = '<div class="empty"><div class="empty-ico">' + ICO("servers") + "</div><h2>" +
      (connecting ? "Connecting…" : "Connect to a server") + "</h2><p>" +
      (connecting ? esc(NB.conn.label) : "Its files appear here, next to the ones on this computer.") + "</p>" +
      (connecting ? "" : '<div class="actions"><button type="button" class="pri" data-go="connections">' + ICO("plus") +
        "New connection</button><button type=\"button\" data-go=\"saved\">Saved servers</button></div>") + "</div>";
    $$("[data-go]", empty).forEach(function (b) {
      b.addEventListener("click", function () { NB.go("connections", { create: b.getAttribute("data-go") === "connections" }); });
    });
  };
  Pane.prototype.showLoading = function (path) {
    var empty = $(".pane-empty", this.el);
    this.list.hidden = true;
    empty.hidden = false;
    empty.innerHTML = '<div class="pane-loading" role="status"><div class="skel" style="width:60%"></div><div class="skel" style="width:44%"></div>' +
      '<div class="skel" style="width:52%"></div><p class="muted"></p></div>';
    empty.querySelector("p").textContent = "Loading " + (path && path !== "." ? path : "folder") + "…";
  };
  Pane.prototype.showError = function (msg) {
    var empty = $(".pane-empty", this.el);
    empty.hidden = false;
    empty.innerHTML = '<p class="muted"></p>';
    empty.firstChild.textContent = msg;
  };

  // ---- selection
  Pane.prototype.item = function (vi) { var idx = this.view[vi]; return idx == null ? null : this.items[idx]; };
  Pane.prototype.selection = function () {
    var self = this, out = [];
    this.view.forEach(function (i) { if (self.selected.has(self.items[i][0])) { out.push(self.items[i]); } });
    if (!out.length) { var f = this.item(this.focus); if (f) { out.push(f); } }
    return out;
  };
  Pane.prototype.selectRange = function (to) {
    this.selected.clear();
    var a = Math.min(this.anchor, to), b = Math.max(this.anchor, to);
    for (var i = a; i <= b; i++) { this.selected.add(this.item(i)[0]); }
  };
  Pane.prototype.setFocus = function (i, mode) {
    if (!this.view.length) { return; }
    i = Math.max(0, Math.min(this.view.length - 1, i));
    this.focus = i;
    if (mode === "range") { this.selectRange(i); }
    else if (mode === "single") { this.selected.clear(); this.selected.add(this.item(i)[0]); this.anchor = i; }
    else if (mode !== "keep") { this.anchor = i; }
    this.vl.reveal(i);
    this.vl.refresh();
    this.foot();
    this.aria();
  };
  Pane.prototype.aria = function () {
    if (this.view.length) { this.list.setAttribute("aria-activedescendant", this.side + "-r-" + this.focus); }
    else { this.list.removeAttribute("aria-activedescendant"); }
  };
  Pane.prototype.open = function (vi) {
    var it = this.item(vi);
    if (!it) { return; }
    if (it[1] === "d" || it[1] === "l") { this.load(joinPath(this.side, this.path, it[0])); return; }   // a link to a file says so
    NB.openEditor(this.side, joinPath(this.side, this.path, it[0]));
  };
  Pane.prototype.up = function () { if (this.parent) { this.load(this.parent); } };

  // ---- events
  Pane.prototype.bind = function () {
    var self = this;
    $(".pane-tools", this.el).addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]");
      if (!b) { return; }
      var a = b.getAttribute("data-act");
      if (a === "up") { self.up(); }
      else if (a === "places") { var bx = b.getBoundingClientRect(); self.places(bx.left, bx.bottom + 4); }
      else if (a === "refresh") { self.load(null, true); }
      else if (a === "mkdir") { self.screen.mkdir(self); }
      else if (a === "hidden") {
        self.hidden = !self.hidden;
        b.setAttribute("aria-pressed", String(self.hidden));
        NB.uiState("hidden-" + self.side, self.hidden);
        self.load(null, true);
      }
    });
    $(".pane-filter", this.el).addEventListener("input", function (e) { self.filter = e.target.value; self.focus = 0; self.apply(); });
    $(".pane-filter", this.el).addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "Enter") { e.preventDefault(); self.list.focus(); self.setFocus(0, "single"); }
      if (e.key === "Escape") { e.target.value = ""; self.filter = ""; self.apply(); self.list.focus(); }
    });
    $(".crumbs", this.el).addEventListener("click", function (e) {
      if (e.target.closest(".crumb-edit")) { return; }
      var c = e.target.closest("[data-path]");
      if (c) { self.load(c.getAttribute("data-path")); } else { self.editPath(); }      // empty space: type a path
    });
    $(".cols", this.el).addEventListener("click", function (e) {
      var c = e.target.closest("[data-sort]");
      if (!c) { return; }
      var k = c.getAttribute("data-sort");
      self.sort = { key: k, dir: self.sort.key === k ? -self.sort.dir : 1 };
      NB.uiState("sort-" + self.side, self.sort);
      self.apply();
    });
    this.list.addEventListener("mousedown", function (e) {
      var r = e.target.closest(".row");
      self.screen.active = self;
      if (!r || e.button !== 0) { return; }
      var i = Number(r.getAttribute("data-i"));
      // Double-click is read from the click count here, not from "dblclick": every mousedown redraws the rows, so
      // the second click's mousedown and mouseup land on different elements and the browser never fires dblclick.
      if (e.detail === 2 && !e.shiftKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); self.open(i); return; }
      if (e.shiftKey) { self.setFocus(i, "range"); }
      else if (e.ctrlKey || e.metaKey) {
        var n = self.item(i)[0];
        if (self.selected.has(n)) { self.selected.delete(n); } else { self.selected.add(n); }
        self.setFocus(i, "keep");
      } else if (!self.selected.has(self.item(i)[0]) || self.selected.size <= 1) { self.setFocus(i, "single"); }
      else { self.setFocus(i, "keep"); }
    });
    this.list.addEventListener("contextmenu", function (e) {
      e.preventDefault();
      var r = e.target.closest(".row");
      if (r) {
        var i = Number(r.getAttribute("data-i"));
        if (!self.selected.has(self.item(i)[0])) { self.setFocus(i, "single"); }
      }
      self.screen.active = self;
      self.screen.menu(self, e.clientX, e.clientY, !!r);
    });
    this.list.addEventListener("focus", function () { self.screen.active = self; self.el.classList.add("active"); self.screen.other(self).el.classList.remove("active"); });
    this.list.addEventListener("keydown", function (e) { self.key(e); });
    // drag between panes
    this.list.addEventListener("dragstart", function (e) {
      var r = e.target.closest(".row");
      if (!r) { return; }
      var i = Number(r.getAttribute("data-i"));
      if (!self.selected.has(self.item(i)[0])) { self.setFocus(i, "single"); }
      e.dataTransfer.setData("application/x-nobad-files", self.side);
      e.dataTransfer.effectAllowed = "copy";
      document.body.classList.add("dragging");
    });
    this.list.addEventListener("dragend", function () { document.body.classList.remove("dragging"); });
    this.el.addEventListener("dragover", function (e) {
      var from = e.dataTransfer.types.indexOf("application/x-nobad-files") >= 0;
      var files = e.dataTransfer.types.indexOf("Files") >= 0;
      if ((from || (files && self.side === "remote")) && (!from || true)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; self.el.classList.add("drop"); }
      NB.lastDropPane = self.side;
    });
    this.el.addEventListener("dragleave", function (e) { if (!self.el.contains(e.relatedTarget)) { self.el.classList.remove("drop"); } });
    this.el.addEventListener("drop", function (e) {
      self.el.classList.remove("drop");
      var from = e.dataTransfer.getData("application/x-nobad-files");
      if (from && from !== self.side) { e.preventDefault(); self.screen.copyTo(self.screen.other(self), self); }
      else if (from) { e.preventDefault(); }
    });
  };
  Pane.prototype.key = function (e) {
    var k = e.key, mod = e.ctrlKey || e.metaKey, page = this.vl.pageSize();
    var move = function (self, i) { self.setFocus(i, e.shiftKey ? "range" : mod ? "keep" : "single"); };
    if (k === "ArrowDown") { e.preventDefault(); move(this, this.focus + 1); }
    else if (k === "ArrowUp" && e.altKey) { e.preventDefault(); this.up(); }
    else if (k === "ArrowUp") { e.preventDefault(); move(this, this.focus - 1); }
    else if (k === "PageDown") { e.preventDefault(); move(this, this.focus + page); }
    else if (k === "PageUp") { e.preventDefault(); move(this, this.focus - page); }
    else if (k === "Home") { e.preventDefault(); move(this, 0); }
    else if (k === "End") { e.preventDefault(); move(this, this.view.length - 1); }
    else if (k === "Enter") { e.preventDefault(); this.open(this.focus); }
    else if (mod && k.toLowerCase() === "l") { e.preventDefault(); this.editPath(); }
    else if (k === "Backspace") { e.preventDefault(); this.up(); }
    else if (k === " " && !this.typed) {
      e.preventDefault();
      var it = this.item(this.focus);
      if (it) { if (this.selected.has(it[0])) { this.selected.delete(it[0]); } else { this.selected.add(it[0]); } this.setFocus(this.focus, "keep"); }
    }
    else if (mod && k.toLowerCase() === "a") { e.preventDefault(); var self = this; this.view.forEach(function (i) { self.selected.add(self.items[i][0]); }); this.vl.refresh(); this.foot(); }
    else if (mod && k.toLowerCase() === "r") { e.preventDefault(); this.load(null, true); }
    else if (k === "F5") { e.preventDefault(); this.screen.copyTo(this, this.screen.other(this)); }
    else if (k === "F2") { e.preventDefault(); this.screen.rename(this); }
    else if (k === "F7") { e.preventDefault(); this.screen.mkdir(this); }
    else if (k === "Delete") { e.preventDefault(); this.screen.remove(this); }
    else if (k === "Escape") { this.selected.clear(); this.vl.refresh(); this.foot(); }
    else if (k.length === 1 && !mod && !e.altKey) { this.typeAhead(k); }
  };
  Pane.prototype.typeAhead = function (ch) {
    var self = this;
    clearTimeout(this.typedTimer);
    this.typed += ch.toLowerCase();
    this.typedTimer = setTimeout(function () { self.typed = ""; }, 700);
    for (var i = 0; i < this.view.length; i++) {
      if (this.items[this.view[i]][0].toLowerCase().indexOf(this.typed) === 0) { this.setFocus(i, "single"); return; }
    }
  };

  // ======================================================================== Screen
  function FilesScreen(el) {
    this.el = el;
    el.innerHTML = '<div class="files" id="filesRoot"><section class="pane-host" id="paneLocal" aria-label="This computer"></section>' +
      '<div class="splitter" role="separator" aria-orientation="vertical" aria-label="Resize panes" tabindex="0" aria-valuemin="25" aria-valuemax="75"></div>' +
      '<section class="pane-host" id="paneRemote" aria-label="Server"></section></div>';
    this.local = new Pane("local", $("#paneLocal", el), this);
    this.remote = new Pane("remote", $("#paneRemote", el), this);
    this.active = this.local;
    this.splitter();
  }
  FilesScreen.prototype.other = function (p) { return p === this.local ? this.remote : this.local; };
  FilesScreen.prototype.splitter = function () {
    var root = $("#filesRoot", this.el), sp = $(".splitter", this.el);
    var set = function (pct) {
      pct = Math.max(25, Math.min(75, pct));
      root.style.setProperty("--split", pct + "%");
      sp.setAttribute("aria-valuenow", String(Math.round(pct)));
      NB.uiState("split", pct);
    };
    set(NB.uiState("split") || 50);
    sp.addEventListener("pointerdown", function (e) {
      sp.setPointerCapture(e.pointerId);
      var r = root.getBoundingClientRect();
      var move = function (ev) { set((ev.clientX - r.left) / r.width * 100); };
      var stop = function () { sp.removeEventListener("pointermove", move); sp.removeEventListener("pointerup", stop); document.body.classList.remove("resizing"); };
      document.body.classList.add("resizing");
      sp.addEventListener("pointermove", move);
      sp.addEventListener("pointerup", stop);
    });
    sp.addEventListener("keydown", function (e) {
      var now = Number(sp.getAttribute("aria-valuenow"));
      if (e.key === "ArrowLeft") { e.preventDefault(); set(now - 5); }
      if (e.key === "ArrowRight") { e.preventDefault(); set(now + 5); }
    });
    sp.addEventListener("dblclick", function () { set(50); });
  };
  FilesScreen.prototype.start = function () {
    var self = this;
    NB.api("fs.local.roots").then(function (r) {
      var start = NB.uiState("path-local") || (r.ok ? r.data.home : null);
      self.local.load(start).then(function () { self.local.list.focus({ preventScroll: true }); });
    });
    this.connChanged();
  };
  FilesScreen.prototype.connChanged = function () {
    this.remote.updateHead();
    if (NB.conn.status === "connected" && this.remote.path && this.connId === NB.conn.profile.id) { return; }   // already showing it
    this.connId = NB.conn.status === "connected" ? NB.conn.profile.id : null;
    if (NB.conn.status === "connected") {
      var saved = NB.uiState("path-remote-" + NB.conn.profile.id);
      this.remote.path = null;
      this.remote.load(saved || NB.conn.profile.remote_path || ".");
    } else {
      this.remote.showDisconnected();
    }
  };

  // ---- actions
  FilesScreen.prototype.copyTo = function (from, to) {
    var items = from.selection();
    if (!items.length) { return; }
    if (NB.conn.status !== "connected") { NB.toast("Connect to a server first."); return; }
    if (!to.path) { NB.toast("Open a folder in the other pane first."); return; }
    var paths = items.map(function (it) { return joinPath(from.side, from.path, it[0]); });
    NB.transfer(from.side === "local" ? "upload" : "download", paths, to.path, function () { to.load(null, true); });
  };
  FilesScreen.prototype.mkdir = function (pane) {
    if (!pane.path) { return; }
    NB.prompt({ title: "New folder", label: "Folder name", action: "Create folder" }).then(function (name) {
      if (!name) { return; }
      NB.api("fs." + pane.side + ".mkdir", { folder: pane.path, name: name }).then(function (r) {
        if (!r.ok) { NB.toast(r.error); return; }
        pane.load(null, true).then(function () {
          var i = pane.view.findIndex(function (vi) { return pane.items[vi][0] === name; });
          if (i >= 0) { pane.setFocus(i, "single"); }
          pane.list.focus();
        });
      });
    });
  };
  FilesScreen.prototype.rename = function (pane) {
    var it = pane.item(pane.focus);
    if (!it) { return; }
    NB.prompt({ title: "Rename", label: "New name", value: it[0], action: "Rename" }).then(function (name) {
      if (!name || name === it[0]) { return; }
      NB.api("fs." + pane.side + ".rename", { path: joinPath(pane.side, pane.path, it[0]), name: name }).then(function (r) {
        if (!r.ok) { NB.toast(r.error); return; }
        pane.selected.clear();
        pane.load(null, true);
        pane.list.focus();
      });
    });
  };
  FilesScreen.prototype.remove = function (pane) {
    var items = pane.selection();
    if (!items.length) { return; }
    var where = pane.side === "local" ? "this computer" : pane.label();
    var what = items.length === 1 ? "“" + items[0][0] + "”" : items.length + " items";
    var dirs = items.some(function (it) { return it[1] === "d"; });
    NB.confirm({
      title: "Delete " + what + "?", danger: true, action: "Delete",
      text: "They're deleted from " + where + (dirs ? ", including everything inside the folders" : "") + ". This can't be undone."
    }).then(function (yes) {
      if (!yes) { return; }
      var run = items.reduce(function (p, it) {
        return p.then(function () {
          return NB.api("fs." + pane.side + ".delete", { path: joinPath(pane.side, pane.path, it[0]), recursive: it[1] === "d" })
            .then(function (r) { if (!r.ok) { NB.toast(r.error); } });
        });
      }, Promise.resolve());
      run.then(function () { pane.selected.clear(); pane.load(null, true); pane.list.focus(); });
    });
  };
  FilesScreen.prototype.menu = function (pane, x, y, onItem) {
    var self = this, other = this.other(pane), toLabel = other.side === "remote" ? "Upload to " + other.label() : "Download to this computer";
    var entries = [];
    if (onItem) {
      entries.push(["open", "Open", "Enter"]);
      if (pane.item(pane.focus) && pane.item(pane.focus)[1] === "f") { entries.push(["edit", "Edit in File Bridge"]); }
      if (other.path) { entries.push(["copy", toLabel, "F5"]); }
      entries.push(["rename", "Rename", "F2"], ["delete", "Delete", "Del"], ["-"]);
    }
    entries.push(["mkdir", "New folder", "F7"], ["refresh", "Refresh", "Ctrl R"]);
    if (pane.path && (pane.side === "local" || NB.conn.status === "connected")) { entries.push(["-"], ["term", "Open terminal here"]); }
    NB.contextMenu(x, y, entries, function (a) {
      if (a === "open") { pane.open(pane.focus); }
      else if (a === "copy") { self.copyTo(pane, other); }
      else if (a === "rename") { self.rename(pane); }
      else if (a === "delete") { self.remove(pane); }
      else if (a === "mkdir") { self.mkdir(pane); }
      else if (a === "refresh") { pane.load(null, true); }
      else if (a === "term") { NB.openTerminal(pane.side, pane.path); }
      else if (a === "edit") { var it = pane.item(pane.focus); if (it) { NB.openEditor(pane.side, joinPath(pane.side, pane.path, it[0])); } }
    });
  };

  var screen = null;
  NB.on("conn", function () { if (screen && document.body.contains(screen.el)) { screen.connChanged(); } });
  NB.screens.files = {
    ready: true,
    render: function (el) {
      el.classList.add("screen-files");
      screen = new FilesScreen(el);
      screen.start();
    },
    leave: function () { screen = null; }
  };
})();
