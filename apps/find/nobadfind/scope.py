"""What NOBAD Find indexes: the scope (Whole PC / My files / Custom) and the categories Settings shows.

Maintainer decisions 2026-11-19 (ROADMAP §3):
- Scope: `whole_pc` (your profile and every fixed drive), `my_files` (your profile and your own folders that live
  elsewhere, e.g. Documents moved to D:), `custom` (the folders in `roots`).
- Full transparency: nothing is skipped silently. Every category below is listed by `info()` (the `scope_info`
  method) with what it is, why it matters, examples and whether it's in; the user chooses.
    system          Windows, Program Files, ProgramData, Recovery, PerfLogs          include_system (default on)
    caches          AppData, cache/temp folders, node_modules, .git, venv           include_caches (default on)
    secrets         .ssh, key files, password stores, wallets                       include_secrets (default OFF)
                    NAMES ONLY when on: their content is never read (Rules.names_only, indexer._skip_secrets).
    other_profiles  other people's profiles, recycle bins, System Volume Information   always out (locked)
    removable       USB sticks and SD cards                                           index_removable
    network         mapped network drives                                             index_network
- Other users' profiles are always out: the normal-user walk can't read them anyway, and the elevated turbo helper
  (ntfs.py) could, so it drops them before anything leaves it.

Rules is the one place the walker (walker.Walker), live changes (Walker.excluded) and the turbo helper's filter
(ntfs.Filter) agree on what's in.
"""
import os

from .const import CACHE_NAMES, DEFAULTS, FIXED_NAMES, SECRET_EXT, SECRET_NAMES, SYSTEM_NAMES

SCOPES = ("whole_pc", "my_files", "custom")
CATEGORIES = ("system", "caches", "secrets", "other_profiles", "removable", "network")
SYSTEM_DIRS = ("Windows", "ProgramData", "Recovery", "PerfLogs", "Program Files", "Program Files (x86)")


def setting(s, key):
    """A setting from a Settings object or a plain dict, its default when it's not there."""
    v = s.get(key)
    return DEFAULTS[key] if v is None else v


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def profile_dir():
    return os.path.normpath(os.environ.get("USERPROFILE") or os.path.expanduser("~"))


def system_drive():
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.splitdrive(sysroot)[0] + "\\"


def system_dirs():
    """The system folders, as paths (the Windows folder from SystemRoot, the rest on the same drive)."""
    drive = system_drive()
    out = [os.path.normpath(os.environ.get("SystemRoot", r"C:\Windows"))]
    out += [os.path.join(drive, d) for d in SYSTEM_DIRS[1:]]
    return out


def _under(n, prefix):
    return n == prefix or n.startswith(prefix.rstrip("\\") + "\\")


def other_profiles(registry=None):
    """Profile folders of every other account Windows knows (HKLM ProfileList, readable by every user)."""
    if registry is None:
        registry = _profile_list
    own = norm(profile_dir())
    return sorted({norm(p) for p in registry() if p and norm(p) != own})


def _profile_list():
    try:
        import winreg
    except ImportError:
        return []
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList") as k:
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if not sid.startswith("S-1-5-21-"):           # real accounts; not SYSTEM/LocalService
                    continue
                try:
                    with winreg.OpenKey(k, sid) as sk:
                        out.append(os.path.expandvars(winreg.QueryValueEx(sk, "ProfileImagePath")[0]))
                except OSError:
                    pass
    except OSError:
        pass
    return out


class Rules:
    """Which folders and files are in, from the include_* settings. Paths compare case-insensitively."""

    def __init__(self, system=True, caches=True, secrets=False, profile=None, others=None):
        self.system, self.caches, self.secrets = bool(system), bool(caches), bool(secrets)
        self.profile = norm(profile or profile_dir())
        self.users = os.path.dirname(self.profile)
        self.public = os.path.join(self.users, "public")
        self.others = set(other_profiles() if others is None else (norm(o) for o in others))
        self.system_set = {norm(d) for d in system_dirs()}
        self.appdata = norm(os.path.join(self.profile, "AppData"))

    @classmethod
    def from_settings(cls, s, **kw):
        return cls(system=setting(s, "include_system"), caches=setting(s, "include_caches"),
                   secrets=setting(s, "include_secrets"), **kw)

    @classmethod
    def legacy(cls):
        """0.7.0's skips: no system folders, no caches, no secrets (callers that pass no rules)."""
        return cls(system=False, caches=False, secrets=False)

    # ----- one folder name or file, as the walk meets it -----
    def _name_cat(self, low):
        if low in FIXED_NAMES:
            return "other_profiles"
        if low in SECRET_NAMES:
            return "secrets"
        if low in CACHE_NAMES:
            return "caches"
        if low in SYSTEM_NAMES or low.startswith("$"):
            return "system"
        return None

    def _path_cat(self, n):
        """Category of a folder by where it is (n normcased), or None."""
        if n in self.others or any(_under(n, o) for o in self.others):
            return "other_profiles"
        if os.path.dirname(n) == self.users and n not in (self.profile, self.public):
            return "other_profiles"                     # Default, stale profiles, anyone ProfileList missed
        if n in self.system_set:
            return "system"
        if n == self.appdata:
            return "caches"
        return None

    def _allowed(self, cat):
        return cat is None or (cat == "system" and self.system) or (cat == "caches" and self.caches) or (
            cat == "secrets" and self.secrets)

    def skip_dir(self, path, name, roots=()):
        """True if the walk must not go into this folder. roots: the normcased roots of this walk (a folder that is
        itself a root is walked as that root, so it's skipped where it would come up a second time)."""
        n = norm(path)
        if n in roots:
            return True                                  # walked as its own root
        if not self._allowed(self._name_cat(name.lower())):
            return True
        return not self._allowed(self._path_cat(n))

    def skip_file(self, path):
        return not self.secrets and os.path.splitext(path)[1].lower() in SECRET_EXT

    def category(self, path, base=""):
        """The category a path falls in (by its folders and its name), or None for ordinary files. base: a root the
        user chose that holds path; only what's below it counts (a chosen folder inside AppData is still in)."""
        n = norm(path)
        parts = n.split("\\")
        floor = len(norm(base).rstrip("\\")) if base else 0
        cat = None
        for i in range(1, len(parts) + 1):
            p = "\\".join(parts[:i])
            if len(p) <= max(3, floor):
                continue                                 # "c:" is the drive itself; the root itself is in
            c = self._path_cat(p) or self._name_cat(parts[i - 1])
            if c is not None and _rank(c) > _rank(cat):
                cat = c
        if os.path.splitext(n)[1] in SECRET_EXT and _rank(cat) < _rank("secrets"):
            cat = "secrets"                              # a key file inside a cache folder is still a key file
        return cat

    def out(self, path, base=""):
        """True if a path (from anywhere: a live change, the turbo helper) is outside what these rules allow."""
        cat = self.category(path, base)
        if cat == "secrets":
            return not self.secrets
        return not self._allowed(cat)

    def names_only(self, path):
        """Secrets are indexed by name only: never read their content, whatever else is on."""
        return self.category(path) == "secrets"


def _rank(cat):
    """Strictest wins when a path is in more than one category (a .ssh folder inside AppData is a secret)."""
    return {None: 0, "caches": 1, "system": 2, "secrets": 3, "other_profiles": 4}[cat]


# ---------- roots ----------
def roots_for(s, drives, known=None):
    """The folders to walk for settings s and the drives Windows shows ([{root, type, label}])."""
    if known is None:
        from .winapi import known_folder as known
    prof = profile_dir()
    # settings without a scope (older code, a plain dict) mean what roots meant before: a folder list = Custom
    scope = s.get("scope") or ("custom" if s.get("roots") else "whole_pc")
    if scope == "custom":
        return list(setting(s, "roots") or []) or [prof]
    roots = [prof]

    def add(p):
        if p and not any(_under(norm(p), norm(r)) for r in roots):
            roots.append(os.path.normpath(p))
    if scope == "my_files":
        for name in ("desktop", "documents", "downloads", "pictures", "music", "videos"):
            add(known(name))
    else:
        for d in drives:
            if d["type"] == "fixed" and norm(d["root"]) not in {norm(r) for r in roots}:
                roots.append(d["root"])
    for d in drives:
        if (d["type"] == "removable" and setting(s, "index_removable")) or (
                d["type"] == "network" and setting(s, "index_network")):
            roots.append(d["root"])
    return roots


def derive_changes(changes, current):
    """An older UI only knows `roots`: a folder list means Custom, an empty one Whole PC (unless scope is sent too)."""
    out = dict(changes)
    if "roots" in changes and "scope" not in changes and isinstance(changes["roots"], list):
        if changes["roots"]:
            out["scope"] = "custom"
        elif current.get("scope") == "custom":
            out["scope"] = "whole_pc"
    return out


# ---------- scope_info ----------
def real_case(path):
    """The spelling on disk (the index keeps paths as the walk saw them), or path if it isn't there."""
    parent, name = os.path.split(os.path.normpath(path))
    try:
        with os.scandir(parent) as it:
            for e in it:
                if e.name.lower() == name.lower():
                    return os.path.join(parent, e.name)
    except OSError:
        pass
    return os.path.normpath(path)


def count_under(store, prefixes):
    """Entries in the index at or below these folders (range scans on the path index)."""
    total = 0
    for p in prefixes:
        p = p.rstrip("\\") if len(p) > 3 else p
        base = p if p.endswith("\\") else p + "\\"
        total += store.one("SELECT count(*) FROM files WHERE path = ? OR (path >= ? AND path < ?)",
                           (p, base, base[:-1] + "]")) or 0
    return total


def info(s, drives, store=None, known=None, real_case=real_case, rules=None):
    """scope_info: {scope, roots, categories: [{id, name, why, examples, included, locked, count}]}."""
    rules = rules or Rules.from_settings(s)
    scope = setting(s, "scope")
    roots = roots_for(s, drives, known)
    drive_walked = any(len(norm(r)) <= 3 for r in roots)
    prof = profile_dir()
    sysdirs = [real_case(d) for d in system_dirs()]
    rem = [d["root"] for d in drives if d["type"] == "removable"]
    net = [d["root"] for d in drives if d["type"] == "network"]

    def count(prefixes):
        return count_under(store, prefixes) if store is not None else None

    cats = [
        {"id": "system", "name": "Windows and programs",
         "why": "Windows itself and installed programs: hundreds of thousands of files you rarely look for by name. "
                "Turn off to keep the index small." + ("" if drive_walked else
                                                         " Not part of My files (it only covers your own folders)."),
         "examples": sysdirs[:3] + sysdirs[4:5], "included": rules.system and drive_walked,
         "locked": not drive_walked, "count": count(sysdirs)},
        {"id": "caches", "name": "App data, caches and code folders",
         "why": "Settings and caches apps keep for themselves (AppData), temp folders and developer folders "
                "(node_modules, .git, venv). Lots of small files that change all the time.",
         "examples": [os.path.join(prof, "AppData"), os.path.join(prof, "AppData", "Local", "Temp"),
                      os.path.join("...", "node_modules"), os.path.join("...", ".git")],
         "included": rules.caches, "locked": False, "count": count([real_case(os.path.join(prof, "AppData"))])},
        {"id": "secrets", "name": "Keys and password stores",
         "why": "SSH and GPG keys, certificates, cloud credentials, password manager vaults and wallets. Off by "
                "default. When on, only their names are indexed: NOBAD Find never reads what's inside them.",
         "examples": [os.path.join(prof, ".ssh"), os.path.join(prof, ".aws"),
                      os.path.join("...", "vault.kdbx"), os.path.join("...", "server.pem")],
         "included": rules.secrets, "locked": False, "count": None},
        {"id": "other_profiles", "name": "Other people's files",
         "why": "Other accounts on this PC (their profiles and recycle bins) and Windows' restore points (System "
                "Volume Information) are never indexed, not even by the turbo index: they aren't yours to search.",
         "examples": [os.path.join(os.path.dirname(prof), "<another account>"), os.path.join(
             system_drive(), "$Recycle.Bin"), os.path.join(system_drive(), "System Volume Information")],
         "included": False, "locked": True,
         "count": count([real_case(o) for o in sorted(rules.others)])},
        {"id": "removable", "name": "USB sticks and SD cards",
         "why": "Drives you plug in, indexed while they're connected (re-read every half hour, so Windows can "
                "still eject them).",
         "examples": rem or ["E:\\"], "included": bool(setting(s, "index_removable")) and scope != "custom",
         "locked": scope == "custom", "count": count(rem) if rem else None},
        {"id": "network", "name": "Network drives",
         "why": "Mapped network drives. Slow on big shares, and the names leave your PC's disk only as far as the "
                "share itself.",
         "examples": net or ["Z:\\"], "included": bool(setting(s, "index_network")) and scope != "custom",
         "locked": scope == "custom", "count": count(net) if net else None},
    ]
    return {"scope": scope, "roots": roots, "categories": cats}
