"""The turbo index's pure parts (nobadfind/ntfs.py), on synthetic buffers: USN_RECORD_V2/V3 parsing, MFT file
records (fixups, $STANDARD_INFORMATION, $DATA), path resolution from file reference numbers, the privacy filter,
journal bookkeeping and the helper's message checks. Nothing here opens a volume or needs administrator rights."""
import json
import struct

import pytest

from nobadfind import ntfs, scope

EPOCH = 116444736000000000             # FILETIME of 1970-01-01
ROOT_FRN = ntfs.ROOT_FRN


def ft(unix):
    return int(unix * 10_000_000) + EPOCH


def frn(index, seq=1):
    return (seq << 48) | index


def usn_v2(ref, parent, name, attrs=0, usn=0, reason=0, ts=0):
    raw = name.encode("utf-16-le")
    size = (60 + len(raw) + 7) & ~7
    head = struct.pack("<IHHQQqqIIIIHH", size, 2, 0, ref, parent, usn, ts, reason, 0, 0, attrs, len(raw), 60)
    return (head + raw).ljust(size, b"\0")


def usn_v3(ref, parent, name, attrs=0, usn=0, reason=0):
    raw = name.encode("utf-16-le")
    size = (76 + len(raw) + 7) & ~7
    head = struct.pack("<IHH", size, 3, 0) + ref.to_bytes(16, "little") + parent.to_bytes(16, "little")
    head += struct.pack("<qqIIIIHH", usn, 0, reason, 0, 0, attrs, len(raw), 76)
    return (head + raw).ljust(size, b"\0")


# ---------- USN records ----------
def test_parse_v2_records_after_the_8_byte_header():
    buf = struct.pack("<Q", 99) + usn_v2(frn(40), ROOT_FRN, "Users", ntfs.DIR) + usn_v2(frn(41), frn(40), "a.txt")
    nxt, recs = ntfs.parse_usn_buffer(buf, len(buf))
    assert nxt == 99
    assert [(r.frn, r.parent, r.name, r.is_dir) for r in recs] == [
        (frn(40), ROOT_FRN, "Users", True), (frn(41), frn(40), "a.txt", False)]


def test_parse_v3_records_and_names_with_any_characters():
    name = "résumé ✓ 日本.pdf"
    buf = struct.pack("<Q", 7) + usn_v3(frn(5000), frn(40), name, usn=123, reason=ntfs.R_CREATE)
    _n, recs = ntfs.parse_usn_buffer(buf, len(buf))
    assert recs[0].name == name and recs[0].usn == 123 and recs[0].reason == ntfs.R_CREATE
    assert recs[0].frn == frn(5000) and recs[0].parent == frn(40)


@pytest.mark.parametrize("bad", [
    b"\x05\0\0\0" + b"\0" * 60,                                   # record shorter than its header
    struct.pack("<IHH", 0, 2, 0) + b"\0" * 56,                      # length 0: would loop forever
    struct.pack("<IHH", 4096, 2, 0) + b"\0" * 56,                   # longer than the buffer
    struct.pack("<IHH", 64, 9, 0) + b"\0" * 56,                     # unknown major version
])
def test_broken_records_stop_the_parse_instead_of_crashing(bad):
    good = usn_v2(frn(41), frn(40), "a.txt")
    buf = struct.pack("<Q", 1) + good + bad
    _n, recs = ntfs.parse_usn_buffer(buf, len(buf))
    assert [r.name for r in recs] == ["a.txt"]


def test_name_outside_the_record_is_refused():
    raw = "x".encode("utf-16-le")
    rec = struct.pack("<IHHQQqqIIIIHH", 64, 2, 0, frn(1), ROOT_FRN, 0, 0, 0, 0, 0, 0, 200, 60) + raw
    buf = struct.pack("<Q", 1) + rec.ljust(64, b"\0")
    assert ntfs.parse_usn_buffer(buf, len(buf))[1] == []


# ---------- MFT file records ----------
def attr_resident(kind, value, name=""):
    nraw = name.encode("utf-16-le")
    head_len = 24
    voff = (head_len + len(nraw) + 7) & ~7
    length = (voff + len(value) + 7) & ~7
    head = struct.pack("<IIBBHHH", kind, length, 0, len(name), head_len, 0, 0)
    head += struct.pack("<IHBB", len(value), voff, 0, 0)
    return (head + nraw).ljust(voff, b"\0") + value.ljust(length - voff, b"\0")


def attr_nonresident(kind, data_size, start_vcn=0, name=""):
    nraw = name.encode("utf-16-le")
    head_len = 64
    length = (head_len + len(nraw) + 8 + 7) & ~7
    head = struct.pack("<IIBBHHH", kind, length, 1, len(name), head_len, 0, 0)
    head += struct.pack("<qqHHI", start_vcn, 10, head_len + len(nraw), 0, 0)
    head += struct.pack("<qqq", (data_size + 4095) & ~4095, data_size, data_size)
    return (head + nraw).ljust(length, b"\0")


def std_info(created, modified):
    return struct.pack("<qqqqI", ft(created), ft(modified), ft(modified), ft(modified), 0x20) + b"\0" * 12


def file_record(attrs, flags=1, size=1024, fixup=True):
    """A FILE record with an update sequence array: the last two bytes of each 512-byte sector hold the USN,
    and the real bytes are in the array (what NTFS writes to disk and FSCTL_GET_NTFS_FILE_RECORD returns)."""
    usa_off, usa_count = 48, size // 512 + 1
    first = (usa_off + 2 * usa_count + 7) & ~7
    body = bytearray(size)
    struct.pack_into("<4sHHqHHHHII", body, 0, b"FILE", usa_off, usa_count, 0, 1, 1, first, flags, 0, size)
    off = first
    for a in attrs:
        body[off:off + len(a)] = a
        off += len(a)
    struct.pack_into("<I", body, off, 0xFFFFFFFF)
    struct.pack_into("<I", body, 24, off + 8)
    if fixup:
        usn = 0x0A0B
        struct.pack_into("<H", body, usa_off, usn)
        for i in range(1, usa_count):
            end = i * 512 - 2
            body[usa_off + 2 * i: usa_off + 2 * i + 2] = body[end:end + 2]
            struct.pack_into("<H", body, end, usn)
    return bytes(body)


def test_file_record_size_and_times_resident_data():
    rec = file_record([attr_resident(0x10, std_info(1_600_000_000, 1_700_000_000.5)),
                       attr_resident(0x80, b"hello world")])
    got = ntfs.parse_file_record(rec)
    assert got.size == 11 and got.in_use and not got.is_dir
    assert got.mtime == pytest.approx(1_700_000_000.5) and got.ctime == pytest.approx(1_600_000_000)


def test_file_record_nonresident_data_and_named_streams_ignored():
    rec = file_record([attr_resident(0x10, std_info(1, 2)), attr_nonresident(0x80, 999, name="Zone.Identifier"),
                       attr_nonresident(0x80, 5_000_000_000)])
    assert ntfs.parse_file_record(rec).size == 5_000_000_000


def test_file_record_fixups_are_applied():
    """A value that crosses a sector end: without the fixup its last two bytes would read as the USN."""
    data = bytes(range(256)) * 3
    rec = file_record([attr_resident(0x10, std_info(1, 2)), attr_resident(0x80, data)])
    assert rec[510:512] == b"\x0b\x0a"                 # the USN sits there on disk
    assert ntfs.parse_file_record(rec).size == len(data)


def test_torn_record_is_refused():
    rec = bytearray(file_record([attr_resident(0x10, std_info(1, 2))]))
    rec[1022:1024] = b"\x99\x99"                        # a sector that doesn't end in the USN: a torn write
    assert ntfs.parse_file_record(bytes(rec)) is None


def test_directory_and_missing_data():
    rec = file_record([attr_resident(0x10, std_info(1, 2))], flags=3)
    got = ntfs.parse_file_record(rec)
    assert got.is_dir and got.size == 0


def test_size_from_an_attribute_list_record_is_unknown():
    rec = file_record([attr_resident(0x10, std_info(1, 2)), attr_resident(0x20, b"\0" * 32)])
    assert ntfs.parse_file_record(rec).size is None     # $DATA is elsewhere: the caller asks Windows instead


@pytest.mark.parametrize("bad", [b"", b"BAAD" + b"\0" * 1020, b"FILE" + b"\xff" * 1020])
def test_garbage_records(bad):
    assert ntfs.parse_file_record(bad) is None


def test_file_record_output_buffer_header():
    rec = file_record([attr_resident(0x10, std_info(1, 2))])
    out = struct.pack("<qI", frn(77), len(rec)) + rec
    ref, body = ntfs.unpack_record_output(out, len(out))
    assert ref == frn(77) and body == rec


# ---------- tree and paths ----------
def tree():
    t = ntfs.Tree("C:\\")
    for ref, parent, name in ((frn(40), ROOT_FRN, "Users"), (frn(41), frn(40), "me"), (frn(42), frn(41), "Documents"),
                              (frn(43), frn(40), "Bob"), (frn(44), ROOT_FRN, "Windows")):
        t.add_dir(ref, parent, name)
    return t


def test_paths_from_reference_numbers():
    t = tree()
    assert t.path(frn(42)) == "C:\\Users\\me\\Documents"
    assert t.path(ROOT_FRN) == "C:\\"
    assert t.child(frn(42), "a.txt") == "C:\\Users\\me\\Documents\\a.txt"


def test_orphans_and_loops_have_no_path():
    t = tree()
    t.add_dir(frn(50), frn(999), "lost")
    t.add_dir(frn(60), frn(61), "a")
    t.add_dir(frn(61), frn(60), "b")
    assert t.path(frn(50)) is None and t.path(frn(60)) is None and t.child(frn(61), "x") is None


def test_rename_and_delete_update_the_tree():
    t = tree()
    t.path(frn(42))                                     # cached
    t.add_dir(frn(41), frn(40), "me2")                  # renamed: the cache below it is dropped
    assert t.path(frn(42)) == "C:\\Users\\me2\\Documents"
    t.remove(frn(42))
    assert t.path(frn(42)) is None


# ---------- the privacy filter ----------
def flt(**kw):
    rules = scope.Rules(profile="C:\\Users\\me", others=["C:\\Users\\Bob", "D:\\Profiles\\Eve"],
                        system=kw.pop("system", True), caches=kw.pop("caches", True), secrets=kw.pop("secrets", False))
    return ntfs.Filter(rules, roots=kw.pop("roots", ["C:\\Users\\me", "C:\\"]), exclude=kw.pop("exclude", []))


def test_filter_drops_other_profiles_always():
    f = flt(secrets=True)
    t = tree()
    assert f.dir_state(t, frn(43)) == ntfs.OUT                     # C:\Users\Bob
    assert f.keep_file(t, frn(43), "b.txt") is None
    assert f.keep_file(t, frn(42), "a.txt") == "C:\\Users\\me\\Documents\\a.txt"


def test_filter_drops_system_volume_information_and_recycle_bins():
    f = flt(system=True, caches=True, secrets=True)
    t = ntfs.Tree("C:\\")
    t.add_dir(frn(70), ROOT_FRN, "System Volume Information")
    t.add_dir(frn(71), ROOT_FRN, "$Recycle.Bin")
    t.add_dir(frn(72), frn(71), "S-1-5-21-1-2-3-1001")
    assert f.dir_state(t, frn(70)) == ntfs.OUT and f.dir_state(t, frn(72)) == ntfs.OUT
    assert f.keep_file(t, frn(72), "$R1.docx") is None


def test_filter_drops_ntfs_metafiles():
    f = flt()
    assert f.keep_file(ntfs.Tree("C:\\"), ROOT_FRN, "$MFT") is None
    assert f.keep_file(ntfs.Tree("C:\\"), ROOT_FRN, "pagefile.sys") == "C:\\pagefile.sys"


def test_filter_follows_scope_and_categories():
    t = tree()
    f = flt(roots=["C:\\Users\\me"])                                # My files: Windows is outside
    assert f.dir_state(t, frn(44)) == ntfs.OUT
    assert f.dir_state(t, frn(40)) == ntfs.ABOVE                    # C:\Users: on the way to a root
    assert f.keep_file(t, frn(40), "x.txt") is None                 # not emitted
    f2 = flt(system=False)
    assert f2.dir_state(t, frn(44)) == ntfs.OUT
    assert f2.keep_file(t, frn(42), "id.pem") is None               # secrets off
    assert flt(secrets=True).keep_file(t, frn(42), "id.pem") == "C:\\Users\\me\\Documents\\id.pem"


def test_filter_user_excludes():
    t = tree()
    f = flt(exclude=["C:\\Users\\me\\Documents"])
    assert f.dir_state(t, frn(42)) == ntfs.OUT


def test_filter_asks_the_access_check_once_per_folder():
    """Turbo shows only what the user could list: a folder the user can't open keeps its name, not its files."""
    asked = []

    def can_list(path):
        asked.append(path)
        return path != "C:\\Users\\me\\Documents"
    t = tree()
    f = ntfs.Filter(scope.Rules(profile="C:\\Users\\me", others=[]), roots=["C:\\"], exclude=[], can_list=can_list)
    assert f.keep_dir(t, frn(42)) == "C:\\Users\\me\\Documents"     # its name is visible in its parent
    assert f.keep_file(t, frn(42), "a.txt") is None
    assert f.keep_file(t, frn(42), "b.txt") is None
    assert asked.count("C:\\Users\\me\\Documents") == 1


def test_a_failing_access_check_fails_closed():
    def boom(path):
        raise OSError("no")
    t = tree()
    f = ntfs.Filter(scope.Rules(profile="C:\\Users\\me", others=[]), roots=["C:\\"], exclude=[], can_list=boom)
    assert f.keep_file(t, frn(42), "a.txt") is None


# ---------- journal ----------
def test_journal_data_unpack():
    raw = struct.pack("<QqqqqQQ", 0x1234, 100, 5000, 100, 2**62, 32 << 20, 8 << 20)
    j = ntfs.unpack_journal(raw)
    assert (j.journal_id, j.first_usn, j.next_usn, j.lowest_valid) == (0x1234, 100, 5000, 100)


@pytest.mark.parametrize("since,want", [
    (None, "full"), ({"journal": 0x1234, "usn": 4000}, "catch_up"), ({"journal": 0x9999, "usn": 4000}, "full"),
    ({"journal": 0x1234, "usn": 50}, "full"),                      # older than the journal keeps: wrapped
    ({"journal": 0x1234, "usn": 6000}, "full"),                    # newer than the journal: reset
])
def test_catch_up_or_full_scan(since, want):
    j = ntfs.Journal(0x1234, 100, 5000, 100)
    assert ntfs.plan_scan(j, since) == want


def test_changes_from_journal_records():
    t = tree()
    f = flt()
    recs = [ntfs.UsnRecord(frn(80), frn(42), 1, 0, ntfs.R_CREATE | ntfs.R_CLOSE, 0, "new.txt"),
            ntfs.UsnRecord(frn(81), frn(43), 2, 0, ntfs.R_CREATE, 0, "bob.txt"),          # another profile
            ntfs.UsnRecord(frn(42), frn(41), 3, 0, ntfs.R_RENAME_OLD, ntfs.DIR, "Documents"),
            ntfs.UsnRecord(frn(42), frn(41), 4, 0, ntfs.R_RENAME_NEW, ntfs.DIR, "Docs")]
    paths = ntfs.apply_changes(t, f, recs)
    assert paths == ["C:\\Users\\me\\Documents\\new.txt", "C:\\Users\\me\\Documents", "C:\\Users\\me\\Docs"]
    assert t.path(frn(42)) == "C:\\Users\\me\\Docs"


def test_a_deleted_folder_leaves_the_tree():
    t = tree()
    paths = ntfs.apply_changes(t, flt(), [ntfs.UsnRecord(frn(42), frn(41), 1, 0, ntfs.R_DELETE | ntfs.R_CLOSE,
                                                          ntfs.DIR, "Documents")])
    assert paths == ["C:\\Users\\me\\Documents"] and t.path(frn(42)) is None


# ---------- the helper's messages ----------
def test_config_from_the_engine_only_narrows():
    good = {"t": "config", "roots": ["C:\\Users\\me", "C:\\"], "exclude": ["C:\\Temp"], "include_system": False,
            "include_caches": True, "include_secrets": False}
    c = ntfs.parse_config(good)
    assert c["roots"] == ["C:\\Users\\me", "C:\\"] and c["include_system"] is False
    for bad in ({"t": "config", "roots": "C:\\"}, {"t": "config", "roots": ["relative"]},
                {"t": "config", "roots": ["C:\\" + "x" * 2000]}, {"t": "config", "roots": ["C:\\a\x00b"]},
                {"t": "config", "roots": ["\\\\server\\share"]}, {"t": "config", "include_system": "yes"}):
        with pytest.raises(ValueError):
            ntfs.parse_config(bad)


def test_scan_request_drive_letters_only():
    assert ntfs.parse_drive({"t": "scan", "drive": "c:\\"}) == "C:\\"
    for bad in ("C:", "CC:\\", "\\\\.\\C:", "1:\\", "C:\\Windows", 5):
        with pytest.raises(ValueError):
            ntfs.parse_drive({"t": "scan", "drive": bad})


def test_since_is_checked():
    assert ntfs.parse_since({"since": {"journal": 5, "usn": 10}}) == {"journal": 5, "usn": 10}
    assert ntfs.parse_since({}) is None
    for bad in ({"since": {"journal": "5", "usn": 1}}, {"since": {"journal": 5, "usn": -1}}, {"since": []},
                {"since": {"journal": True, "usn": 1}}):
        with pytest.raises(ValueError):
            ntfs.parse_since(bad)


def test_line_reader_caps_lines():
    r = ntfs.Lines(max_line=64)
    assert r.feed(b'{"t":"a"}\n{"t"') == [{"t": "a"}]
    assert r.feed(b':"b"}\n') == [{"t": "b"}]
    with pytest.raises(ValueError):
        r.feed(b"x" * 100)
    with pytest.raises(ValueError):
        ntfs.Lines().feed(b"[1,2]\n")                     # only objects
    with pytest.raises(ValueError):
        ntfs.Lines().feed(b'{"t": NaN}\n')


def test_messages_are_ascii_lines():
    line = ntfs.encode({"t": "rows", "rows": [["C:\\é", 0, 1, 2.0, 3.0]]})
    assert line.endswith(b"\n") and line.isascii() and json.loads(line)["rows"][0][0] == "C:\\é"


def test_fixed_words_only():
    assert set(ntfs.WORDS) == {"serve", "selftest"}
    assert ntfs.helper_main("rm -rf") == 2
    assert ntfs.helper_main("") == 2


def test_helper_refuses_to_run_without_admin(monkeypatch):
    monkeypatch.setenv(ntfs.DEV_ENV, "1")
    monkeypatch.setattr(ntfs.winapi, "is_admin", lambda: False)
    assert ntfs.helper_main("serve") == 3
    assert ntfs.helper_main("selftest") == 3


def test_filetime():
    assert ntfs.filetime(ft(1_700_000_000)) == pytest.approx(1_700_000_000)
    assert ntfs.filetime(0) is None


def test_the_root_comes_from_the_volume():
    """Record 5 is the root; its sequence number is whatever the volume says, and it is its own parent."""
    t = ntfs.Tree("D:\\", root=0)
    root = frn(5, seq=9)
    t.set_root(root)
    t.add_dir(root, root, ".")                          # ignored: no loop through the root
    t.add_dir(frn(40), root, "Data")
    assert t.path(frn(40)) == "D:\Data" and t.path(root) == "D:\\"


def test_enum_input_is_the_padded_v1_struct():
    import inspect
    assert '"<QqqHH4x"' in inspect.getsource(ntfs.Volume.enum)
    assert struct.calcsize("<QqqHH4x") == 32


# ---------- security review of #79: the engine's config can't open another profile ----------
@pytest.mark.parametrize("roots", [["C:\\Users\\Bob"], ["C:\\Users\\Bob\\Documents"],
                                   ["C:\\Users\\Bob", "C:\\Users\\Bob\\Documents", "C:\\"]])
def test_a_config_naming_another_profile_still_gets_nothing_from_it(roots):
    t = tree()
    t.add_dir(frn(45), frn(43), "Documents")                        # C:\\Users\\Bob\\Documents
    rules = scope.Rules(profile="C:\\Users\\me", others=["C:\\Users\\Bob"], secrets=True)
    f = ntfs.Filter(rules, roots=roots, exclude=[])
    for ref in (frn(43), frn(45)):
        assert f.dir_state(t, ref) == ntfs.OUT
        assert f.keep_dir(t, ref) is None
        assert f.keep_file(t, ref, "tax.pdf") is None
    recs = [ntfs.UsnRecord(frn(90), frn(45), 1, 0, ntfs.R_CREATE, 0, "new.docx"),
            ntfs.UsnRecord(frn(46), frn(43), 2, 0, ntfs.R_CREATE, ntfs.DIR, "Secret plans")]
    assert ntfs.apply_changes(t, f, recs) == []


def test_a_config_naming_a_profile_missing_from_profilelist_still_gets_nothing():
    """Default, stale profiles, anything in the profiles folder that isn't yours or Public."""
    t = tree()
    rules = scope.Rules(profile="C:\\Users\\me", others=[])          # ProfileList didn't list Bob
    f = ntfs.Filter(rules, roots=["C:\\Users\\Bob"], exclude=[])
    assert f.dir_state(t, frn(43)) == ntfs.OUT and f.keep_file(t, frn(43), "x.txt") is None


# ---------- security review of #79: from source the helper is dev only ----------
def test_from_source_the_helper_needs_the_dev_switch(monkeypatch):
    monkeypatch.setattr(ntfs.sys, "frozen", False, raising=False)
    monkeypatch.setattr(ntfs.winapi, "is_admin", lambda: True)
    monkeypatch.delenv(ntfs.DEV_ENV, raising=False)
    ran = []
    monkeypatch.setattr(ntfs, "_serve", lambda: ran.append("serve") or 0)
    monkeypatch.setattr(ntfs, "_selftest", lambda: ran.append("selftest") or 0)
    assert ntfs.helper_main("serve") == 6 and ntfs.helper_main("selftest") == 6 and ran == []
    monkeypatch.setenv(ntfs.DEV_ENV, "yes")                         # only exactly "1"
    assert ntfs.helper_main("serve") == 6
    monkeypatch.setenv(ntfs.DEV_ENV, "1")
    assert ntfs.helper_main("serve") == 0 and ran == ["serve"]


def test_the_exe_needs_no_dev_switch(monkeypatch):
    monkeypatch.setattr(ntfs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ntfs.winapi, "is_admin", lambda: True)
    monkeypatch.delenv(ntfs.DEV_ENV, raising=False)
    monkeypatch.setattr(ntfs, "_serve", lambda: 0)
    assert ntfs.helper_main("serve") == 0
