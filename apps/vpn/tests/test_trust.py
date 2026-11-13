"""#15: trusted networks need a matching fingerprint, not just a name."""
from nobadvpn import settings, trust
from nobadvpn.netinfo import UNKNOWN_WIFI

W = {"name": "Home", "kind": "wifi", "auth": "WPA2-Personal", "bssid": "aa:bb:cc:dd:ee:01", "gw_mac": None}


def test_record_then_check_and_mesh_access_points():
    ok, fps = trust.record(W, {})
    assert ok and trust.check(W, ["Home"], fps) == ("trusted", "")
    other = dict(W, bssid="aa:bb:cc:dd:ee:02")
    assert trust.check(other, ["Home"], fps)[0] == "unverified"
    ok, fps = trust.record(other, fps)                       # user confirms the second access point
    assert fps["Home"]["bssids"] == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    assert trust.check(W, ["Home"], fps)[0] == trust.check(other, ["Home"], fps)[0] == "trusted"


def test_security_change_resets_access_points():
    _, fps = trust.record(W, {})
    _, fps = trust.record(dict(W, auth="WPA3-Personal", bssid="aa:bb:cc:dd:ee:09"), fps)
    assert fps["Home"] == {"kind": "wifi", "auth": "WPA3-Personal", "bssids": ["aa:bb:cc:dd:ee:09"]}
    assert trust.check(W, ["Home"], fps)[0] == "unverified"


def test_open_hidden_and_unreadable_wifi_are_refused():
    assert not trust.record(dict(W, auth="Open"), {})[0]
    assert not trust.record(dict(W, name=UNKNOWN_WIFI), {})[0]
    assert not trust.record(dict(W, bssid=None), {})[0]
    _, fps = trust.record(W, {})
    assert trust.check(dict(W, auth="Open"), ["Home"], fps)[0] == "untrusted"
    assert trust.check(dict(W, name=UNKNOWN_WIFI), [UNKNOWN_WIFI], fps)[0] == "untrusted"


def test_not_listed_or_removed_is_untrusted():
    _, fps = trust.record(W, {})
    assert trust.check(W, [], fps)[0] == "untrusted"
    assert trust.check(None, ["Home"], fps)[0] == "untrusted"


def test_kind_mismatch_is_unverified():
    _, fps = trust.record(W, {})
    wired = {"name": "Home", "kind": "wired", "auth": None, "bssid": None, "gw_mac": "00:11:22:33:44:55"}
    assert trust.check(wired, ["Home"], fps)[0] == "unverified"
    assert not trust.record(dict(wired, gw_mac=None), {})[0]


def test_fingerprints_are_not_ui_settable_and_cleaned_on_load():
    assert settings.coerce("trusted_fingerprints", {"Home": {}})[0] is False
    dirty = {"Home": {"kind": "wifi", "auth": "WPA2-Personal", "bssids": ["aa:bb:cc:dd:ee:01", "nope", 5]},
             "Open": {"kind": "wifi", "auth": "", "bssids": ["aa:bb:cc:dd:ee:01"]},
             "Eth": {"kind": "wired", "gw_macs": []}, "": {}, "x": "y"}
    assert settings.clean_fingerprints(dirty) == {
        "Home": {"kind": "wifi", "auth": "WPA2-Personal", "bssids": ["aa:bb:cc:dd:ee:01"]}}
    assert settings.clean_fingerprints("junk") == {}


def test_wlan_parse_reads_bssid_and_security():
    from nobadvpn import netinfo as ni
    wlan = ("    Name                   : Wi-Fi\n    State                  : connected\n"
            "    SSID                   : Home 5G\n    AP BSSID               : AA:BB:CC:DD:EE:01\n"
            "    Authentication         : WPA3-Personal\n")
    assert ni.parse_wlan(wlan) == {"ssid": "Home 5G", "bssid": "aa:bb:cc:dd:ee:01", "auth": "WPA3-Personal"}
    assert ni.parse_wlan("There is no wireless interface")["bssid"] is None


def test_arp_parse_finds_router_mac():
    from nobadvpn import netinfo as ni
    out = ("Interface: 192.168.1.50 --- 0xc\n  Internet Address      Physical Address      Type\n"
           "  192.168.1.1           00-11-22-33-44-55     dynamic\n  192.168.1.10          66-77-88-99-aa-bb     dynamic\n")
    assert ni.parse_arp_mac(out, "192.168.1.1") == "00:11:22:33:44:55"
    assert ni.parse_arp_mac(out, "192.168.1.2") is None
    assert ni.parse_arp_mac("  192.168.1.1   ff-ff-ff-ff-ff-ff  static", "192.168.1.1") is None


def test_wifi_without_location_permission_uses_the_router():
    hidden = dict(W, auth=None, bssid=None, gw_mac="00:11:22:33:44:55")
    ok, fps = trust.record(hidden, {})
    assert ok and fps["Home"] == {"kind": "wifi", "gw_macs": ["00:11:22:33:44:55"]}
    assert trust.check(hidden, ["Home"], fps)[0] == "trusted"
    assert trust.check(dict(hidden, gw_mac="de:ad:be:ef:00:01"), ["Home"], fps)[0] == "unverified"
    assert trust.check(dict(hidden, gw_mac=None), ["Home"], fps)[0] == "unverified"


def test_visible_access_point_must_match_even_if_router_does():
    full = dict(W, gw_mac="00:11:22:33:44:55")
    _, fps = trust.record(full, {})
    assert fps["Home"]["bssids"] == ["aa:bb:cc:dd:ee:01"] and fps["Home"]["gw_macs"] == ["00:11:22:33:44:55"]
    assert trust.check(dict(full, bssid="66:66:66:66:66:66"), ["Home"], fps)[0] == "unverified"
    assert trust.check(dict(full, auth=None, bssid=None), ["Home"], fps)[0] == "trusted"   # Location turned off later
    assert trust.check(dict(full, auth="Open", bssid=None), ["Home"], fps)[0] == "untrusted"


def test_cleaned_wifi_entry_keeps_router_and_drops_open_auth():
    raw = {"Home": {"kind": "wifi", "auth": "Open", "bssids": ["aa:bb:cc:dd:ee:01"], "gw_macs": ["00:11:22:33:44:55"]}}
    assert settings.clean_fingerprints(raw) == {"Home": {"kind": "wifi", "gw_macs": ["00:11:22:33:44:55"]}}
