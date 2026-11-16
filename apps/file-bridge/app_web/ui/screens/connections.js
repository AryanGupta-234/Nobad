// Connections: saved servers and the new-connection form (paste an ssh command or fill in the fields).
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var DEFAULT_PORT = { sftp: 22, ssh: 22, ftp: 21, ftps: 21 };

  function card(p) {
    var current = NB.conn.status === "connected" && NB.conn.profile && NB.conn.profile.id === p.id;
    return '<article class="card conn-card' + (current ? " current" : "") + '" data-id="' + esc(p.id) + '">' +
      '<div class="conn-top"><span class="conn-ico">' + ICO("servers") + '</span><div class="conn-id"><h3>' + esc(p.name) + "</h3>" +
      '<p class="mono">' + esc(p.username + "@" + p.host + ":" + p.port) + "</p></div>" +
      '<span class="chip ' + (p.insecure ? "warn" : "acc") + '">' + esc(p.protocol.toUpperCase()) + "</span></div>" +
      '<p class="conn-meta muted">' + esc(p.auth_type === "ssh_key" ? "SSH key" : p.auth_type === "ssh_agent" ? "SSH agent" : "Password") +
      (p.secret_saved ? " · saved in your system keychain" : "") + (p.remote_path && p.remote_path !== "." ? " · opens " + p.remote_path : "") + "</p>" +
      '<div class="conn-actions">' + (current
        ? '<button type="button" data-a="files" class="pri">' + ICO("files") + "Open files</button><button type=\"button\" data-a=\"disconnect\">Disconnect</button>"
        : '<button type="button" data-a="connect" class="pri">' + ICO("arrow") + "Connect</button>") +
      '<button type="button" class="icon ghost sm" data-a="more" aria-label="More for ' + esc(p.name) + '">' + ICO("more") + "</button></div></article>";
  }

  function render(el) {
    NB.api("conn.profiles").then(function (r) {
      var list = r.ok ? r.data : [];
      var grid = $(".conn-grid", el);
      if (!grid) { return; }
      if (!list.length) {
        grid.innerHTML = '<div class="card"><div class="empty"><div class="empty-ico">' + ICO("servers") + "</div><h2>No saved servers yet</h2>" +
          "<p>Add one with New connection. Tick “Save this connection” to find it here next time.</p></div></div>";
        return;
      }
      grid.innerHTML = list.map(card).join("");
      $$(".conn-card", grid).forEach(function (c) {
        var p = list.find(function (x) { return x.id === c.getAttribute("data-id"); });
        c.addEventListener("click", function (e) {
          var b = e.target.closest("[data-a]");
          if (!b) { return; }
          var a = b.getAttribute("data-a");
          if (a === "connect") { NB.connectSaved(p, b); }
          else if (a === "files") { NB.go("files"); }
          else if (a === "disconnect") { NB.disconnect(); }
          else if (a === "more") {
            var r2 = b.getBoundingClientRect();
            NB.contextMenu(r2.left, r2.bottom + 4, [["rename", "Rename"], ["delete", "Delete"]], function (x) {
              if (x === "rename") {
                NB.prompt({ title: "Rename connection", label: "Name", value: p.name, action: "Rename" }).then(function (n) {
                  if (n) { NB.api("conn.rename", { id: p.id, name: n }).then(function (res) { if (!res.ok) { NB.toast(res.error); } render(el); }); }
                });
              } else {
                NB.confirm({ title: "Delete “" + p.name + "”?", danger: true, action: "Delete",
                  text: "The saved connection and its saved password are removed from this computer. Nothing changes on the server." })
                  .then(function (yes) { if (yes) { NB.api("conn.delete", { id: p.id }).then(function (res) { if (!res.ok) { NB.toast(res.error); } render(el); }); } });
              }
            });
          }
        });
      });
    });
  }

  // ---- new connection form
  function form() {
    var f = document.createElement("form");
    f.className = "conn-form";
    f.setAttribute("novalidate", "");
    f.innerHTML =
      '<label class="field wide"><span>Paste a server address <small class="muted">optional</small></span>' +
        '<input name="paste" type="text" placeholder="ssh -p 2222 deploy@example.com or sftp://user@host…" autocomplete="off" spellcheck="false"></label>' +
      '<div class="field wide"><span id="protoLabel">Protocol</span><div class="seg" role="radiogroup" aria-labelledby="protoLabel" data-name="protocol">' +
        ["sftp", "ssh", "ftps", "ftp"].map(function (p, i) {
          return '<button type="button" role="radio" data-value="' + p + '" aria-checked="' + (i === 0) + '" tabindex="' + (i === 0 ? 0 : -1) + '">' + p.toUpperCase() + "</button>";
        }).join("") + "</div></div>" +
      '<label class="field grow"><span>Host</span><input name="host" type="text" required placeholder="example.com…" autocomplete="off" spellcheck="false"></label>' +
      '<label class="field port"><span>Port</span><input name="port" type="number" min="1" max="65535" value="22" inputmode="numeric"></label>' +
      '<label class="field wide"><span>Username</span><input name="username" type="text" required autocomplete="username" spellcheck="false" placeholder="deploy…"></label>' +
      '<div class="field wide ssh-only"><span id="authLabel">Sign in with</span><div class="seg" role="radiogroup" aria-labelledby="authLabel" data-name="auth_type">' +
        '<button type="button" role="radio" data-value="password" aria-checked="true" tabindex="0">Password</button>' +
        '<button type="button" role="radio" data-value="ssh_key" aria-checked="false" tabindex="-1">SSH key</button>' +
        '<button type="button" role="radio" data-value="ssh_agent" aria-checked="false" tabindex="-1">SSH agent</button></div></div>' +
      '<label class="field wide key-only" hidden><span>Private key file</span><span class="input-row"><input name="key_path" type="text" placeholder="C:\\Users\\you\\.ssh\\id_ed25519…" spellcheck="false" autocomplete="off">' +
        '<button type="button" data-a="pick-key">Browse…</button></span></label>' +
      '<label class="field wide secret"><span class="secret-label">Password</span><input name="secret" type="password" autocomplete="current-password"></label>' +
      '<label class="field wide"><span>Open this server folder <small class="muted">optional</small></span><input name="remote_path" type="text" placeholder="/var/www…" spellcheck="false" autocomplete="off"></label>' +
      '<div class="field wide checks"><label class="check"><input type="checkbox" name="save" checked><span>Save this connection</span></label>' +
        '<label class="check"><input type="checkbox" name="remember"><span>Remember the password in your system keychain</span></label></div>' +
      '<p class="form-error" role="alert" hidden></p>' +
      '<div class="modal-actions"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri" id="connectBtn">' + ICO("arrow") + "Connect</button></div>";
    return f;
  }
  function segValue(f, name) { var b = f.querySelector('.seg[data-name="' + name + '"] [aria-checked=true]'); return b ? b.getAttribute("data-value") : null; }
  function setSeg(f, name, value) {
    $$('.seg[data-name="' + name + '"] [role=radio]', f).forEach(function (b) {
      var on = b.getAttribute("data-value") === value;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    });
  }
  function sync(f) {
    var proto = segValue(f, "protocol"), auth = segValue(f, "auth_type"), ssh = proto === "sftp" || proto === "ssh";
    $$(".ssh-only", f).forEach(function (x) { x.hidden = !ssh; });
    var useKey = ssh && auth === "ssh_key";
    f.querySelector(".key-only").hidden = !useKey;
    f.querySelector(".secret").hidden = ssh && auth === "ssh_agent";
    f.querySelector(".secret-label").textContent = useKey ? "Key passphrase (if it has one)" : "Password";
    f.secret.autocomplete = useKey ? "off" : "current-password";
    f.remember.nextElementSibling.textContent = useKey ? "Remember the passphrase in your system keychain" : "Remember the password in your system keychain";
  }

  function openForm() {
    var f = form();
    var m = NB.modal({ title: "New connection", sub: "Host keys are checked before the first login.", body: f, className: "wide", initialFocus: "[name=host]" });
    var portTouched = false;
    f.port.addEventListener("input", function () { portTouched = true; });
    $$(".seg", f).forEach(function (seg) {
      var radios = $$("[role=radio]", seg);
      seg.addEventListener("click", function (e) {
        var b = e.target.closest("[role=radio]");
        if (!b) { return; }
        setSeg(f, seg.getAttribute("data-name"), b.getAttribute("data-value"));
        if (seg.getAttribute("data-name") === "protocol" && !portTouched) { f.port.value = DEFAULT_PORT[b.getAttribute("data-value")]; }
        sync(f);
      });
      seg.addEventListener("keydown", function (e) {
        var i = radios.indexOf(document.activeElement);
        if (i < 0 || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) { return; }
        e.preventDefault();
        var next = radios[(i + (e.key === "ArrowRight" ? 1 : radios.length - 1)) % radios.length];
        next.click();
        next.focus();
      });
    });
    f.paste.addEventListener("change", function () {
      if (!f.paste.value.trim()) { return; }
      NB.api("conn.parse", { text: f.paste.value }).then(function (r) {
        if (!r.ok) { error(r.error); return; }
        var d = r.data;
        if (d.protocol && DEFAULT_PORT[d.protocol]) { setSeg(f, "protocol", d.protocol); }
        if (d.host) { f.host.value = d.host; }
        if (d.username) { f.username.value = d.username; }
        f.port.value = d.port || DEFAULT_PORT[segValue(f, "protocol")];
        portTouched = !!d.port;
        sync(f);
        error("");
        (f.username.value ? f.secret : f.username).focus();
      });
    });
    f.querySelector("[data-a=pick-key]").addEventListener("click", function () {
      NB.api("window.pick", { kind: "file" }).then(function (r) {
        if (r.ok && r.data.paths.length) { f.key_path.value = r.data.paths[0]; }
        else if (r.ok && !r.data.available) { f.key_path.focus(); NB.toast("Type the key file's path (no file picker in browser mode)."); }
      });
    });
    f.querySelector("[data-a=cancel]").addEventListener("click", function () { m.close(); });
    function error(text) { var e = f.querySelector(".form-error"); e.textContent = text; e.hidden = !text; }
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var proto = segValue(f, "protocol");
      if (!f.host.value.trim() || !f.username.value.trim()) { error("Enter the host and the username."); (f.host.value.trim() ? f.username : f.host).focus(); return; }
      var go = function () {
        var body = {
          profile: { protocol: proto, host: f.host.value, port: f.port.value, username: f.username.value,
                     auth_type: proto === "ftp" || proto === "ftps" ? "password" : segValue(f, "auth_type"),
                     key_path: f.key_path.value, remote_path: f.remote_path.value },
          secret: f.secret.value, save: f.save.checked, remember: f.remember.checked
        };
        NB.api("conn.connect", body).then(function (r) {
          if (!r.ok) { error(r.error); return; }
          f.secret.value = "";
          m.close();
          NB.toast("Connecting to " + f.host.value.trim() + "…", "ok");
        });
      };
      if (proto === "ftp") { NB.confirmInsecure().then(function (yes) { if (yes) { go(); } }); } else { go(); }
    });
    sync(f);
  }
  NB.newConnection = openForm;

  NB.screens.connections = {
    ready: true,
    render: function (el, _screen, opts) {
      el.innerHTML = '<div class="screen-head"><div><h1>Connections</h1><p>Your saved servers. Passwords stay in your system keychain, never in File Bridge\'s database.</p></div>' +
        '<button type="button" class="pri" id="newConn">' + ICO("plus") + "New connection</button></div>" +
        '<div class="conn-grid"><div class="card"><div class="skel" style="height:14px;width:50%"></div></div></div>';
      $("#newConn", el).addEventListener("click", openForm);
      render(el);
      var off = function () { if (document.body.contains(el)) { render(el); } };
      NB.on("conn", off);
      NB.on("profiles_changed", off);
      if (opts && opts.create) { openForm(); }
    }
  };
})();
