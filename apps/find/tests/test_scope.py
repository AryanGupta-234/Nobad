"""What to index (scope) and the transparent categories: system, caches, secrets, other profiles, removable, network.

Maintainer decisions 2026-11-19 (ROADMAP §3): scope Whole PC / My files / Custom; every category is shown in Settings
and chosen by the user; secrets are names only and off by default; other users' profiles are always out."""
import json
import os

import pytest

from nobadfind import scope, settings as settings_mod
from nobadfind.const import DEFAULTS
from nobadfind.store import Store
from nobadfind.walker import Walker

PROF = os.path.normpath(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
USERS = os.path.dirname(PROF)
SYSROOT = os.path.normpath(os.environ.get("SystemRoot", r"C:\Windows"))
DRIVE = os.path.splitdrive(SYSROOT)[0] + "\\"


# ---------- settings ----------
def test_new_settings_and_defaults():
    assert DEFAULTS["scope"] == "whole_pc"
    assert DEFAULTS["include_system"] is True and DEFAULTS["include_caches"] is True
    assert DEFAULTS["include_secrets"] is False
    assert DEFAULTS["turbo"] is False


def test_scope_coerce():
    for v in ("whole_pc", "my_files", "custom"):
        assert settings_mod.coerce("scope", v) == v
    assert settings_mod.coerce("scope", "everything") == "whole_pc"
    assert settings_mod.coerce("scope", 3) == "whole_pc"
    assert settings_mod.coerce("include_secrets", "yes") is False


@pytest.mark.parametrize("roots,want", [([], "whole_pc"), ([PROF], "custom")])
def test_old_settings_get_a_scope_from_their_roots(tmp_path, roots, want):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"roots": roots, "theme": "light"}), encoding="utf-8")
    assert settings_mod.Settings(str(p)).get("scope") == want


def test_a_saved_scope_wins_over_the_roots(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"roots": [PROF], "scope": "my_files"}), encoding="utf-8")
    assert settings_mod.Settings(str(p)).get("scope") == "my_files"


def test_derived_scope_follows_a_roots_change_from_an_old_ui():
    assert scope.derive_changes({"roots": [PROF]}, {"scope": "whole_pc"}) == {"roots": [PROF], "scope": "custom"}
    assert scope.derive_changes({"roots": []}, {"scope": "custom"}) == {"roots": [], "scope": "whole_pc"}
    # a UI that sends the scope itself decides
    assert scope.derive_changes({"roots": [PROF], "scope": "my_files"}, {"scope": "whole_pc"})["scope"] == "my_files"
    assert scope.derive_changes({"theme": "light"}, {"scope": "custom"}) == {"theme": "light"}


# ---------- rules ----------
def rules(**kw):
    s = dict(DEFAULTS)
    s.update(kw)
    return scope.Rules.from_settings(s)


def test_default_rules_include_system_and_caches_but_not_secrets():
    r = rules()
    assert not r.skip_dir(os.path.join(SYSROOT, "System32"), "System32")
    assert not r.skip_dir(os.path.join(DRIVE, "ProgramData"), "ProgramData")
    assert not r.skip_dir(os.path.join(PROF, "AppData"), "AppData")
    assert not r.skip_dir(os.path.join(PROF, "proj", "node_modules"), "node_modules")
    assert r.skip_dir(os.path.join(PROF, ".ssh"), ".ssh")
    assert r.skip_file(os.path.join(PROF, "keys", "server.pem"))
    assert not r.skip_file(os.path.join(PROF, "notes.txt"))


def test_system_off_skips_windows_programs_and_programdata():
    r = rules(include_system=False)
    for name in ("Windows", "ProgramData", "Recovery", "PerfLogs", "Program Files", "Program Files (x86)"):
        assert r.skip_dir(os.path.join(DRIVE, name), name), name
    assert r.skip_dir(os.path.join(DRIVE, "Windows"), "WINDOWS")       # case doesn't matter
    assert not r.skip_dir(os.path.join(DRIVE, "Projects"), "Projects")


def test_caches_off_skips_appdata_and_cache_names():
    r = rules(include_caches=False)
    assert r.skip_dir(os.path.join(PROF, "AppData"), "AppData")
    for name in ("node_modules", ".git", "__pycache__", "venv", ".venv", "Cache", "Temp", "tmp", "GPUCache"):
        assert r.skip_dir(os.path.join(PROF, "x", name), name), name


def test_secrets_on_lets_their_names_in():
    r = rules(include_secrets=True)
    assert not r.skip_dir(os.path.join(PROF, ".ssh"), ".ssh")
    assert not r.skip_file(os.path.join(PROF, "keys", "server.pem"))
    # names only: the content is never read
    assert r.names_only(os.path.join(PROF, "keys", "server.pem"))
    assert r.names_only(os.path.join(PROF, ".ssh", "config"))
    assert r.names_only(os.path.join(PROF, "AppData", "Roaming", "Bitwarden", "data.json"))
    assert not r.names_only(os.path.join(PROF, "Documents", "data.json"))


def test_other_profiles_are_always_out_even_with_everything_on():
    r = rules(include_system=True, include_caches=True, include_secrets=True)
    assert r.skip_dir(os.path.join(USERS, "SomeoneElse"), "SomeoneElse")
    assert r.skip_dir(os.path.join(USERS, "Default"), "Default")
    assert not r.skip_dir(os.path.join(USERS, "Public"), "Public")
    assert r.out(os.path.join(USERS, "SomeoneElse", "Desktop", "s.txt"))
    assert r.out(os.path.join(DRIVE, "System Volume Information", "x"))
    assert r.out(os.path.join(DRIVE, "$Recycle.Bin", "S-1-5-21-1-2-3-1001", "x.txt"))
    assert not r.out(os.path.join(PROF, "Desktop", "s.txt"))


def test_own_profile_under_users_is_not_walked_twice():
    """Whole PC walks the profile as its own root, so C:\\Users\\me is skipped under C:\\."""
    r = rules()
    assert r.skip_dir(PROF, os.path.basename(PROF), roots={os.path.normcase(PROF)})
    assert not r.skip_dir(PROF, os.path.basename(PROF), roots={os.path.normcase(DRIVE)})


def test_find_own_data_is_never_indexed():
    r = rules(include_caches=True, include_system=True, include_secrets=True)
    assert r.skip_dir(os.path.join(PROF, "AppData", "Local", "NOBAD"), "NOBAD")


# ---------- roots per scope ----------
DRIVES = [{"root": DRIVE, "type": "fixed", "label": "Windows"}, {"root": "D:\\", "type": "fixed", "label": "Data"},
          {"root": "E:\\", "type": "removable", "label": "USB"}, {"root": "Z:\\", "type": "network", "label": ""}]


def test_whole_pc_roots_are_the_profile_and_every_fixed_drive():
    s = dict(DEFAULTS)
    assert scope.roots_for(s, DRIVES, known=lambda n: None) == [PROF, DRIVE, "D:\\"]
    s.update(index_removable=True, index_network=True)
    assert scope.roots_for(s, DRIVES, known=lambda n: None) == [PROF, DRIVE, "D:\\", "E:\\", "Z:\\"]


def test_my_files_is_the_profile_and_your_folders_that_live_elsewhere():
    s = dict(DEFAULTS, scope="my_files")
    moved = {"documents": "D:\\Docs", "pictures": os.path.join(PROF, "Pictures")}
    assert scope.roots_for(s, DRIVES, known=moved.get) == [PROF, "D:\\Docs"]


def test_custom_is_the_folder_list_and_profile_when_empty():
    s = dict(DEFAULTS, scope="custom", roots=["D:\\Work"])
    assert scope.roots_for(s, DRIVES, known=lambda n: None) == ["D:\\Work"]
    s["roots"] = []
    assert scope.roots_for(s, DRIVES, known=lambda n: None) == [PROF]


# ---------- the walker follows the rules ----------
def make_tree(tmp_path):
    root = tmp_path / "r"
    for d in ("docs", "proj/node_modules/lib", ".ssh", "AppData/Local"):
        (root / d).mkdir(parents=True)
    (root / "docs" / "a.txt").write_text("a")
    (root / "proj" / "node_modules" / "lib" / "i.js").write_text("x")
    (root / ".ssh" / "id_rsa").write_text("secret")
    (root / "docs" / "k.pem").write_text("secret")
    return root


def walk(root, **kw):
    seen = []
    Walker([str(root)], gen=1, on_batch=seen.extend, rules=rules(**kw)).run()
    return {os.path.relpath(r[0], root) for r in seen}


def test_walker_with_default_rules_indexes_caches_not_secrets(tmp_path):
    got = walk(make_tree(tmp_path))
    assert os.path.join("proj", "node_modules", "lib", "i.js") in got
    assert os.path.join(".ssh", "id_rsa") not in got and ".ssh" not in got
    assert os.path.join("docs", "k.pem") not in got


def test_walker_without_caches(tmp_path):
    got = walk(make_tree(tmp_path), include_caches=False)
    assert not any("node_modules" in p for p in got)
    assert os.path.join("docs", "a.txt") in got


def test_walker_with_secrets_lists_their_names(tmp_path):
    got = walk(make_tree(tmp_path), include_secrets=True)
    assert os.path.join(".ssh", "id_rsa") in got and os.path.join("docs", "k.pem") in got


def test_walker_excluded_matches_the_walk(tmp_path):
    root = make_tree(tmp_path)
    w = Walker([str(root)], rules=rules(include_caches=False))
    assert w.excluded(str(root / "proj" / "node_modules" / "x.js"))
    assert w.excluded(str(root / ".ssh" / "id_rsa"))
    assert not w.excluded(str(root / "docs" / "b.txt"))
    w2 = Walker([str(root)], rules=rules(include_secrets=True))
    assert not w2.excluded(str(root / ".ssh" / "id_rsa"))
    assert not w2.excluded(str(root / "proj" / "node_modules" / "x.js"))


def test_walker_without_rules_keeps_the_old_skips():
    """Callers that pass no rules (older code paths, tests) keep 0.7.0's behaviour."""
    w = Walker([PROF, DRIVE])
    assert w.excluded(os.path.join(PROF, "AppData", "Local", "x.txt"))
    assert w.excluded(os.path.join(USERS, "SomeoneElse", "Desktop", "s.txt"))


# ---------- scope_info ----------
def test_scope_info_lists_every_category(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    win = SYSROOT
    s.upsert_files([(os.path.join(win, "notepad.exe"), "notepad.exe", win, ".exe", "app", 1, 1.0, 1.0, 1),
                    (os.path.join(win, "System32"), "System32", win, "", "folder", 0, 1.0, 1.0, 1),
                    (os.path.join(PROF, "a.txt"), "a.txt", PROF, ".txt", "text", 1, 1.0, 1.0, 1)])
    st = dict(DEFAULTS)
    info = scope.info(st, DRIVES, s, known=lambda n: None, real_case=lambda p: p)
    assert info["scope"] == "whole_pc" and info["roots"] == [PROF, DRIVE, "D:\\"]
    cats = {c["id"]: c for c in info["categories"]}
    assert list(cats) == ["system", "caches", "secrets", "other_profiles", "removable", "network"]
    for c in cats.values():
        assert c["name"] and c["why"] and isinstance(c["examples"], list) and c["examples"]
        assert isinstance(c["included"], bool) and isinstance(c["locked"], bool)
    assert cats["system"]["included"] and not cats["system"]["locked"] and cats["system"]["count"] == 2
    assert cats["secrets"]["included"] is False and "never" in cats["secrets"]["why"].lower()
    assert cats["other_profiles"] == dict(cats["other_profiles"], included=False, locked=True, count=0)
    assert cats["removable"]["included"] is False and cats["network"]["included"] is False
    s.close()


def test_scope_info_my_files_locks_system_out(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    info = scope.info(dict(DEFAULTS, scope="my_files"), DRIVES, s, known=lambda n: None, real_case=lambda p: p)
    cats = {c["id"]: c for c in info["categories"]}
    assert cats["system"]["included"] is False and cats["system"]["locked"] is True
    s.close()


def test_category_of_a_path():
    r = rules(include_secrets=True)
    assert r.category(os.path.join(DRIVE, "Windows", "x.dll")) == "system"
    assert r.category(os.path.join(PROF, "AppData", "Local", "x")) == "caches"
    assert r.category(os.path.join(PROF, "p", "node_modules", "x.js")) == "caches"
    assert r.category(os.path.join(PROF, ".ssh", "id_rsa")) == "secrets"
    assert r.category(os.path.join(USERS, "Other", "x")) == "other_profiles"
    assert r.category(os.path.join(PROF, "Documents", "x.docx")) is None


def test_finds_own_data_folder_is_never_indexed_wherever_it_is(tmp_path, monkeypatch):
    """NOBAD_FIND_DATA_DIR can point anywhere (measurements use the temp folder): indexing its own database
    writes would feed itself."""
    data = tmp_path / "somewhere" / "data"
    monkeypatch.setattr(scope, "DATA_DIR", str(data))
    r = rules(include_caches=True, include_system=True, include_secrets=True)
    assert r.skip_dir(str(data), "data")
    assert r.out(str(data / "index.db-wal"))
    assert not r.out(str(tmp_path / "somewhere" / "other.txt"))


# ---------- security review of #79: credential stores inside AppData ----------
LOCAL = os.path.join(PROF, "AppData", "Local")
ROAMING = os.path.join(PROF, "AppData", "Roaming")
CHROME = os.path.join(LOCAL, "Google", "Chrome", "User Data", "Default")
FIREFOX = os.path.join(ROAMING, "Mozilla", "Firefox", "Profiles", "abcd.default-release")
CREDENTIAL_STORES = [
    os.path.join(CHROME, "Login Data"), os.path.join(CHROME, "Login Data-journal"), os.path.join(CHROME, "Cookies"),
    os.path.join(CHROME, "Network", "Cookies"), os.path.join(CHROME, "History"), os.path.join(CHROME, "Web Data"),
    os.path.join(LOCAL, "Google", "Chrome", "User Data", "Local State"),
    os.path.join(LOCAL, "Microsoft", "Edge", "User Data", "Default", "Login Data"),
    os.path.join(LOCAL, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cookies"),
    os.path.join(ROAMING, "Opera Software", "Opera Stable", "Login Data"),
    os.path.join(FIREFOX, "key4.db"), os.path.join(FIREFOX, "logins.json"), os.path.join(FIREFOX, "cookies.sqlite"),
    os.path.join(FIREFOX, "places.sqlite"), os.path.join(FIREFOX, "formhistory.sqlite"),
    os.path.join(ROAMING, "Microsoft", "Credentials", "DFBE70A7E5CC19A398EBF1B96859CE5D"),
    os.path.join(LOCAL, "Microsoft", "Vault", "4BF4C442-9B8A-41A0-B380-DD4A704DDB28", "Policy.vpol"),
    os.path.join(ROAMING, "Microsoft", "Protect", "S-1-5-21-1-2-3-1001", "Preferred"),
    os.path.join(PROF, "Documents", "vault.kdbx"), os.path.join(PROF, "Documents", "export.1pux"),
    os.path.join(ROAMING, "discord", "Local Storage", "leveldb", "000005.ldb"),
    os.path.join(ROAMING, "Slack", "Local Storage", "leveldb", "000003.log"),
    os.path.join(ROAMING, "Microsoft", "Teams", "Local Storage", "leveldb", "000003.log"),
    os.path.join(PROF, ".npmrc"), os.path.join(PROF, ".pypirc"), os.path.join(PROF, ".netrc"),
    os.path.join(PROF, ".git-credentials"), os.path.join(PROF, ".config", "gcloud", "credentials.db"),
    os.path.join(PROF, ".aws", "credentials"), os.path.join(PROF, ".azure", "msal_token_cache.json"),
    os.path.join(ROAMING, "Bitcoin", "wallets", "wallet.dat"), os.path.join(ROAMING, "Exodus", "exodus.wallet"),
]


@pytest.mark.parametrize("path", CREDENTIAL_STORES)
def test_credential_stores_are_secrets_even_with_caches_on(path):
    r = rules(include_caches=True, include_system=True, include_secrets=False)
    assert r.category(path) == "secrets", path
    assert r.out(path), path


@pytest.mark.parametrize("path", CREDENTIAL_STORES)
def test_credential_stores_are_names_only_when_secrets_are_on(path):
    r = rules(include_caches=True, include_secrets=True)
    assert not r.out(path) and r.names_only(path), path


def test_ordinary_files_with_similar_names_are_not_secrets():
    r = rules()
    for p in (os.path.join(PROF, "Documents", "History of Rome.docx"), os.path.join(PROF, "Documents", "cookies.txt"),
              os.path.join(PROF, "Documents", "Vault", "plan.docx"), os.path.join(PROF, "Music", "Protect.mp3"),
              os.path.join(PROF, "Documents", "Credentials", "letter.docx")):
        assert r.category(p) is None and not r.names_only(p), p


def test_browser_profile_databases_never_reach_text_extraction():
    """SQLite and LevelDB files in browser profiles are binary noise: names only even with every switch on."""
    r = rules(include_caches=True, include_secrets=True)
    for p in (os.path.join(CHROME, "Favicons"), os.path.join(CHROME, "IndexedDB", "x.leveldb", "000003.log"),
              os.path.join(CHROME, "Sync Data", "LevelDB", "000004.ldb"), os.path.join(FIREFOX, "storage.sqlite"),
              os.path.join(FIREFOX, "prefs.js"), os.path.join(LOCAL, "Some App", "data", "state.sqlite"),
              os.path.join(LOCAL, "Some App", "cache.db")):
        assert not r.out(p) and r.names_only(p), p
    assert not r.names_only(os.path.join(PROF, "Documents", "notes.txt"))


def test_walker_skips_secret_files_by_name(tmp_path):
    root = tmp_path / "r"
    prof = root / "Google" / "Chrome" / "User Data" / "Default"
    prof.mkdir(parents=True)
    (prof / "Login Data").write_text("x")
    (prof / "Preferences").write_text("x")
    (root / ".npmrc").write_text("x")
    (root / "Login Data").write_text("x")                     # outside a browser: an ordinary file
    rel = os.path.join("Google", "Chrome", "User Data", "Default")
    got = walk(root)
    assert os.path.join(rel, "Preferences") in got and "Login Data" in got
    assert os.path.join(rel, "Login Data") not in got and ".npmrc" not in got
    assert os.path.join(rel, "Login Data") in walk(root, include_secrets=True)


def test_scope_info_names_the_credential_stores(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    cats = {c["id"]: c for c in scope.info(dict(DEFAULTS), DRIVES, s, known=lambda n: None,
                                          real_case=lambda p: p)["categories"]}
    why = cats["secrets"]["why"]
    for word in ("Login Data", "Cookies", "History", "key4.db", "logins.json", "Credentials", ".npmrc", "wallet"):
        assert word in why, word
    assert any("Login Data" in e for e in cats["secrets"]["examples"])
    assert "never reads" in cats["caches"]["why"]                   # browser databases: names only
    s.close()
