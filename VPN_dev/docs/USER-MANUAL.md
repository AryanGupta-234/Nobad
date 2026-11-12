# NOBAD VPN user manual

NOBAD VPN connects your Windows PC to WireGuard VPN servers. You need a WireGuard configuration file (a `.conf` file,
a link to one, or a QR code) from your VPN provider or from whoever runs your server. NOBAD does not come with servers
of its own.

The app is in English only.

---

## Contents

1. [Installing](#1-installing)
2. [First start: the setup checklist](#2-first-start-the-setup-checklist)
3. [Adding your servers](#3-adding-your-servers)
4. [Connecting and disconnecting](#4-connecting-and-disconnecting)
5. [Choosing a server](#5-choosing-a-server)
6. [Protection: kill switch and DNS leak block](#6-protection-kill-switch-and-dns-leak-block)
7. [Trusted Wi-Fi](#7-trusted-wi-fi)
8. [Streaming tab](#8-streaming-tab)
9. [Network tab (gaming and network health)](#9-network-tab-gaming-and-network-health)
10. [Details tab and usage history](#10-details-tab-and-usage-history)
11. [Tray icon and mini window](#11-tray-icon-and-mini-window)
12. [Network Intelligence (Intel tab)](#12-network-intelligence-intel-tab)
13. [Fix my internet](#13-fix-my-internet)
14. [WireGuard is installed for you](#14-wireguard-is-installed-for-you)
15. [Updates](#15-updates)
16. [Settings at a glance](#16-settings-at-a-glance)
17. [Troubleshooting and FAQ](#17-troubleshooting-and-faq)
18. [Uninstalling](#18-uninstalling)

---

## 1. Installing

1. Run `NobadVPN-Setup-<version>.exe` and accept the Windows administrator prompt. NOBAD needs administrator rights
   because it creates VPN tunnels and firewall rules.
2. Choose the options:
   * **Start NOBAD VPN when I sign in** (recommended, ticked the first time). NOBAD then starts quietly in the tray
     when you sign in, so it opens instantly.
   * **Create a desktop shortcut** (not ticked by default).
3. If WireGuard for Windows is not on your PC yet, Setup installs it silently. It is the official WireGuard program
   that NOBAD uses to run tunnels.
4. At the end you can launch NOBAD VPN.

After installation, opening NOBAD does **not** show a Windows administrator prompt each time; Setup arranges this
once.

If Windows shows "Windows protected your PC", see [the SmartScreen question](#windows-protected-your-pc-smartscreen)
in the FAQ.

---

## 2. First start: the setup checklist

The first time NOBAD opens, a **Set up NOBAD** checklist appears. Each item shows a tick when it is done, or a button
to fix it:

* **WireGuard for Windows**: installed, or a button to install it and a link to the official download page.
* **Administrator rights**: NOBAD should be running as administrator; if not, use *Relaunch as administrator*.
* **A server config**: add your servers from a file, a link, a QR image, by pasting the text, or by opening the
  configs folder.
* **Optional**: switches for the kill switch, the DNS leak block, Start with Windows and the tray icon.

Press **Finish** (or **Skip for now**). You can open the checklist again any time from **Settings → Help → Setup
checklist**.

---

## 3. Adding your servers

Open the **Servers** tab (globe icon at the bottom). You can add configs in several ways:

| Way | How |
|---|---|
| File | **Import .conf** and pick one or more `.conf` files. |
| Drag and drop | Drag `.conf` files (or QR images) onto the Servers tab. |
| QR code | **Import QR image** and pick a screenshot or photo of the QR code. You will be asked for a name. |
| Paste | Copy the config text and press Ctrl+V while the Servers tab is open (or use **Paste config**). A copied QR image can be pasted the same way. |
| Link | **Import from URL** and enter an `https://` link to the `.conf` file. |
| Folder | **Open folder** opens the configs folder; put files there and press **Rescan**. |

Good to know:

* Server names can be 1 to 32 characters: letters, digits and `_ = + . -`.
* NOBAD checks each config and tells you exactly what is wrong if it can't be used.
* For safety, configs from a link or a QR code are refused if they contain commands (`PreUp`, `PostUp`, `PreDown`,
  `PostDown`).
* Your configs are kept in `C:\ProgramData\NobadVPN\configs`, a folder normal programs can't read. They contain your
  private keys, so don't share them.

**Editing a server.** Each server in the list has an **Edit** button. The editor hides your private keys as `(hidden)`
and keeps them unchanged unless you paste a new key. It checks the text as you type. The editor also has **Delete**
(you must disconnect from that server first).

---

## 4. Connecting and disconnecting

* Press **Go** next to a server in the **Servers** list, click a server on the **map**, or press the big **Connect**
  button at the bottom.
  If no server is selected, Connect picks the fastest one.
* Press **Disconnect** (the same button) to stop.
* Keyboard: press **Space** to connect or disconnect (when no text box has focus).

While connected you see your status, the exit IP address (with **Copy** and **Refresh**), latency, jitter, packet
loss, download and upload speed, uptime and live charts.

**Quitting.** In **Settings** you have two buttons:

* **Quit (VPN stays on)**: closes NOBAD but the VPN keeps running. NOBAD reconnects to it next time it opens.
* **Disconnect & quit**: turns the VPN off and closes NOBAD.

Closing the window with the X normally just hides NOBAD in the tray (see [section 11](#11-tray-icon-and-mini-window)).

If the connection drops, NOBAD reconnects by itself (setting *Auto-repair & failover*). After a few failed tries it
moves to another server.

---

## 5. Choosing a server

| Option | What it does |
|---|---|
| **Fastest** | Measures every server and connects to the quickest one. If you are connected, the VPN drops for a moment while it measures. |
| **Smart pick** | Like Fastest, but also uses what NOBAD has learned: which servers are usually fast at this time of day, which ones failed recently, and (if you chose a service to watch) which ones are blocked for that service. |
| **Probe all** | Measures all servers without connecting. |
| **Favourites** | Click the star next to a server. Tick **Favorites** to show only favourites, or sort by *Favorites first*. |
| Search and sort | Type in *Search locations*; sort by best latency, name, or favourites first. |

Ping colours on the map and list: green under 80 ms, amber under 180 ms, red slower.

---

## 6. Protection: kill switch and DNS leak block

### Kill switch (off by default)

The kill switch makes sure your internet traffic can only go through the VPN. If the VPN drops, normal internet is
blocked instead of silently going around the VPN. Your local network (printers, router) keeps working.

* While NOBAD is reconnecting after a drop, sleep or a Wi-Fi change, the kill switch keeps blocking.
* If NOBAD can't reconnect after 8 tries, the normal kill switch lets go and tells you clearly: "VPN is off". You are
  then online **without** the VPN.
* **Strict kill switch** (Settings → Protection) never lets go by itself. You stay offline until you reconnect or
  press **Restore internet**.
* If you see "Kill switch is blocking your internet", press **Restore internet** in the notice to get back online.

### DNS leak block (on by default)

DNS is how your PC looks up website names. Without protection, those lookups could go to your internet provider even
while the VPN is on. The DNS leak block only allows lookups through the VPN while you are connected (even a DNS server
on your own router is blocked).

* If a config has no DNS line, NOBAD adds a fallback DNS (1.1.1.1, 1.0.0.1 by default) to the copy it gives
  WireGuard, so lookups keep working. Your `.conf` file is never changed. If you turn this off, the DNS block is
  skipped for that config and the log says why.
* Encrypted DNS over HTTPS (used by some browsers) is not stopped by the DNS block alone; the kill switch blocks it
  outside the VPN.

### "Protection not enforced"

Both protections are Windows Firewall rules. If Windows Firewall is turned off (sometimes by another security
program), NOBAD shows a red **Protection not enforced** notice with a button to open Windows' firewall settings.

### Hotel and café Wi-Fi (sign-in pages)

If a network needs you to sign in on a web page, the VPN can't connect. NOBAD notices this, shows **Wi-Fi sign-in
required**, pauses the normal kill switch, and offers **Open sign-in page**. After you sign in, NOBAD reconnects by
itself. The strict kill switch never pauses: use **Restore internet** to sign in, then reconnect.

### After a crash or restart

If NOBAD crashes with the kill switch on, a small helper restarts it (*Crash watchdog*). If it can't, you stay
blocked (safest) unless you turned on *Release the kill switch if NOBAD can't restart*. If Windows restarts after such
a crash and nothing else will clean up, a start-up guard restores your internet by itself.

---

## 7. Trusted Wi-Fi

Turn on **Settings → Trusted networks → Use trusted-network rules** to let NOBAD decide by network:

* On a **trusted** network (for example your home Wi-Fi) NOBAD disconnects automatically.
* On any **other** network it connects automatically to your last server.

Add networks with **Trust current network** or by typing a Wi-Fi name (or `Ethernet`). Each automatic choice can be
switched off separately.

If you disconnect by hand, NOBAD respects that until you change network.

On Windows 11 (24H2 and later) the Wi-Fi name may be hidden from apps unless you allow location access
(*Settings → Privacy & security → Location → let desktop apps access your location*). Until then NOBAD shows
"Wi-Fi (name hidden)" and treats every Wi-Fi as **untrusted**, which only ever means more protection.

---

## 8. Streaming tab

* **Run speed test**: downloads up to 8 MB from Cloudflare (at most about 5 seconds) and shows your speed, with
  markers for SD (3 Mbps), HD (8 Mbps) and 4K (25 Mbps).
* **Service reachability → Check**: tests Netflix, YouTube, Disney+, Prime Video, Spotify and Twitch (plus a
  Cloudflare baseline) through your current connection. "Reachable" means the site answered; it doesn't guarantee
  a particular title will play.
* **Watch a streaming service** (Settings → Connection): NOBAD checks your chosen service through the VPN and
  remembers which servers it works on. With *Switch server if it gets blocked*, it moves to a server that still works.

---

## 9. Network tab (gaming and network health)

* **Run network check**: a quick, plain-English check of your router, your internet connection and website name
  lookups. It doesn't change any settings. **Clear DNS cache** empties Windows' saved lookups.
* **VALORANT · Global server check**: response times to VALORANT regions. Mumbai and Singapore use community-reported
  Riot addresses; the other regions use nearby cloud servers as an estimate. Real in-game ping can differ.
* **Test custom**: type any game server address and see ping, packet loss, jitter and a short verdict.

---

## 10. Details tab and usage history

* **Protection check**: a score with up to seven checks (tunnel active, fresh handshake, all traffic routed, IPv6
  covered, DNS inside the tunnel, exit IP differs from your real IP, kill switch armed).
* **Session** and **Exit & protection**: server, endpoint, last handshake, data used, exit IP, location, provider.
* **Recent sessions** and **Usage history**: data downloaded and uploaded per day (last 7 days, 30 days or all
  time), usage by server, speed-test history and a session list. All of this stays on your PC.

---

## 11. Tray icon and mini window

The NOBAD icon in the notification area shows a coloured dot: green connected, amber connecting, red blocked by the
kill switch, grey off.

* **Left-click** opens the **mini window** (Quick view) at the bottom-right: status, a server list, Connect /
  Disconnect, Fastest, Open NOBAD, a kill switch switch and live speeds. It hides when you click elsewhere or press
  Esc.
* **Right-click** menu: Quick view, Open NOBAD, Connect (last server) / Disconnect, Connect to (server list), Fastest
  server, Smart pick, Kill switch, Restore internet (panic reset), Repair network (quick), Quit (VPN keeps running),
  Disconnect and quit.

The tray icon can be turned off in **Settings → Startup & tray**. Without it, the mini window isn't available and
closing the window quits NOBAD.

---

## 12. Network Intelligence (Intel tab)

The **Intel** tab helps you find out why a website doesn't open or what your network is doing. Everything is measured
live on your PC. Nothing is changed unless you ask (or switch on the smart fix agent). Each finding shows its
evidence and how confident NOBAD is (low, medium, high).

| Section | What it shows |
|---|---|
| **Overview** | Your network connection, gateway, DNS servers, whether DNS servers answer properly or invent answers, whether something on the network intercepts DNS, and what changed since this network was last seen. It runs automatically the first time you open the tab; press *Analyze again* to repeat. |
| **Sites** | **Investigate a site**: type a site name (or paste its link). NOBAD compares your network's DNS with independent resolvers and tests the real connection to find where the site is blocked or failing (DNS, site-name filtering, unreachable addresses, "unavailable for legal reasons", broken IPv6). It also tells you whether apps on this PC are really affected, and what to do. |
| **DNS** | Ask every resolver for a name and record types (A, AAAA, CNAME, MX, TXT, NS, SOA) and compare raw answers. |
| **IPv4 / IPv6** | Addresses, routes and DNS for each active network adapter, from the last overview. |
| **VPN** | While connected: checks that IPv4, IPv6 and DNS really go through the tunnel and that nothing leaks around it. |
| **History** | Past results, stored only on this PC. Networks are identified by a code, never by name. **Clear** deletes the history. |

### Smart fix agent

If a site is blocked by your network's DNS, the Sites result may offer **Fix DNS safely**. After you confirm, NOBAD:

1. saves your current DNS settings,
2. switches this network adapter's DNS to an independent resolver that returned the real address,
3. checks the site and several other sites you use, plus your router,
4. undoes the change automatically if anything broke.

You can undo it yourself with **Undo this change**. It is also undone when you leave that network, and by any reset
(Restore internet, Repair, uninstall). NOBAD refuses to change anything when it can't help or could cause trouble,
for example on work/school PCs, when the VPN is connected, or when the network also blocks the site in other ways;
it tells you why.

The **Smart fix agent** switch (on the Sites pane or in *Settings → Network Intelligence*) is **off** by default.
When on, NOBAD may make such fixes by itself (with the same checks), including checking your recent lookups every 30
minutes.

---

## 13. Fix my internet

If web pages stop loading after using a VPN, use these in order. Each asks first and then shows the real result of
every step. They work without internet.

| Option | What it does |
|---|---|
| **1 · Restore internet** | Removes NOBAD's firewall rules, NOBAD tunnels and any DNS change NOBAD made. Windows is back as it was before NOBAD. |
| **2 · Quick repair** | Restore internet, then clears the DNS cache and ARP cache and renews your IP address. Takes seconds; Wi-Fi may blink once. |
| **3 · Full network reset** | Quick repair, then resets Winsock, TCP/IP and proxy settings (like Windows' own network reset). You must restart Windows, and any manually set IP addresses must be entered again. |

Where to find them:

* **Intel tab → Overview**, the *Fix my internet* card (all three).
* **Settings → Protection → Panic reset** and **Settings → Network safety** (Quick repair, Full network reset).
* **Tray menu**: *Restore internet (panic reset)* and *Repair network (quick)*.
* **Start menu → NOBAD VPN → Restore internet (NOBAD)** and **Repair network (NOBAD)**. These work even when NOBAD is
  closed or won't open, ask for administrator rights, and show a message with the result.

---

## 14. WireGuard is installed for you

NOBAD uses the official WireGuard for Windows. Setup installs it if needed. If it is ever removed, NOBAD reinstalls it
by itself at start-up (setting *Reinstall WireGuard automatically*, on by default), first from the copy that came with
NOBAD (works offline), then from the official WireGuard website, then through winget. Every installer must carry
WireGuard's valid digital signature, or it isn't used. A notice shows the progress. You can also press **Install
WireGuard** in the notice or the setup checklist.

---

## 15. Updates

NOBAD can update itself only if an update address has been set in **Settings → Updates → Update manifest URL**
(normally provided by whoever distributes NOBAD to you). Then press **Check now**, or turn on *Check for updates on
launch*. When an update is available a notice offers **Install now**; NOBAD downloads it, checks it, installs it
silently and restarts. The VPN keeps running meanwhile.

For your safety NOBAD only installs an update that is digitally signed by the same publisher as the NOBAD you are
running. A NOBAD build without a digital signature can't verify updates, so it won't install them; download and
install the new version by hand instead.

---

## 16. Settings at a glance

Settings are grouped and have a search box at the top.

| Group | Main settings |
|---|---|
| Protection | Kill switch, DNS leak block, fallback DNS, strict kill switch, crash watchdog, release the kill switch if NOBAD can't restart, Panic reset |
| Network safety | what NOBAD has changed, Quick network repair, Full network reset |
| Network Intelligence | Smart fix agent, local diagnostic history, independent resolvers to compare with |
| Connection | Auto-repair & failover, reconnect after sleep or network changes, streaming-tuned tunnel, connect on launch, smart server choice, watch a streaming service, switch server if blocked |
| Trusted networks | trusted-network rules and the list of trusted networks |
| Startup & tray | Start with Windows, tray icon, close to tray, keep guarding after the window closes, Windows notifications, visual effects |
| Privacy & security | look up my exit IP address, run checks at startup, encrypt stored configs, crash reports, Export diagnostics |
| Updates | reinstall WireGuard automatically, check for updates on launch, update manifest URL |
| Help | Setup checklist |
| Appearance | dark or light mode (also the button at the top right) |

Privacy notes:

* **Look up my exit IP address** is **on** by default. It sends your public IP address to ipinfo.io (and fallback
  services) to show where you appear to be and to place servers on the map. Turn it off for no lookups at all.
* **Run extra checks at startup** is off by default. A quick network check and the IP lookup (if allowed) still run each
  time NOBAD opens.
* **Encrypt stored configs** protects your config files if they are copied, backed up or the disk is stolen. It does
  not protect them from other administrators on this PC.
* **Crash reports** are always saved on your PC and only sent if you turn sending on and a server address is set.

---

## 17. Troubleshooting and FAQ

### My internet doesn't work after closing NOBAD

Usually the kill switch is still blocking. Open NOBAD and press **Restore internet**, or use
**Start menu → NOBAD VPN → Restore internet (NOBAD)**, or the tray item. If pages still don't load, try **Quick
repair**, then **Full network reset** ([section 13](#13-fix-my-internet)).

Remember: **Quit (VPN stays on)** leaves the VPN running on purpose.

### "... never completed a handshake"

NOBAD started the tunnel but the server never answered. Check:

* that the config's keys and server address/port are right (use **Edit config**);
* that your network allows the VPN (use **Check endpoint** to test the server address);
* whether you are on a network with a sign-in page (NOBAD usually detects this);
* try another server.

The notice disappears by itself after a while; **Show log** shows the details.

### "WireGuard for Windows isn't installed"

Press **Install WireGuard** in the notice. If the automatic install fails, use **Open download page** in the setup
checklist and install WireGuard from the official site, then try again.

### "NOBAD needs administrator rights"

Click *Not running as administrator* at the top, or **Relaunch as administrator**.

### "Windows protected your PC" (SmartScreen)

This appears when the installer is not digitally signed, or is signed by a publisher Windows doesn't know well yet.
If you got the installer from a source you trust, click **More info → Run anyway**. Unsigned builds also can't update
themselves (see [section 15](#15-updates)).

### "Protection not enforced"

Windows Firewall is off for at least one network type. Press **Turn on Windows Firewall** in the notice, or check your
other security software.

### The Wi-Fi name shows as "Wi-Fi (name hidden)"

Allow location access for desktop apps in Windows settings ([section 7](#7-trusted-wi-fi)).

### Where are the logs? How do I get help?

Click the line at the bottom of the window to show the log. For support, use **Settings → Privacy & security →
Export diagnostics**: it creates a zip on your Desktop (or in Downloads) with logs and network information. Private
keys are removed, MAC addresses and Wi-Fi names are masked; server addresses and your network's IP addresses are
included, so review it before sharing.

### What does `--selftest` do?

Support may ask you to run `"C:\Program Files\NOBAD VPN\NobadVPN.exe" --selftest` from an administrator command
prompt. It prints what your PC supports.

---

## 18. Uninstalling

Use **Windows Settings → Apps → NOBAD VPN → Uninstall**. The uninstaller first restores your internet (removes
NOBAD's firewall rules, tunnels and DNS changes) so you are never left offline, then removes NOBAD's scheduled tasks
and program files.

It keeps:

* **WireGuard for Windows**, which other programs may use. Uninstall it separately if you want.
* **`C:\ProgramData\NobadVPN`**, which holds your configs (with private keys), settings and history. Delete this folder
  yourself if you want them gone.
