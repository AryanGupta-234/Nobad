// Screens that are still being rebuilt for the new window. Each says plainly what it will do and where to do it
// today (the classic window), so nothing here claims a feature that isn't there yet.
(function () {
  "use strict";
  var NB = window.NB, esc = NB.esc;

  var PLANS = {
    files: {
      title: "Your files, side by side",
      text: "This computer on the left, the server on the right. Drag between them, or press F5 to copy and F6 to move.",
      parts: [["files", "Dual-pane browser", "Fast lists for folders with 100,000+ files, full keyboard control."],
              ["transfer", "Transfer queue", "Speed, progress and time left, with pause, retry and cancel."],
              ["warn", "Conflicts, your choice", "Overwrite, skip, rename or compare before anything is replaced."]]
    },
    connections: {
      title: "Saved servers",
      text: "SSH, SFTP, FTP and FTPS connections, with host keys checked before the first login.",
      parts: [["plus", "New connection", "Paste an ssh command or fill in host, user and key."],
              ["servers", "Saved profiles", "Passwords stay in your system keychain, never in the database."],
              ["check", "Host key checks", "Unknown servers ask first; a changed key is refused."]]
    },
    terminal: { title: "Terminal tabs", text: "Shells on the server or on this computer, next to your files.", parts: [["terminal", "Tabs", "Open one per server or folder, and reconnect when the link drops."]] },
    editor: { title: "Edit files on the server", text: "A code editor with syntax colours and a side-by-side diff before you upload.", parts: [["code", "Compare before saving", "See exactly what changes, and get warned if the file changed on the server."]] },
    sync: { title: "Two-way sync", text: "Keep a local folder and a server folder in step, with a preview of every change first.", parts: [["sync", "Dry run first", "A table of what would be copied, deleted or needs your decision."]] },
    deploy: { title: "Deployments", text: "Build, back up, upload and check your site in one run, with one-click rollback.", parts: [["deploy", "Health checks", "The deploy only counts when the site answers as expected."]] },
    vault: { title: "Credential vault", text: "API keys, passwords and notes, encrypted with your master password (Argon2id + AES-GCM).", parts: [["vault", "Locked by default", "Nothing is readable until you unlock it."]] },
    dashboard: { title: "Server health", text: "CPU, memory, disk and the busiest processes on the connected server.", parts: [] },
    services: { title: "Services", text: "Start, stop and read the logs of systemd services.", parts: [] },
    tunnels: { title: "SSH tunnels", text: "Forward ports to and from the server.", parts: [] },
    logs: { title: "Live logs", text: "Follow log files and journald units as they are written.", parts: [] },
    playbooks: { title: "Playbooks", text: "Run ready-made maintenance scripts and your own snippets, with live output.", parts: [] }
  };

  // Decorative sketch of the dual-pane layout (aria-hidden: the text above already says what it is).
  function bridgePreview() {
    function pane(title, cls, rows) {
      return '<div class="bp-pane ' + cls + '"><div class="bp-head">' + ICO(cls === "remote" ? "servers" : "window") + "<span>" + title +
        "</span></div>" + rows.map(function (w, i) {
          return '<div class="bp-row' + (i === 1 ? " sel" : "") + '">' + ICO(i < 2 ? "files" : "code") + '<span class="bp-bar" style="width:' + w + '%"></span>' +
            '<span class="bp-size"></span></div>';
        }).join("") + "</div>";
    }
    return '<div class="bridge-preview" aria-hidden="true">' + pane("This computer", "local", [62, 48, 70, 40, 55]) +
      '<div class="bp-link">' + ICO("transfer") + "</div>" + pane("example.com", "remote", [52, 66, 44, 58, 36]) + "</div>";
  }

  NB.screens.__upcoming = {
    render: function (el, screen) {
      var plan = PLANS[screen.id] || { title: screen.label, text: "", parts: [] };
      el.innerHTML =
        '<div class="screen-head"><div><h1>' + esc(screen.label) + "</h1></div></div>" +
        '<div class="card' + (screen.id === "files" ? " hero" : "") + '"><div class="empty"><div class="empty-ico">' + ICO(screen.icon) + "</div>" +
        "<h2>" + esc(plan.title) + "</h2><p>" + esc(plan.text) + "</p>" +
        '<p class="faint">This screen is being rebuilt for the new window and arrives in a later update. Until then, use it in the classic window: <code>python -m app.main</code>.</p>' +
        '<div class="actions"><button class="pri" type="button" data-go="settings">' + ICO("settings") + "Open Settings</button>" +
        '<button type="button" data-palette>' + ICO("search") + "Search <kbd>Ctrl</kbd><kbd>K</kbd></button></div></div>" +
        (screen.id === "files" ? bridgePreview() : "") + "</div>" +
        (plan.parts.length ? '<div class="plan-list">' + plan.parts.map(function (p) {
          return '<div class="card flat"><h3>' + ICO(p[0]) + esc(p[1]) + "</h3><p>" + esc(p[2]) + "</p></div>";
        }).join("") + "</div>" : "");
      el.querySelector("[data-go]").addEventListener("click", function () { NB.go("settings"); });
      el.querySelector("[data-palette]").addEventListener("click", function () { NB.palette.open(); });
    }
  };
})();
