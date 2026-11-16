// Connection state for the whole page: status pill, host-key prompt, password prompt, connect/fail feedback.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  NB.conn = { status: "disconnected", profile: null, label: "" };

  function pill() {
    var p = $("#connPill"), c = NB.conn;
    p.classList.toggle("on", c.status === "connected");
    p.classList.toggle("wait", c.status === "connecting");
    var text = c.status === "connected" ? c.profile.name : c.status === "connecting" ? "Connecting to " + c.label + "…" : "Not connected";
    p.innerHTML = '<span class="dot"></span><span class="pill-t"></span>' +
      (c.status === "connected" ? '<button type="button" class="pill-x" id="pillDisconnect" aria-label="Disconnect from ' + esc(c.profile.name) + '" title="Disconnect">' + ICO("close") + "</button>" : "");
    p.querySelector(".pill-t").textContent = text;
    p.title = c.status === "connected" ? c.label : "";
    var x = $("#pillDisconnect");
    if (x) { x.addEventListener("click", NB.disconnect); }
  }
  NB.disconnect = function () {
    NB.api("conn.disconnect").then(function (r) { if (!r.ok) { NB.toast(r.error); } });
  };

  function setState(s, initial) {
    var was = NB.conn.status;
    NB.conn = { status: s.status, profile: s.profile || null, label: s.label || "" };
    pill();
    NB.emit("conn", NB.conn);
    if (!initial && was !== "connected" && s.status === "connected") {
      NB.toast("Connected to " + s.profile.name, "ok");
      if (location.hash !== "#/files") { NB.go("files"); }
    }
  }
  NB.on("connection", function (s) { setState(s, false); });
  NB.on("conn_failed", function (p) {
    var body = document.createElement("div");
    body.innerHTML = (p.fix ? '<p class="muted"></p>' : "") +
      '<div class="modal-actions"><button type="button" data-a="log">Show activity</button><button type="button" class="pri" data-a="ok">OK</button></div>';
    if (p.fix) { body.querySelector("p").textContent = p.fix; }
    var m = NB.modal({ title: "Couldn't connect", sub: p.message, body: body, initialFocus: "[data-a=ok]" });
    body.querySelector("[data-a=ok]").addEventListener("click", m.close);
    body.querySelector("[data-a=log]").addEventListener("click", function () { m.close(); NB.setDock(true, "activity"); });
  });

  // ---- host key: unknown = ask; changed = warn hard, Cancel is the default
  var askedTokens = {};
  NB.on("hostkey", function (p) {
    if (askedTokens[p.token]) { return; }      // the same question via the event and the start-up state
    askedTokens[p.token] = true;
    var body = document.createElement("div");
    body.className = "hostkey";
    body.innerHTML =
      '<dl class="kv"><dt>Server</dt><dd class="mono" data-f="server"></dd><dt>Key type</dt><dd class="mono" data-f="alg"></dd>' +
      '<dt>Fingerprint</dt><dd class="mono fp" data-f="fp"></dd>' + (p.changed ? '<dt>Trusted before</dt><dd class="mono fp" data-f="prev"></dd>' : "") + "</dl>" +
      '<p class="muted" data-f="hint"></p>' +
      '<div class="modal-actions"><button type="button" data-a="no">' + (p.changed ? "Cancel" : "Don't connect") + "</button>" +
      '<button type="button" class="' + (p.changed ? "danger" : "pri") + '" data-a="yes">' + (p.changed ? "Replace key and connect" : "Trust and connect") + "</button></div>";
    var f = function (k) { return body.querySelector('[data-f="' + k + '"]'); };
    f("server").textContent = p.host + ":" + p.port + (p.address && p.address !== p.host ? "  (" + p.address + ")" : "");
    f("alg").textContent = p.algorithm;
    f("fp").textContent = p.fingerprint;
    if (p.changed) { f("prev").textContent = (p.previous || []).join("\n") || "Not available"; }
    f("hint").textContent = p.changed
      ? "This server's identity changed since you last connected. That happens when a server is rebuilt, but it can also mean someone is intercepting the connection. Check the new fingerprint with your hosting provider before you replace it."
      : "Compare this fingerprint with the one your hosting provider or server admin gives you. Trust it only if they match.";
    var answered = false;
    var m = NB.modal({
      title: p.changed ? "The server's host key changed" : "Trust this server?",
      sub: p.changed ? "File Bridge didn't connect." : "This is the first time File Bridge connects to " + p.host + ".",
      body: body, className: p.changed ? "modal-danger" : "", initialFocus: "[data-a=no]",
      onClose: function () { if (!answered) { send(false); } }
    });
    function send(accept) {
      answered = true;
      NB.api("conn.trust", { token: p.token, accept: accept }).then(function (r) { if (!r.ok) { NB.toast(r.error); } });
    }
    body.querySelector("[data-a=no]").addEventListener("click", function () { send(false); m.close(); });
    body.querySelector("[data-a=yes]").addEventListener("click", function () { send(true); m.close(); });
  });

  // ---- secret prompt (saved profile without a saved password)
  NB.askSecret = function (title, label) {
    return new Promise(function (resolve) {
      var body = document.createElement("form");
      body.innerHTML = '<label class="field"><span></span><input type="password" name="secret" autocomplete="current-password" required></label>' +
        '<div class="modal-actions"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri">Connect</button></div>';
      body.querySelector("span").textContent = label;
      var done = false;
      var m = NB.modal({ title: title, body: body, initialFocus: "input", onClose: function () { if (!done) { resolve(null); } } });
      body.addEventListener("submit", function (e) { e.preventDefault(); done = true; var v = body.secret.value; m.close(); resolve(v); });
      body.querySelector("[data-a=cancel]").addEventListener("click", function () { m.close(); });
    });
  };

  NB.confirmInsecure = function () {
    return NB.confirm({ title: "FTP isn't encrypted", danger: true, action: "Connect anyway",
      text: "Your password and files travel over the network as plain text. Use SFTP or FTPS if the server offers it." });
  };
  NB.connectSaved = function (profile, button) {
    if (profile.insecure) {
      NB.confirmInsecure().then(function (yes) { if (yes) { go(null); } });
      return;
    }
    go(null);
    function go(secret) {
      var body = { id: profile.id };
      if (secret != null) { body.secret = secret; }
      NB.api("conn.connect_saved", body).then(function (r) {
        if (!r.ok) { NB.toast(r.error); return; }
        if (r.data.needs) {
          NB.askSecret("Connect to " + profile.name, r.data.needs === "password" ? "Password for " + profile.username + "@" + profile.host : "Key passphrase")
            .then(function (s) { if (s != null) { go(s); } });
          return;
        }
        if (button) { NB.task("conn.connect", button, "Connecting…"); }
      });
    }
  };

  document.addEventListener("DOMContentLoaded", function () {
    pill();
    NB.api("conn.state").then(function (r) {
      if (!r.ok) { return; }
      setState(r.data, true);
      if (r.data.hostkey) { NB.emit("hostkey", r.data.hostkey); }
    });
  });
})();
