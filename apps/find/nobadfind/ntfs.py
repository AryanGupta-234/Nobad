"""The optional turbo index: an elevated helper that reads NTFS's own file list and change journal.

Maintainer decision 2026-11-19 (ROADMAP §3): an optional elevated helper, OFF by default (setting `turbo`). It
reverses "never elevated" for this one helper only. The walker (walker.py) and folder notifications (watcher.py)
stay the fallback: UAC declined, a drive that isn't NTFS, any error.

What it does
- `NobadFind.exe --turbo serve`, started by the engine with ShellExecuteW "runas" (one UAC prompt per engine run),
  exactly like wsearch.helper_main. It accepts the fixed words in WORDS and nothing else from its command line.
- Per fixed NTFS drive in the scope: FSCTL_ENUM_USN_DATA lists every MFT entry (file reference number, parent,
  name, attributes) in two passes (folders first, so paths resolve with only the folder tree in memory), then
  FSCTL_GET_NTFS_FILE_RECORD gives each kept entry's size and times from its MFT record ($STANDARD_INFORMATION,
  $DATA). Where the record can't say (the $DATA attribute lives in an attribute list), it asks Windows for that one
  file (OpenFileById + GetFileInformationByHandleEx). It reads metadata only, never a file's contents.
- Then it follows the drive's change journal (FSCTL_QUERY_USN_JOURNAL / FSCTL_READ_USN_JOURNAL) from the next USN,
  once a second, and sends the paths that changed. The engine looks at each changed path again as the normal user.
  A journal that was deleted, reset or wrapped past the saved USN (plan_scan, JournalLost) means a full read again.
- After an engine restart it catches up from the USN the engine saved (if the journal is the same one and still
  holds that USN) instead of reading the whole drive again.
- Lifetime: one helper per engine run (one UAC prompt per session, the option the maintainer preferred). It ends when
  the engine ends: the engine puts it in its kill-on-close job where Windows allows that, and the helper itself
  waits on the engine's process handle and on the pipe, and exits when either goes.

Privacy (why an elevated reader doesn't leak more than the normal walk would show)
An administrator can read every folder's names, including other people's. The helper therefore drops, before
anything leaves it:
- other users' profiles: every ProfileImagePath in HKLM ProfileList except the engine user's own, and every folder
  directly in the profiles folder except the user's own profile and Public (Default, stale profiles);
- System Volume Information (restore points) and every $Recycle.Bin (other users' deleted files are in there);
- NTFS's own metafiles ($MFT, $LogFile... at the drive root);
- anything outside the scope and categories the user chose (scope.Rules, Filter), and the user's excluded folders;
- folders the user couldn't list as themselves: each folder's security descriptor is checked with AccessCheck against
  the ENGINE USER's token (cached per descriptor), so a folder only an administrator may open keeps its name (the
  normal walk sees that too) but not its contents. A failing check counts as "no" (fail closed).
The user's identity comes from Windows, never from the engine's messages: the SID of the pipe server process's token,
and that SID's profile from HKLM ProfileList. The engine's config can only narrow what is sent (roots, exclusions,
category switches); the hard drops above don't depend on it. The engine then applies its own rules again to every
record (turbo.Turbo._rows: Walker.excluded) and reads file contents only in its normal-user workers.

The pipe
- The ENGINE is the server: `\\\\.\\pipe\\NOBADFind-turbo-<user SID>-<engine pid>`, DACL for that user's SID only
  (network logons denied), one instance, FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_REJECT_REMOTE_CLIENTS.
- The engine checks the client is the process its ShellExecuteEx started (GetNamedPipeClientProcessId) in its own
  session (GetNamedPipeClientSessionId). The helper checks the server is its parent process (the process that asked
  for elevation), runs the same program (QueryFullProcessImageNameW), in the same session
  (GetNamedPipeServerSessionId), and the pipe name carries that process's own token SID.
- The helper opens the pipe with SECURITY_IDENTIFICATION, so the engine (and anything pretending to be it) can't
  impersonate the elevated helper.
- Messages: one JSON object per line, ASCII, capped at MAX_LINE (Lines). The helper accepts only `config`, `scan`
  and `stop`; every field is checked (parse_config, parse_drive, parse_since). Paths from the engine are only ever
  compared as strings, never opened.
"""
import ctypes
import json
import os
import re
import struct
import sys
import threading
import time
from collections import namedtuple
from ctypes import wintypes

from . import scope, winapi

WORDS = ("serve", "selftest")
PROTOCOL = 1
MAX_LINE = 8 * 1024 * 1024
ROWS_PER_MESSAGE = 1000
FOLLOW_EVERY = 1.0                       # seconds between looks at the change journal
EPOCH = 116444736000000000               # FILETIME of 1970-01-01
ROOT_FRN = (5 << 48) | 5                 # the root folder's MFT record (5) with its usual sequence number (5)
DIR = 0x10                               # FILE_ATTRIBUTE_DIRECTORY
REPARSE = 0x400
R_CREATE, R_DELETE = 0x100, 0x200
R_RENAME_OLD, R_RENAME_NEW = 0x1000, 0x2000
R_CLOSE = 0x80000000
METAFILES = {"$mft", "$mftmirr", "$logfile", "$volume", "$attrdef", "$bitmap", "$boot", "$badclus", "$secure",
             "$upcase", "$extend"}
DRIVE_RE = re.compile(r"^[A-Za-z]:\\$")
SID_RE = re.compile(r"^S-1-5-21-\d+-\d+-\d+-\d+$")

OUT, ABOVE, IN, SHUT = 0, 1, 2, 3        # Filter states of a folder (SHUT: its name is in, its contents aren't)


# ---------- USN records (FSCTL_ENUM_USN_DATA, FSCTL_READ_USN_JOURNAL) ----------
class UsnRecord(namedtuple("UsnRecord", "frn parent usn timestamp reason attrs name")):
    __slots__ = ()

    @property
    def is_dir(self):
        return bool(self.attrs & DIR)


_V2 = struct.Struct("<IHHQQqqIIIIHH")        # 60 bytes before the name
_V3_TAIL = struct.Struct("<qqIIIIHH")        # after the two 128-bit ids


def parse_usn_buffer(buf, n):
    """(first 8 bytes as a number, [UsnRecord]) from an ENUM_USN_DATA / READ_USN_JOURNAL output buffer. Broken
    records end the parse; nothing in the buffer can make it read outside it or loop."""
    if n < 8:
        return 0, []
    mv = memoryview(buf)[:n]
    nxt = struct.unpack_from("<Q", mv, 0)[0]
    out, off = [], 8
    while off + 8 <= n:
        length, major = struct.unpack_from("<IH", mv, off)
        if length < _V2.size or off + length > n:
            break
        if major == 2:
            (_l, _ma, _mi, ref, parent, usn, ts, reason, _src, _sec, attrs, nlen, noff) = _V2.unpack_from(mv, off)
        elif major == 3 and length >= 76:
            ref = int.from_bytes(mv[off + 8:off + 24], "little")
            parent = int.from_bytes(mv[off + 24:off + 40], "little")
            usn, ts, reason, _src, _sec, attrs, nlen, noff = _V3_TAIL.unpack_from(mv, off + 40)
        else:
            break
        if noff + nlen <= length and nlen % 2 == 0 and noff >= (60 if major == 2 else 76):
            name = bytes(mv[off + noff:off + noff + nlen]).decode("utf-16-le", "replace")
            out.append(UsnRecord(ref, parent, usn, ts, reason, attrs, name))
        off += length
    return nxt, out


# ---------- MFT file records (FSCTL_GET_NTFS_FILE_RECORD) ----------
FileRecord = namedtuple("FileRecord", "in_use is_dir size mtime ctime")


def filetime(v):
    return None if not v or v <= 0 else (v - EPOCH) / 1e7


def unpack_record_output(out, n):
    """NTFS_FILE_RECORD_OUTPUT_BUFFER -> (file reference number, record bytes), or (None, b"")."""
    if n < 12:
        return None, b""
    ref, length = struct.unpack_from("<qI", out, 0)
    if 12 + length > n:
        return None, b""
    return ref, bytes(out[12:12 + length])


def parse_file_record(rec):
    """FileRecord from one MFT record (update sequence fixups applied), or None if it isn't a sound record.
    size is None when the unnamed $DATA attribute isn't in this record (it's in an attribute list)."""
    n = len(rec)
    if n < 48 or rec[:4] != b"FILE":
        return None
    usa_off, usa_count = struct.unpack_from("<HH", rec, 4)
    if usa_count < 1 or usa_off < 40 or usa_off + 2 * usa_count > n or (usa_count - 1) * 512 > n:
        return None
    b = bytearray(rec)
    usn = b[usa_off:usa_off + 2]
    for i in range(1, usa_count):
        end = i * 512 - 2
        if b[end:end + 2] != usn:
            return None                          # a torn write: don't trust any of it
        b[end:end + 2] = b[usa_off + 2 * i:usa_off + 2 * i + 2]
    first, flags, in_use_bytes = struct.unpack_from("<HHI", b, 20)
    limit = min(n, in_use_bytes or n)
    off = first
    size = fn_size = None
    mtime = ctime = None
    has_list = False
    while off + 16 <= limit:
        kind, length = struct.unpack_from("<II", b, off)
        if kind == 0xFFFFFFFF or length < 16 or off + length > limit:
            break
        nonres, name_len = b[off + 8], b[off + 9]
        if not nonres and off + 24 <= limit:
            vlen, voff = struct.unpack_from("<IH", b, off + 16)
            v = off + voff
            if voff >= 24 and v + vlen <= off + length:
                if kind == 0x10 and vlen >= 32:
                    c, m = struct.unpack_from("<qq", b, v)
                    ctime, mtime = filetime(c), filetime(m)
                elif kind == 0x80 and name_len == 0:
                    size = vlen
                elif kind == 0x30 and vlen >= 66:
                    fn_size = struct.unpack_from("<q", b, v + 48)[0]
                elif kind == 0x20:
                    has_list = True
        elif nonres and off + 64 <= limit:
            if kind == 0x80 and name_len == 0:
                start_vcn = struct.unpack_from("<q", b, off + 16)[0]
                if start_vcn == 0:
                    size = struct.unpack_from("<q", b, off + 48)[0]
            elif kind == 0x20:
                has_list = True
        off += length
    is_dir = bool(flags & 2)
    if size is None and not has_list:
        size = fn_size if fn_size is not None else 0     # no $DATA here and no list: $FILE_NAME's copy, or empty
    if is_dir:
        size = 0
    return FileRecord(bool(flags & 1), is_dir, size, mtime, ctime)


# ---------- the folder tree ----------
class Tree:
    """Folders of one drive by file reference number, for paths. Only folders are kept (files are resolved through
    their parent as they come), so a drive of a million files needs only its ~200 000 folders in memory."""

    MAX_DEPTH = 512

    def __init__(self, drive, root=ROOT_FRN):
        self.drive = drive if drive.endswith("\\") else drive + "\\"
        self.root = root
        self.dirs = {}
        self._paths = {root: self.drive}

    def add_dir(self, ref, parent, name):
        old = self.dirs.get(ref)
        if old is not None and old != (parent, name):
            self._paths = {self.root: self.drive}        # a rename or a move: paths below it changed
        self.dirs[ref] = (parent, name)

    def remove(self, ref):
        if self.dirs.pop(ref, None) is not None:
            self._paths = {self.root: self.drive}

    def path(self, ref):
        p = self._paths.get(ref)
        if p is not None:
            return p
        chain, cur = [], ref
        while cur not in self._paths:
            d = self.dirs.get(cur)
            if d is None or len(chain) > self.MAX_DEPTH:
                return None                              # an orphan (deleted parent) or a loop
            chain.append((cur, d[1]))
            cur = d[0]
            if cur == ref:
                return None
        base = self._paths[cur]
        for c, name in reversed(chain):
            base = base + name if base.endswith("\\") else base + "\\" + name
            self._paths[c] = base
        return base

    def child(self, parent, name):
        p = self.path(parent)
        if p is None:
            return None
        return p + name if p.endswith("\\") else p + "\\" + name


# ---------- the privacy filter ----------
def _norm(p):
    return os.path.normcase(os.path.normpath(p))


class Filter:
    """What the helper may send: scope.Rules (other profiles and Windows' private folders always out, the user's
    categories), the roots and exclusions, and can_list(path) -> bool: could the user list this folder themselves.
    Decided once per folder (memo by reference number)."""

    def __init__(self, rules, roots, exclude=(), can_list=None):
        self.rules = rules
        self.roots = {_norm(r) for r in roots}
        self.exclude = {_norm(e) for e in exclude}
        self.can_list = can_list
        self._state = {}

    def forget(self):
        self._state = {}

    def _hard_out(self, n, name):
        low = name.lower()
        if os.path.dirname(n) == n[:3] and (low in METAFILES):
            return True
        return self.rules.skip_dir(n, name) and self.rules.category(n) == "other_profiles"

    def _listable(self, path):
        if self.can_list is None:
            return True
        try:
            return bool(self.can_list(path))
        except Exception:
            return False                                 # fail closed

    def _decide(self, path, name, parent_state):
        n = _norm(path)
        if parent_state in (OUT, SHUT) or self._hard_out(n, name):
            return OUT
        if any(n == e or n.startswith(e.rstrip("\\") + "\\") for e in self.exclude):
            return OUT
        if n in self.roots:
            state = IN
        elif parent_state == IN:
            state = OUT if self.rules.skip_dir(n, name) else IN
        elif any(r.startswith(n.rstrip("\\") + "\\") for r in self.roots):
            return ABOVE                                 # on the way to a root: walked through, not sent
        else:
            return OUT
        return state if self._listable(path) else SHUT

    def dir_state(self, tree, ref):
        s = self._state.get(ref)
        if s is not None:
            return s
        if ref == tree.root:
            n = _norm(tree.drive)
            s = IN if n in self.roots else ABOVE if any(r.startswith(n) for r in self.roots) else OUT
            if s == IN and not self._listable(tree.drive):
                s = SHUT
        else:
            d = tree.dirs.get(ref)
            path = tree.path(ref)
            if d is None or path is None:
                s = OUT
            else:
                s = self._decide(path, d[1], self.dir_state(tree, d[0]))
        self._state[ref] = s
        return s

    def keep_dir(self, tree, ref):
        """The folder's path if its name may be sent (its parent is in, it is in or shut), else None."""
        d = tree.dirs.get(ref)
        if d is None or self.dir_state(tree, d[0]) != IN or self.dir_state(tree, ref) not in (IN, SHUT):
            return None
        p = tree.path(ref)
        return None if p is None or _norm(p) in self.roots else p

    def keep_file(self, tree, parent, name):
        if self.dir_state(tree, parent) != IN:
            return None
        if parent == tree.root and name.lower() in METAFILES:
            return None
        if self.rules.skip_file(name):
            return None
        return tree.child(parent, name)


def apply_changes(tree, flt, records):
    """Journal records -> the paths the engine should look at again (in order, once each). Folders update the tree;
    a folder deleted or renamed away gives its old path (the engine forgets what was below it)."""
    out, seen = [], set()

    def emit(p):
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    for r in records:
        if r.is_dir:
            if r.reason & (R_DELETE | R_RENAME_OLD):
                emit(flt.keep_dir(tree, r.frn))
                if r.reason & R_DELETE:
                    tree.remove(r.frn)
                    flt.forget()
                continue
            tree.add_dir(r.frn, r.parent, r.name)
            flt.forget()
            emit(flt.keep_dir(tree, r.frn))
        else:
            emit(flt.keep_file(tree, r.parent, r.name))
    return out


# ---------- the change journal ----------
Journal = namedtuple("Journal", "journal_id first_usn next_usn lowest_valid")


class JournalLost(Exception):
    """The journal was deleted, reset or wrapped past what we need: read the whole drive again."""


def unpack_journal(raw):
    jid, first, nxt, lowest = struct.unpack_from("<Qqqq", raw, 0)
    return Journal(jid, first, nxt, lowest)


def plan_scan(journal, since):
    """'catch_up' when the saved place (journal id, usn) is still in this journal, else 'full'."""
    if not since or journal is None or since.get("journal") != journal.journal_id:
        return "full"
    usn = since.get("usn", -1)
    if usn < max(journal.first_usn, journal.lowest_valid) or usn > journal.next_usn:
        return "full"
    return "catch_up"


# ---------- messages ----------
def encode(obj):
    return (json.dumps(obj, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _no_constants(word):
    raise ValueError(f"{word} is not JSON")


class Lines:
    """Bytes in, JSON objects out, one per line; a line over max_line or anything but an object raises."""

    def __init__(self, max_line=MAX_LINE):
        self.max_line, self._buf = max_line, b""

    def feed(self, data):
        self._buf += data
        out = []
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                if len(self._buf) > self.max_line:
                    raise ValueError("line too long")
                return out
            line, self._buf = self._buf[:i], self._buf[i + 1:]
            if len(line) > self.max_line:
                raise ValueError("line too long")
            if not line.strip():
                continue
            obj = json.loads(line, parse_constant=_no_constants)
            if not isinstance(obj, dict):
                raise ValueError("not an object")
            out.append(obj)


def _paths(v, what):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 200:
        raise ValueError(f"{what}: a list of at most 200 folders")
    out = []
    for p in v:
        if not (isinstance(p, str) and 3 <= len(p) < 1024 and "\x00" not in p and re.match(r"^[A-Za-z]:\\", p)):
            raise ValueError(f"{what}: a folder on a drive letter")
        out.append(os.path.normpath(p))
    return out


def parse_config(msg):
    """The engine's scope for the helper (it can only narrow what's sent; the hard drops don't depend on it)."""
    out = {"roots": _paths(msg.get("roots"), "roots"), "exclude": _paths(msg.get("exclude"), "exclude")}
    for k, d in (("include_system", True), ("include_caches", True), ("include_secrets", False)):
        v = msg.get(k, d)
        if not isinstance(v, bool):
            raise ValueError(f"{k}: true or false")
        out[k] = v
    return out


def parse_drive(msg):
    d = msg.get("drive")
    if not isinstance(d, str) or not DRIVE_RE.match(d):
        raise ValueError("drive: like C:\\")
    return d.upper()


def parse_since(msg):
    s = msg.get("since")
    if s is None:
        return None
    if not isinstance(s, dict):
        raise ValueError("since: {journal, usn}")
    j, u = s.get("journal"), s.get("usn")
    for v in (j, u):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v >= 1 << 64:
            raise ValueError("since: whole numbers")
    return {"journal": j, "usn": u}


# ---------- Windows: the volume (elevated only) ----------
FSCTL_ENUM_USN_DATA = 0x000900B3
FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_USN_JOURNAL = 0x000900BB
FSCTL_GET_NTFS_FILE_RECORD = 0x00090068
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064
ERROR_HANDLE_EOF, ERROR_MORE_DATA = 38, 234
ERROR_JOURNAL_DELETE_IN_PROGRESS, ERROR_JOURNAL_NOT_ACTIVE, ERROR_JOURNAL_ENTRY_DELETED = 1178, 1179, 1181
GENERIC_READ = 0x80000000
FILE_SHARE_ALL = 0x7
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE = ctypes.c_void_p(-1).value
ENUM_BUF = 1 << 20

_dll = {}


def _k32():
    if "k" not in _dll:
        w = wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B, P = w.HANDLE, w.DWORD, w.BOOL, ctypes.c_void_p
        for name, res, args in (
                ("CreateFileW", H, [w.LPCWSTR, D, D, P, D, D, H]),
                ("DeviceIoControl", B, [H, D, P, D, P, D, ctypes.POINTER(D), P]),
                ("CloseHandle", B, [H]),
                ("OpenFileById", H, [H, P, D, D, P, D]),
                ("GetFileInformationByHandleEx", B, [H, ctypes.c_int, P, D]),
                ("GetVolumeInformationW", B, [w.LPCWSTR, w.LPWSTR, D, P, P, P, w.LPWSTR, D]),
                ("GetDriveTypeW", ctypes.c_uint, [w.LPCWSTR]),
                ("GetCurrentProcessId", D, []),
                ("GetCurrentProcess", H, []),
                ("OpenProcess", H, [D, B, D]),
                ("ProcessIdToSessionId", B, [D, ctypes.POINTER(D)]),
                ("QueryFullProcessImageNameW", B, [H, D, w.LPWSTR, ctypes.POINTER(D)]),
                ("CreateToolhelp32Snapshot", H, [D, D]),
                ("Process32FirstW", B, [H, P]),
                ("Process32NextW", B, [H, P]),
                ("WaitForSingleObject", D, [H, D]),
                ("ReadFile", B, [H, P, D, ctypes.POINTER(D), P]),
                ("WriteFile", B, [H, P, D, ctypes.POINTER(D), P]),
                ("GetNamedPipeServerProcessId", B, [H, ctypes.POINTER(D)]),
                ("GetNamedPipeServerSessionId", B, [H, ctypes.POINTER(D)]),
                ("LocalFree", P, [P])):
            f = getattr(k, name)
            f.restype, f.argtypes = res, args
        _dll["k"] = k
    return _dll["k"]


def is_ntfs_fixed(drive):
    if not winapi.WIN:
        return False
    k = _k32()
    if k.GetDriveTypeW(drive) != 3:                     # DRIVE_FIXED
        return False
    fs = ctypes.create_unicode_buffer(64)
    return bool(k.GetVolumeInformationW(drive, None, 0, None, None, None, fs, 64)) and fs.value == "NTFS"


class Volume:
    """One NTFS volume, opened read-only (GENERIC_READ). Needs administrator rights."""

    def __init__(self, drive):
        self.drive = drive
        k = _k32()
        h = k.CreateFileW("\\\\.\\" + drive[:2], GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE:
            raise OSError(ctypes.get_last_error(), f"can't open {drive[:2]}")
        self.h = h
        self._rec_out = ctypes.create_string_buffer(64 * 1024 + 12)

    def close(self):
        if self.h:
            _k32().CloseHandle(self.h)
            self.h = None

    def _ioctl(self, code, inb, out):
        n = wintypes.DWORD()
        ib = ctypes.create_string_buffer(inb, len(inb)) if inb else None
        ok = _k32().DeviceIoControl(self.h, code, ib, len(inb) if inb else 0, out, len(out), ctypes.byref(n), None)
        return ok, ctypes.get_last_error(), n.value

    def journal(self):
        out = ctypes.create_string_buffer(80)
        ok, err, n = self._ioctl(FSCTL_QUERY_USN_JOURNAL, None, out)
        if not ok:
            if err in (ERROR_JOURNAL_NOT_ACTIVE, ERROR_JOURNAL_DELETE_IN_PROGRESS):
                return None
            raise OSError(err, "change journal")
        return unpack_journal(out.raw)

    def enum(self, high_usn):
        """Every MFT entry in use, as batches of UsnRecord (V2 records: 64-bit file reference numbers)."""
        out = ctypes.create_string_buffer(ENUM_BUF)
        start = 0
        v1 = True
        while True:
            inb = struct.pack("<QqqHH", start, 0, high_usn, 2, 2) if v1 else struct.pack("<Qqq", start, 0, high_usn)
            ok, err, n = self._ioctl(FSCTL_ENUM_USN_DATA, inb, out)
            if not ok:
                if err == ERROR_HANDLE_EOF:
                    return
                if v1 and err == 87:                      # ERROR_INVALID_PARAMETER: an older Windows, V0 input
                    v1 = False
                    continue
                raise OSError(err, "MFT enumeration")
            nxt, recs = parse_usn_buffer(out.raw, n)
            if recs:
                yield recs
            if nxt == start or n <= 8:
                return
            start = nxt

    def read_journal(self, journal_id, start_usn):
        """(next usn, [UsnRecord]) since start_usn; raises JournalLost when that place is gone."""
        out = ctypes.create_string_buffer(ENUM_BUF)
        inb = struct.pack("<qIIQQQ", start_usn, 0xFFFFFFFF, 0, 0, 0, journal_id)
        ok, err, n = self._ioctl(FSCTL_READ_USN_JOURNAL, inb, out)
        if not ok:
            if err in (ERROR_JOURNAL_ENTRY_DELETED, ERROR_JOURNAL_NOT_ACTIVE, ERROR_JOURNAL_DELETE_IN_PROGRESS):
                raise JournalLost(err)
            raise OSError(err, "change journal")
        return parse_usn_buffer(out.raw, n)

    def record(self, ref):
        """FileRecord for this file reference number, or None (gone, reused or unreadable)."""
        ok, _err, n = self._ioctl(FSCTL_GET_NTFS_FILE_RECORD, struct.pack("<q", ref & 0xFFFFFFFFFFFF), self._rec_out)
        if not ok:
            return None
        got, body = unpack_record_output(self._rec_out.raw, n)
        if got is None or (got & 0xFFFFFFFFFFFF) != (ref & 0xFFFFFFFFFFFF):
            return None
        if len(body) >= 18 and struct.unpack_from("<H", body, 16)[0] != (ref >> 48):
            return None                                  # the record was reused for another file
        rec = parse_file_record(body)
        return rec if rec is not None and rec.in_use else None

    def stat_by_id(self, ref):
        """(size, mtime, ctime) from Windows for one file by its id (metadata only), or None."""
        k = _k32()
        desc = struct.pack("<IIq8x", 24, 0, ref)          # FILE_ID_DESCRIPTOR: size, FileIdType, the id
        db = ctypes.create_string_buffer(desc, len(desc))
        h = k.OpenFileById(self.h, db, 0x80, FILE_SHARE_ALL, None, FILE_FLAG_BACKUP_SEMANTICS)   # read attributes
        if not h or h == INVALID_HANDLE:
            return None
        try:
            basic = ctypes.create_string_buffer(40)
            std = ctypes.create_string_buffer(24)
            if not (k.GetFileInformationByHandleEx(h, 0, basic, 40) and k.GetFileInformationByHandleEx(h, 1, std, 24)):
                return None
            c, _a, m = struct.unpack_from("<qqq", basic.raw, 0)
            return struct.unpack_from("<q", std.raw, 8)[0], filetime(m), filetime(c)
        finally:
            k.CloseHandle(h)


# ---------- who's who (helper side) ----------
class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def parent_pid(pid=None):
    k = _k32()
    pid = pid or k.GetCurrentProcessId()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)              # TH32CS_SNAPPROCESS
    if not snap or snap == INVALID_HANDLE:
        return 0
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(_PE32)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.th32ProcessID == pid:
                return e.th32ParentProcessID
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return 0


def image_of(h):
    buf = ctypes.create_unicode_buffer(32768)
    n = wintypes.DWORD(32768)
    return buf.value if _k32().QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""


def session_of(pid):
    s = wintypes.DWORD()
    return s.value if _k32().ProcessIdToSessionId(pid, ctypes.byref(s)) else None


def _advapi():
    if "a" not in _dll:
        w = wintypes
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        H, D, B, P = w.HANDLE, w.DWORD, w.BOOL, ctypes.c_void_p
        for name, res, args in (
                ("OpenProcessToken", B, [H, D, ctypes.POINTER(H)]),
                ("GetTokenInformation", B, [H, ctypes.c_int, P, D, ctypes.POINTER(D)]),
                ("ConvertSidToStringSidW", B, [P, ctypes.POINTER(w.LPWSTR)]),
                ("DuplicateTokenEx", B, [H, D, P, ctypes.c_int, ctypes.c_int, ctypes.POINTER(H)]),
                ("GetFileSecurityW", B, [w.LPCWSTR, D, P, D, ctypes.POINTER(D)]),
                ("AccessCheck", B, [P, H, D, P, P, ctypes.POINTER(D), ctypes.POINTER(D), ctypes.POINTER(B)])):
            f = getattr(a, name)
            f.restype, f.argtypes = res, args
        _dll["a"] = a
    return _dll["a"]


def token_sid(token):
    a, k = _advapi(), _k32()
    need = wintypes.DWORD()
    a.GetTokenInformation(token, 1, None, 0, ctypes.byref(need))            # TokenUser
    buf = ctypes.create_string_buffer(max(need.value, 64))
    if not a.GetTokenInformation(token, 1, buf, need, ctypes.byref(need)):
        return ""
    sid = ctypes.c_void_p.from_buffer(buf).value
    s = wintypes.LPWSTR()
    if not a.ConvertSidToStringSidW(sid, ctypes.byref(s)):
        return ""
    try:
        return s.value
    finally:
        k.LocalFree(s)


def profile_of(sid):
    """The profile folder Windows has for this SID (HKLM ProfileList: only administrators can change it)."""
    if not SID_RE.match(sid or ""):
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\" + sid) as k:
            return os.path.normpath(os.path.expandvars(winreg.QueryValueEx(k, "ProfileImagePath")[0]))
    except OSError:
        return ""


class Lister:
    """can_list(path): could the engine's user list this folder (FILE_LIST_DIRECTORY), by AccessCheck against a
    copy of that user's own token. Cached per security descriptor (most folders share a few)."""

    _MAPPING = struct.pack("<IIII", 0x120089, 0x120116, 0x1200A0, 0x1F01FF)  # FILE_GENERIC_READ/WRITE/EXECUTE/ALL

    def __init__(self, token):
        self.token = token                               # an impersonation token (SecurityIdentification)
        self._cache = {}

    def __call__(self, path):
        a = _advapi()
        need = wintypes.DWORD()
        info = 0x1 | 0x2 | 0x4                            # owner, group, DACL
        a.GetFileSecurityW(path, info, None, 0, ctypes.byref(need))
        if not need.value or need.value > 1 << 20:
            return False
        sd = ctypes.create_string_buffer(need.value)
        if not a.GetFileSecurityW(path, info, sd, need, ctypes.byref(need)):
            return False
        key = sd.raw
        if key in self._cache:
            return self._cache[key]
        mapping = ctypes.create_string_buffer(self._MAPPING, 16)
        priv = ctypes.create_string_buffer(256)
        plen = wintypes.DWORD(256)
        granted, status = wintypes.DWORD(), wintypes.BOOL()
        ok = a.AccessCheck(sd, self.token, 0x1, mapping, priv, ctypes.byref(plen), ctypes.byref(granted),
                           ctypes.byref(status))
        result = bool(ok and status.value and granted.value & 0x1)
        self._cache[key] = result
        return result


# ---------- the helper ----------
def pipe_name(sid, pid):
    return f"\\\\.\\pipe\\NOBADFind-turbo-{sid}-{int(pid)}"


class _Pipe:
    """The helper's end of the engine's pipe (blocking I/O; one reader, writes under a lock)."""

    def __init__(self, h):
        self.h = h
        self._lock = threading.Lock()

    def send(self, obj):
        data = encode(obj)
        n = wintypes.DWORD()
        with self._lock:
            off = 0
            while off < len(data):
                chunk = data[off:off + (1 << 20)]
                buf = ctypes.create_string_buffer(chunk, len(chunk))
                if not _k32().WriteFile(self.h, buf, len(chunk), ctypes.byref(n), None) or not n.value:
                    raise OSError(ctypes.get_last_error(), "pipe write")
                off += n.value

    def read(self):
        buf = ctypes.create_string_buffer(65536)
        n = wintypes.DWORD()
        if not _k32().ReadFile(self.h, buf, 65536, ctypes.byref(n), None) or not n.value:
            return b""
        return buf.raw[:n.value]


def _connect_to_parent():
    """Open the engine's pipe, after checking the engine is who the pipe name and Windows say it is.
    Returns (_Pipe, parent process handle, the user's SID, the user's token for AccessCheck)."""
    k, a = _k32(), _advapi()
    me = k.GetCurrentProcessId()
    ppid = parent_pid(me)
    if not ppid:
        raise PermissionError("no parent process")
    hp = k.OpenProcess(0x1000 | 0x100000 | 0x0400 | 0x0040, False, ppid)  # query limited, synchronize, query, dup
    if not hp:
        raise PermissionError("parent process can't be opened")
    if os.path.normcase(image_of(hp)) != os.path.normcase(image_of(k.GetCurrentProcess())):
        raise PermissionError("the parent isn't NOBAD Find")
    if session_of(ppid) != session_of(me):
        raise PermissionError("the parent is in another session")
    tok = wintypes.HANDLE()
    if not a.OpenProcessToken(hp, 0x8 | 0x2, ctypes.byref(tok)):         # TOKEN_QUERY | TOKEN_DUPLICATE
        raise PermissionError("the parent's token can't be read")
    sid = token_sid(tok)
    if not SID_RE.match(sid):
        raise PermissionError("the parent isn't a user account")
    imp = wintypes.HANDLE()
    if not a.DuplicateTokenEx(tok, 0x8 | 0x4, None, 1, 2, ctypes.byref(imp)):   # SecurityIdentification, impersonation
        raise PermissionError("no token for access checks")
    k.CloseHandle(tok)
    name = pipe_name(sid, ppid)
    h = k.CreateFileW(name, GENERIC_READ | 0x40000000, 0, None, OPEN_EXISTING,
                      0x00100000 | 0x00010000, None)          # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION
    if not h or h == INVALID_HANDLE:
        raise PermissionError(f"pipe not there ({ctypes.get_last_error()})")
    spid, ssess = wintypes.DWORD(), wintypes.DWORD()
    if not (k.GetNamedPipeServerProcessId(h, ctypes.byref(spid)) and spid.value == ppid):
        k.CloseHandle(h)
        raise PermissionError("the pipe isn't served by the parent")
    if not (k.GetNamedPipeServerSessionId(h, ctypes.byref(ssess)) and ssess.value == session_of(me)):
        k.CloseHandle(h)
        raise PermissionError("the pipe is served from another session")
    return _Pipe(h), hp, sid, imp


def _rules_for(sid, cfg, profile=None):
    prof = profile or profile_of(sid)
    if not prof:
        raise PermissionError("no profile for this account")
    others = [p for p in scope._profile_list() if p and _norm(p) != _norm(prof)]
    return scope.Rules(system=cfg["include_system"], caches=cfg["include_caches"], secrets=cfg["include_secrets"],
                       profile=prof, others=others)


class Scanner:
    """Reads one drive (full or catch-up) and follows its journal; sends through `send`. Used by serve and
    selftest. stats: timings and counts (never names)."""

    def __init__(self, drive, flt, send, volume=None):
        self.drive, self.flt, self.send = drive, flt, send
        self.vol = volume or Volume(drive)
        self.tree = Tree(drive)
        self.journal = None
        self.usn = 0
        self.stats = {"drive": drive, "entries": 0, "dirs": 0, "sent": 0, "dropped": 0, "by_id": 0}

    def _folders(self, high):
        t0 = time.perf_counter()
        n = 0
        for recs in self.vol.enum(high):
            for r in recs:
                n += 1
                if r.is_dir:
                    self.tree.add_dir(r.frn, r.parent, r.name)
        self.stats.update(entries=n, dirs=len(self.tree.dirs), enum_s=round(time.perf_counter() - t0, 2))

    def _meta(self, ref, is_dir):
        rec = self.vol.record(ref)
        if rec is not None and rec.size is not None:
            return rec.size, rec.mtime, rec.ctime
        got = self.vol.stat_by_id(ref)
        self.stats["by_id"] += 1
        if got is None:
            return (0 if is_dir else None), (rec.mtime if rec else None), (rec.ctime if rec else None)
        return got

    def scan(self, since=None):
        self.journal = self.vol.journal()
        high = self.journal.next_usn if self.journal else 1 << 62
        plan = plan_scan(self.journal, since)
        self._folders(high)
        self.usn = self.journal.next_usn if self.journal else 0
        if plan == "catch_up":
            self.usn = since["usn"]
            self.follow_once()
            return {"full": False}
        t0 = time.perf_counter()
        rows = []
        for recs in self.vol.enum(high):
            for r in recs:
                p = self.flt.keep_dir(self.tree, r.frn) if r.is_dir else self.flt.keep_file(self.tree, r.parent,
                                                                                           r.name)
                if p is None:
                    self.stats["dropped"] += 1
                    continue
                if r.attrs & REPARSE:
                    continue                             # links and junctions: like the walk, not followed
                size, mtime, ctime = self._meta(r.frn, r.is_dir)
                rows.append([p, 1 if r.is_dir else 0, size, mtime, ctime])
                if len(rows) >= ROWS_PER_MESSAGE:
                    self.send({"t": "rows", "drive": self.drive, "rows": rows})
                    self.stats["sent"] += len(rows)
                    rows = []
        if rows:
            self.send({"t": "rows", "drive": self.drive, "rows": rows})
            self.stats["sent"] += len(rows)
        self.stats["rows_s"] = round(time.perf_counter() - t0, 2)
        return {"full": True}

    def follow_once(self):
        """Read the journal from self.usn; send the changed paths. Raises JournalLost."""
        if self.journal is None:
            raise JournalLost("no journal")
        while True:
            nxt, recs = self.vol.read_journal(self.journal.journal_id, self.usn)
            if not recs or nxt <= self.usn:
                self.usn = max(self.usn, nxt)
                return
            self.usn = nxt
            paths = apply_changes(self.tree, self.flt, recs)
            if paths:
                self.send({"t": "changes", "drive": self.drive, "paths": paths})


def _serve():
    pipe, parent, sid, token = _connect_to_parent()
    k = _k32()

    def watch_parent():
        k.WaitForSingleObject(parent, 0xFFFFFFFF)
        os._exit(0)                                       # the engine is gone: so is the helper
    threading.Thread(target=watch_parent, daemon=True, name="parent").start()
    try:
        winapi.worker_priority(True)                      # idle CPU, low memory and I/O priority
    except Exception:
        pass
    drives = [f"{chr(65 + i)}:\\" for i in range(26) if is_ntfs_fixed(f"{chr(65 + i)}:\\")]
    pipe.send({"t": "hello", "protocol": PROTOCOL, "pid": k.GetCurrentProcessId(),
               "volumes": [{"drive": d, "ntfs": True} for d in drives]})
    lister = Lister(token)
    state = {"flt": None, "followers": {}}
    lock = threading.Lock()
    work = []
    wake = threading.Event()

    def follower():
        while True:
            time.sleep(FOLLOW_EVERY)
            with lock:
                items = list(state["followers"].items())
            for drive, sc in items:
                try:
                    sc.follow_once()
                    pipe.send({"t": "usn", "drive": drive, "journal": sc.journal.journal_id, "usn": sc.usn})
                except JournalLost:
                    with lock:
                        state["followers"].pop(drive, None)
                    pipe.send({"t": "journal", "drive": drive, "usn_ok": False,
                               "error": "The change journal was reset; reading the drive again."})
                except OSError as e:
                    with lock:
                        state["followers"].pop(drive, None)
                    pipe.send({"t": "journal", "drive": drive, "usn_ok": False, "error": f"error {e.errno}"})

    def worker():
        while True:
            wake.wait()
            wake.clear()
            while work:
                drive, since = work.pop(0)
                with lock:
                    state["followers"].pop(drive, None)
                    flt = state["flt"]
                try:
                    if drive not in drives:
                        raise OSError(0, "not an NTFS fixed drive")
                    sc = Scanner(drive, flt, pipe.send)
                    r = sc.scan(since)
                    j = sc.journal
                    pipe.send({"t": "scanned", "drive": drive, "full": r["full"], "files": sc.stats["sent"],
                               "journal": j.journal_id if j else 0, "usn": sc.usn, "usn_ok": j is not None})
                    if j is not None:
                        with lock:
                            state["followers"][drive] = sc
                except Exception as e:
                    pipe.send({"t": "failed", "drive": drive, "error": f"{type(e).__name__} {getattr(e, 'errno', '')}"})
    threading.Thread(target=worker, daemon=True, name="scan").start()
    threading.Thread(target=follower, daemon=True, name="follow").start()

    lines = Lines()
    while True:
        data = pipe.read()
        if not data:
            return 0                                      # the engine closed the pipe
        for msg in lines.feed(data):                      # a bad line raises: the helper ends
            t = msg.get("t")
            if t == "config":
                cfg = parse_config(msg)
                flt = Filter(_rules_for(sid, cfg), cfg["roots"], cfg["exclude"], can_list=lister)
                with lock:
                    state["flt"] = flt
                    for sc in state["followers"].values():
                        sc.flt = flt
            elif t == "scan":
                if state["flt"] is None:
                    raise ValueError("scan before config")
                work.append((parse_drive(msg), parse_since(msg)))
                wake.set()
            elif t == "stop":
                return 0


def _selftest(out=print):
    """Already elevated: read the system drive with the default scope, as the user running it, and print timings
    and counts (never a name). Measures both ways of getting size and times, and the change latency."""
    import tempfile
    from .const import DEFAULTS
    k, a = _k32(), _advapi()
    tok = wintypes.HANDLE()
    a.OpenProcessToken(k.GetCurrentProcess(), 0x8 | 0x2, ctypes.byref(tok))
    imp = wintypes.HANDLE()
    a.DuplicateTokenEx(tok, 0x8 | 0x4, None, 1, 2, ctypes.byref(imp))
    sid = token_sid(tok)
    drive = scope.system_drive()
    cfg = parse_config({"roots": scope.roots_for(DEFAULTS, [{"root": drive, "type": "fixed", "label": ""}],
                                                 known=lambda n: None)})
    flt = Filter(_rules_for(sid, cfg, profile=scope.profile_dir()), cfg["roots"], cfg["exclude"], can_list=Lister(imp))
    sent = [0]
    t0 = time.perf_counter()
    sc = Scanner(drive, flt, lambda m: sent.__setitem__(0, sent[0] + len(m.get("rows") or m.get("paths") or [])))
    sc.scan(None)
    total = time.perf_counter() - t0
    pmc = (ctypes.c_size_t * 10)()
    ctypes.WinDLL("psapi").GetProcessMemoryInfo(k.GetCurrentProcess(), pmc, ctypes.sizeof(pmc))
    # option B for size/times: one GetFileInformationByHandleEx per file, on a sample
    sample = [r.frn for recs in sc.vol.enum(sc.journal.next_usn if sc.journal else 1 << 62)
              for r in recs if not r.is_dir][:5000]
    t1 = time.perf_counter()
    for ref in sample:
        sc.vol.record(ref)
    rec_us = (time.perf_counter() - t1) / max(1, len(sample)) * 1e6
    t1 = time.perf_counter()
    for ref in sample:
        sc.vol.stat_by_id(ref)
    byid_us = (time.perf_counter() - t1) / max(1, len(sample)) * 1e6
    # change latency: a file appears in the user's temp folder, how long until the journal shows it
    latency = None
    if sc.journal is not None:
        fd, path = tempfile.mkstemp(prefix="nobadfind-turbo-")
        os.close(fd)
        t2 = time.perf_counter()
        seen = False
        while time.perf_counter() - t2 < 10 and not seen:
            nxt, recs = sc.vol.read_journal(sc.journal.journal_id, sc.usn)
            seen = any(r.name == os.path.basename(path) for r in recs)
            sc.usn = max(sc.usn, nxt)
            if not seen:
                time.sleep(0.01)
        latency = round((time.perf_counter() - t2) * 1000, 1) if seen else None
        os.remove(path)
    st = dict(sc.stats, total_s=round(total, 2), rows=sent[0], peak_private_mb=round(pmc[8] / 1048576),
              peak_ws_mb=round(pmc[2] / 1048576), record_us_per_file=round(rec_us, 1),
              by_handle_us_per_file=round(byid_us, 1), journal_latency_ms=latency, usn_ok=sc.journal is not None)
    out(json.dumps(st))
    return 0


def helper_main(word):
    """`--turbo <word>`. Only the words in WORDS; only elevated (the helper is pointless and refused otherwise)."""
    if word not in WORDS:
        return 2
    if not winapi.is_admin():
        return 3
    try:
        return _serve() if word == "serve" else _selftest()
    except PermissionError as e:
        print(f"turbo helper refused: {e}", file=sys.stderr)
        return 4
    except (OSError, ValueError) as e:
        print(f"turbo helper ended: {type(e).__name__}", file=sys.stderr)
        return 5
