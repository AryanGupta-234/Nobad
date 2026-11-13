import time

from nobadvpn import settings as st, smart as sm, usage as us
from nobadvpn.const import DEFAULTS


def test_settings_migrate_from_legacy(tmp_path):
    legacy = tmp_path / "tunnel_settings.json"
    legacy.write_text('{"kill_switch": true, "last_region": "Home", "bogus": 1}')
    new = tmp_path / "ProgramData" / "settings.json"
    s = st.Settings(str(new), str(legacy))
    assert s.get("kill_switch") is True and s.get("last_region") == "Home"
    assert s.get("settings_version") == DEFAULTS["settings_version"]
    assert s.get("wizard_done") is True               # existing users skip the wizard
    assert new.exists() and s.get("dns_leak_block") is True  # new defaults filled in
    assert "bogus" not in new.read_text()


def test_settings_validation():
    assert st.coerce("kill_switch", 1) == (True, True)
    assert st.coerce("nope", 1)[0] is False
    assert st.coerce("language", "en")[0] is False      # English only: there is no language setting
    assert st.coerce("update_url", "http://x")[0] is False
    assert st.coerce("fallback_dns", "1.1.1.1,not-an-ip")[0] is False
    assert st.coerce("fallback_dns", "1.1.1.1,  9.9.9.9") == (True, "1.1.1.1, 9.9.9.9")
    assert st.coerce("trusted_networks", ["Home", "Home", " ", "Cafe"]) == (True, ["Home", "Cafe"])
    assert st.coerce("dpapi_runtime_ok", True)[0] is False   # internal flag is not user-settable


def test_usage_totals_and_history(tmp_path):
    u = us.Usage(str(tmp_path / "usage.json"))
    now = time.time()
    u.add_delta("A", 1000, 500, 10, ts=now)
    u.add_delta("A", 1000, 500, 10, ts=now - 86400 * 3)
    u.add_delta("B", 10, 10, 1, ts=now - 86400 * 40)
    u.log_session({"name": "A", "start": int(now), "secs": 20, "rx": 2000, "tx": 1000, "avg_bps": 1, "peak_bps": 2})
    u.add_speed(88.5, "A")
    u.save(force=True)
    u2 = us.Usage(str(tmp_path / "usage.json"))
    s7, s30, sall = u2.summary(7), u2.summary(30), u2.summary(0)
    assert s7["totals"]["rx"] == 2000 and s7["totals"]["sessions"] == 1
    assert s30["totals"]["rx"] == 2000 and sall["totals"]["rx"] == 2010
    assert sall["servers"][0]["name"] == "A" and s7["speed"][0]["mbps"] == 88.5


def test_usage_imports_legacy_sessions(tmp_path):
    legacy = tmp_path / "sessions.json"
    legacy.write_text('[{"name":"A","start":1700000000,"secs":60,"rx":10,"tx":5}]')
    u = us.Usage(str(tmp_path / "usage.json"), str(legacy))
    assert u.summary(0)["totals"]["rx"] == 10 and len(u.recent()) == 1


def test_smart_prefers_time_block_and_skips_blocked(tmp_path):
    s = sm.Smart(str(tmp_path / "smart.json"))
    morning = time.mktime((2026, 11, 11, 9, 0, 0, 0, 0, -1))
    evening = time.mktime((2026, 11, 11, 21, 0, 0, 0, 0, -1))
    for _ in range(5):
        s.record_latency("Fast-AM", 30, morning)
        s.record_latency("Fast-AM", 200, evening)
        s.record_latency("Fast-PM", 200, morning)
        s.record_latency("Fast-PM", 30, evening)
    assert s.rank(["Fast-AM", "Fast-PM"], morning)[0][0] == "Fast-AM"
    assert s.rank(["Fast-AM", "Fast-PM"], evening)[0][0] == "Fast-PM"
    s.record_service("Fast-PM", "netflix", False, evening)
    ranked = [n for n, _ in s.rank(["Fast-AM", "Fast-PM"], evening, service="netflix")]
    assert ranked == ["Fast-AM"]                         # blocked server excluded for that service only
    assert "Fast-PM" in [n for n, _ in s.rank(["Fast-AM", "Fast-PM"], evening)]
    assert s.is_blocked("Fast-PM", "netflix", evening + 3600)
    assert not s.is_blocked("Fast-PM", "netflix", evening + 90000)   # expires after 24 h


def test_smart_failure_penalty_and_persistence(tmp_path):
    p = str(tmp_path / "smart.json")
    s = sm.Smart(p)
    s.record_latency("A", 50)
    s.record_latency("B", 60)
    s.record_result("A", False)
    s.record_result("A", False)
    assert s.rank(["A", "B"])[0][0] == "B"
    assert sm.Smart(p).rank(["A", "B"])[0][0] == "B"
