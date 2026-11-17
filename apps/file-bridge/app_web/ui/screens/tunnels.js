// Tunnels: SSH port forwards on the connected server. Local (reach a server port from this computer), reverse
// (let the server reach this computer) and SOCKS (browse through the server). Listening anywhere but this computer
// (or the server's own loopback for reverse) is an explicit, warned choice.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var host = null, data = null, error = null;
  var KINDS = { local: ["Local", "Reach a port on the server from this computer"], remote: ["Reverse", "Let the server reach a port on this computer"],
    socks5: ["SOCKS proxy", "Send apps' traffic through the server"] };

  function load() {
    NB.api("tunnel.list").then(function (r) { if (r.ok) { data = r.data; error = null; } else { error = r.error; } render(); });
  }
  function route(t) {
    if (t.type === "socks5") { return '<span class="mono">' + esc(t.local_host) + ":" + t.local_port + '</span> <span class="faint">→ any address, through the server</span>'; }
    if (t.type === "remote") { return '<span class="faint">server</span> <span class="mono">' + esc(t.remote_host) + ":" + t.remote_port + '</span> <span class="faint">→ this computer</span> <span class="mono">' + esc(t.local_host) + ":" + t.local_port + "</span>"; }
    return '<span class="faint">this computer</span> <span class="mono">' + esc(t.local_host) + ":" + t.local_port + '</span> <span class="faint">→ server</span> <span class="mono">' + esc(t.remote_host) + ":" + t.remote_port + "</span>";
  }
  function card(t) {
    var on = t.status === "active", connected = NB.conn.status === "connected";
    var st = on ? ["ok", "Open"] : t.status === "error" ? ["bad", "Error"] : t.status === "connecting" ? ["busy", "Opening"] : ["", "Closed"];
    return '<article class="card tn-card' + (on ? " on" : "") + '"><div class="tn-top"><div><h2>' + esc(t.name) + '</h2><span class="chip">' + KINDS[t.type][0] + "</span>" +
      (t.allow_lan || t.allow_public ? ' <span class="chip warn">' + ICO("warn") + (t.allow_public ? "Open to anyone" : "Open to your network") + "</span>" : "") +
      (!t.mine ? ' <span class="chip">Another server</span>' : "") + '</div><span class="chip ' + st[0] + '">' + st[1] + "</span></div>" +
      '<p class="tn-route">' + route(t) + "</p>" + (t.description ? '<p class="faint tn-desc">' + esc(t.description) + "</p>" : "") +
      (t.error ? '<p class="banner bad">' + ICO("warn") + "<span>" + esc(t.error) + "</span></p>" : "") +
      '<div class="tn-acts">' + (on ? '<button type="button" class="sm" data-stop="' + esc(t.id) + '">Close</button>' + (t.type !== "remote" ? '<button type="button" class="sm ghost" data-test="' + esc(t.id) + '">Test</button>' : "")
        : '<button type="button" class="sm pri" data-start="' + esc(t.id) + '"' + (connected && t.mine ? "" : " disabled") + ">Open</button>") +
      '<button type="button" class="sm ghost" data-copy="' + esc(t.ssh) + '" title="' + esc(t.ssh) + '">Copy ssh command</button><span class="spacer"></span>' +
      '<button type="button" class="sm ghost" data-edit="' + esc(t.id) + '"' + (on ? " disabled" : "") + '>Edit</button><button type="button" class="sm ghost danger-tx" data-del="' + esc(t.id) + '">Delete</button></div></article>';
  }
  function render() {
    if (!host) { return; }
    var head = '<div class="screen-head"><div><h1>Tunnels</h1><p>Reach databases and internal sites on the server as if they ran on this computer, without opening them to the internet. Tunnels close when you disconnect.</p></div>' +
      '<div class="head-actions"><button type="button" class="pri" data-a="new">' + ICO("plus") + "New tunnel</button></div></div>";
    if (error) { NB.frame(host).innerHTML = head + '<p class="banner warn">' + ICO("warn") + "<span>" + esc(error) + "</span></p>"; return; }
    if (!data) { NB.frame(host).innerHTML = head; return; }
    var presets = '<section class="tn-presets"><b class="faint">Start from</b>' + data.presets.map(function (p) {
      return '<button type="button" class="sm ghost" data-preset="' + esc(p.id) + '">' + esc(p.name) + "</button>"; }).join("") + "</section>";
    NB.frame(host).innerHTML = head + (NB.conn.status !== "connected" ? '<p class="banner info">' + ICO("info") + "<span>Connect to an SSH server to open tunnels.</span></p>" : "") +
      (data.tunnels.length ? '<div class="tn-grid">' + data.tunnels.map(card).join("") + "</div>" :
        '<div class="empty"><div class="empty-ico">' + ICO("tunnel") + "</div><h2>No tunnels yet</h2><p>A tunnel forwards a port through your SSH connection: for example, open the server's PostgreSQL on localhost:5433 for a database app on this computer.</p></div>") + presets;
  }

  function form(t) {
    t = t || { type: "local", name: "", local_host: "127.0.0.1", local_port: 8080, remote_host: "127.0.0.1", remote_port: 80, allow_lan: false, allow_public: false, description: "" };
    var f = document.createElement("form");
    f.className = "conn-form tn-form";
    f.setAttribute("novalidate", "");
    var kind = t.type;
    function paint() {
      f.innerHTML = '<label class="field wide"><span>Name</span><input name="name" autocomplete="off" placeholder="Production database…"></label>' +
        '<div class="field wide"><span id="tnKind">Kind</span><div class="seg" role="radiogroup" aria-labelledby="tnKind">' + Object.keys(KINDS).map(function (k) {
          return '<button type="button" role="radio" data-kind="' + k + '" aria-checked="' + (k === kind) + '">' + KINDS[k][0] + "</button>"; }).join("") + '</div><p class="faint tn-kind">' + KINDS[kind][1] + "</p></div>" +
        '<label class="field"><span>' + (kind === "remote" ? "Address on this computer" : "Listen on (this computer)") + '</span><input name="local_host" class="mono" autocomplete="off" spellcheck="false"></label>' +
        '<label class="field"><span>Port on this computer</span><input name="local_port" type="number" min="1" max="65535"></label>' +
        (kind === "socks5" ? "" : '<label class="field"><span>' + (kind === "remote" ? "Listen on (server)" : "Address seen from the server") + '</span><input name="remote_host" class="mono" autocomplete="off" spellcheck="false"></label>' +
          '<label class="field"><span>Port on the server side</span><input name="remote_port" type="number" min="1" max="65535"></label>') +
        (kind === "remote" ? '<label class="check wide"><input type="checkbox" name="allow_public"><span>Let anyone who can reach the server use it</span></label>'
          : '<label class="check wide"><input type="checkbox" name="allow_lan"><span>Let other devices on my network use it</span></label>') +
        '<p class="faint wide tn-warn">' + (kind === "remote" ? "Off: only programs on the server itself can use the forwarded port." :
          kind === "socks5" ? "Off: only this computer can use the proxy. On would let anyone on your network browse the internet through your server." :
          "Off: only this computer can use the port.") + "</p>" +
        '<label class="field wide"><span>Note <small class="muted">optional</small></span><input name="description" autocomplete="off"></label>' +
        '<p class="form-error wide" role="alert" hidden></p><div class="modal-actions wide"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri">' + (t.id ? "Save" : "Add tunnel") + "</button></div>";
      ["name", "local_host", "local_port", "remote_host", "remote_port", "description"].forEach(function (k) { if (f[k]) { f[k].value = t[k] == null ? "" : t[k]; } });
      if (f.allow_lan) { f.allow_lan.checked = !!t.allow_lan; }
      if (f.allow_public) { f.allow_public.checked = !!t.allow_public; }
    }
    function read() {
      ["name", "local_host", "local_port", "remote_host", "remote_port", "description"].forEach(function (k) { if (f[k]) { t[k] = f[k].value; } });
      if (f.allow_lan) { t.allow_lan = f.allow_lan.checked; }
      if (f.allow_public) { t.allow_public = f.allow_public.checked; }
    }
    paint();
    var m = NB.modal({ title: t.id ? "Edit tunnel" : "New tunnel", body: f, className: "wide", initialFocus: "[name=name]" });
    f.addEventListener("click", function (e) {
      var b = e.target.closest("[data-kind],[data-a=cancel]");
      if (!b) { return; }
      if (b.hasAttribute("data-kind")) { read(); kind = b.getAttribute("data-kind"); t.type = kind; paint(); return; }
      m.close();
    });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      read();
      t.type = kind;
      NB.api("tunnel.save", { tunnel: t }).then(function (r) {
        if (!r.ok) { var er = $(".form-error", f); er.textContent = r.error; er.hidden = false; return; }
        m.close();
        load();
      });
    });
  }
  function preset(id) {
    var p = data.presets.find(function (x) { return x.id === id; });
    if (p) { form({ type: p.tunnel_type, name: p.name, local_host: p.local_host, local_port: p.local_port, remote_host: p.tunnel_type === "socks5" ? "127.0.0.1" : p.remote_host,
      remote_port: p.remote_port, description: p.description }); }
  }

  NB.on("tunnels.changed", function () { if (host) { load(); } });
  NB.on("conn", function () { if (host) { load(); } });

  NB.screens.tunnels = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      load();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-start],[data-stop],[data-test],[data-copy],[data-edit],[data-del],[data-preset]");
        if (!b || b.disabled) { return; }
        var id;
        if ((id = b.getAttribute("data-start"))) {
          b.classList.add("is-busy");
          NB.api("tunnel.start", { id: id }).then(function (r) { b.classList.remove("is-busy"); NB.toast(r.ok ? r.data.message : r.error, r.ok ? "ok" : ""); load(); });
        } else if ((id = b.getAttribute("data-stop"))) { NB.api("tunnel.stop", { id: id }).then(function (r) { if (!r.ok) { NB.toast(r.error); } load(); }); }
        else if ((id = b.getAttribute("data-test"))) { NB.api("tunnel.test", { id: id }).then(function (r) { NB.toast(r.ok ? (r.data.ok ? "Answers in " + r.data.ms + " ms" : r.data.message) : r.error, r.ok && r.data.ok ? "ok" : ""); }); }
        else if (b.hasAttribute("data-copy")) { navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () { NB.toast("Copied the ssh command", "ok"); }); }
        else if ((id = b.getAttribute("data-edit"))) { form(JSON.parse(JSON.stringify(data.tunnels.find(function (x) { return x.id === id; })))); }
        else if ((id = b.getAttribute("data-del"))) {
          var t = data.tunnels.find(function (x) { return x.id === id; });
          NB.confirm({ title: "Delete the tunnel “" + t.name + "”?", danger: true, action: "Delete", text: t.status === "active" ? "It's open now; deleting closes it." : "Only the saved settings are removed." })
            .then(function (yes) { if (yes) { NB.api("tunnel.delete", { id: id }).then(load); } });
        } else if ((id = b.getAttribute("data-preset"))) { preset(id); }
        else if (b.getAttribute("data-a") === "new") { form(null); }
      });
    },
    leave: function () { host = null; }
  };
})();
