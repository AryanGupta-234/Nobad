from nobadvpn import watchdog as wd
from nobadvpn.netwatch import NetWatch, RESUME_GAP


class FakeTunnel:
    def __init__(self):
        self.want = True
        self.connected = True
        self.connecting = None
        self.events = []
        self.disconnected = []

    def tunnel_ips(self):
        return ["10.2.0.2"]

    def on_network_event(self, kind, fp, reason):
        self.events.append((kind, bool(fp), reason))

    def region_names(self):
        return ["Home"]

    def has_region(self, n):
        return n == "Home"

    def disconnect(self, manual=True):
        self.disconnected.append(manual)

    def connect(self, name):
        self.events.append(("connect", name))


class FakeSettings(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make(fps, names=None, **s):
    clock, t = Clock(), FakeTunnel()
    it = iter(fps)
    cur = {"v": None}

    def fp(_ips):
        try:
            cur["v"] = next(it)
        except StopIteration:
            pass
        return cur["v"]
    nw = NetWatch(t, FakeSettings(s), clock=clock, fp_fn=fp, name_fn=lambda: names, use_events=False)
    return nw, t, clock


def drain(nw):
    import time
    time.sleep(0.05)  # on_network_event is spawned on a thread


WIFI = frozenset({("v4", "192.168.1.1", "192.168.1.50")})
ETH = frozenset({("v4", "10.0.0.1", "10.0.0.20")})


def test_no_event_when_network_stable():
    nw, t, c = make([WIFI, WIFI, WIFI])
    nw.tick(); c.t += 5; nw.tick(); c.t += 5; nw.tick()
    drain(nw)
    assert t.events == []


def test_wifi_to_ethernet_triggers_reconnect():
    nw, t, c = make([WIFI, ETH])
    nw.tick(); c.t += 5
    assert nw.tick() == "change"
    drain(nw)
    assert t.events == [("change", True, "network changed")]


def test_network_lost_is_reported_as_offline():
    nw, t, c = make([WIFI, frozenset()])
    nw.tick(); c.t += 5
    nw.tick()
    drain(nw)
    assert t.events == [("change", False, "network lost")]


def test_resume_detected_by_clock_jump():
    nw, t, c = make([WIFI, WIFI])
    nw.tick()
    c.t += RESUME_GAP + 600          # laptop slept for 10 minutes
    assert nw.tick() == "resume"
    drain(nw)
    assert t.events and t.events[0][0] == "resume"


def test_idle_gap_is_not_a_resume():
    nw, t, c = make([WIFI, WIFI])
    nw.tick(need_tick=False); c.t += 3600
    assert nw.tick(need_tick=False) is None


HOME = {"name": "Home Wi-Fi", "kind": "wifi", "auth": "WPA2-Personal", "bssid": "aa:bb:cc:dd:ee:01", "gw_mac": None}
HOME_FP = {"Home Wi-Fi": {"kind": "wifi", "auth": "WPA2-Personal", "bssids": ["aa:bb:cc:dd:ee:01"]}}


def test_trusted_network_disconnects_and_untrusted_connects():
    nw, t, c = make([WIFI, ETH], names="Home Wi-Fi", ssid_rules=True, trusted_networks=["Home Wi-Fi"],
                    trusted_fingerprints=HOME_FP, autodisconnect_trusted=True, autoconnect_untrusted=True,
                    last_region="Home")
    nw.ident_fn = lambda: HOME
    assert nw.evaluate_rules("test") == "disconnect"
    drain(nw)
    assert t.disconnected == [False]
    t.connected = False
    nw.ident_fn = lambda: dict(HOME, name="Airport")
    assert nw.evaluate_rules("test") == "connect"
    drain(nw)
    assert ("connect", "Home") in t.events


def test_evil_twin_with_trusted_name_stays_protected(monkeypatch):
    """#15: same SSID but another access point, other security or unreadable: not trusted, the VPN connects."""
    import nobadvpn.netwatch as nwmod
    told = []
    monkeypatch.setattr(nwmod, "notify", lambda *a, **k: told.append(a))
    for twin in (dict(HOME, bssid="66:66:66:66:66:66"), dict(HOME, auth="Open"), dict(HOME, auth="WPA2-Enterprise"),
                 dict(HOME, bssid=None)):
        nw, t, c = make([WIFI], names="x", ssid_rules=True, trusted_networks=["Home Wi-Fi"],
                        trusted_fingerprints=HOME_FP, autodisconnect_trusted=True, autoconnect_untrusted=True,
                        last_region="Home")
        nw.ident_fn = lambda twin=twin: twin
        assert nw.evaluate_rules("test") != "disconnect" and not t.disconnected
        t.connected = False
        assert nw.evaluate_rules("test") == "connect"
    assert told


def test_name_only_entry_needs_confirming(monkeypatch):
    import nobadvpn.netwatch as nwmod
    monkeypatch.setattr(nwmod, "notify", lambda *a, **k: None)
    nw, t, c = make([WIFI], names="Home Wi-Fi", ssid_rules=True, trusted_networks=["Home Wi-Fi"],
                    autodisconnect_trusted=True)
    nw.ident_fn = lambda: HOME
    assert nw.evaluate_rules("test") is None and not t.disconnected
    assert nw.pending and nw.pending["name"] == "Home Wi-Fi"


def test_wired_network_is_identified_by_router(monkeypatch):
    import nobadvpn.netwatch as nwmod
    monkeypatch.setattr(nwmod, "notify", lambda *a, **k: None)
    eth = {"name": "Ethernet", "kind": "wired", "auth": None, "bssid": None, "gw_mac": "00:11:22:33:44:55"}
    fp = {"Ethernet": {"kind": "wired", "gw_macs": ["00:11:22:33:44:55"]}}
    nw, t, c = make([ETH], names="Ethernet", ssid_rules=True, trusted_networks=["Ethernet"],
                    trusted_fingerprints=fp, autodisconnect_trusted=True)
    nw.ident_fn = lambda: eth
    assert nw.evaluate_rules("test") == "disconnect"
    nw2, t2, _ = make([ETH], names="Ethernet", ssid_rules=True, trusted_networks=["Ethernet"],
                      trusted_fingerprints=fp, autodisconnect_trusted=True)
    nw2.ident_fn = lambda: dict(eth, gw_mac="de:ad:be:ef:00:01")      # someone else's office or hotel cable
    assert nw2.evaluate_rules("test") is None and not t2.disconnected


def test_manual_disconnect_is_respected_until_network_changes():
    nw, t, c = make([WIFI], names="Cafe", ssid_rules=True, trusted_networks=[], autoconnect_untrusted=True,
                    last_region="Home")
    t.connected = False
    nw.note_manual_disconnect()
    assert nw.evaluate_rules("x") is None


def test_watchdog_decisions():
    d = wd.decide
    assert d(True, True, False, 0, False) == "exit"           # clean exit: never interfere
    assert d(False, False, False, 0, False) == "exit"         # crashed while idle: nothing to protect
    assert d(False, True, False, 0, False) == "relaunch"
    assert d(False, True, False, 3, False) == "stay_blocked"  # default: fail closed
    assert d(False, True, False, 3, True) == "failopen"       # only when the user opted in
    assert d(False, True, True, 0, False) == "relaunch"       # tunnel still up: just restore monitoring
