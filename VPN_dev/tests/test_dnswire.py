import json
import socket
import struct
import threading

import pytest

from nobadvpn.netintel import dnswire as dw


# ---------------------------------------------------------------- hand-crafted wire helpers (independent of the module)
def wname(n):
    return b"".join(bytes([len(x)]) + x.encode() for x in n.split(".") if x) + b"\x00"


def hdr(qid, flags=0x8180, qd=1, an=0, ns=0, ar=0):
    return struct.pack("!6H", qid, flags, qd, an, ns, ar)


def question(n, t=1):
    return wname(n) + struct.pack("!HH", t, 1)


def rr(owner, t, rdata, ttl=300):
    return owner + struct.pack("!HHIH", t, 1, ttl, len(rdata)) + rdata


def ptr(off):
    return struct.pack("!H", 0xC000 | off)


def test_build_query_layout():
    msg, qid = dw.build_query("WWW.Example.com.", "AAAA")
    assert 0 <= qid < 65536 and struct.unpack("!H", msg[:2])[0] == qid
    assert msg[2:12] == struct.pack("!5H", 0x0100, 1, 0, 0, 1)
    assert msg[12:12 + 17] == wname("www.example.com")
    assert msg[29:33] == struct.pack("!HH", 28, 1)
    assert msg[33:] == b"\x00" + struct.pack("!HHIH", 41, 1232, 0, 0)
    plain, _ = dw.build_query("example.com", 15, rd=False, edns=False, qid=7)
    assert plain[:12] == struct.pack("!6H", 7, 0, 1, 0, 0, 0)


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        dw.build_query("a" * 64 + ".com")
    with pytest.raises(ValueError):
        dw.build_query(".".join(["abcdefg"] * 40))
    with pytest.raises(ValueError):
        dw.build_query("example.com", "BOGUS")
    with pytest.raises(ValueError):
        dw.query("example.com", server="not-an-ip")


def test_a_cname_chain_with_compression():
    q = question("www.example.com")                 # name at offset 12; "example.com" at offset 16
    body = hdr(0x1234, an=2) + q
    cname_rdata = b"\x03cdn" + ptr(16)               # cdn.example.com
    target_off = len(body) + 12                     # CNAME rdata starts after owner(2)+fixed(10)
    body += rr(ptr(12), 5, cname_rdata, ttl=60)
    body += rr(ptr(target_off), 1, bytes([93, 184, 216, 34]), ttl=30)
    p = dw.parse_response(body)
    assert p["error"] is None and p["id"] == 0x1234 and p["rcode_name"] == "NOERROR"
    assert p["flags"]["rd"] and p["flags"]["ra"] and not p["flags"]["tc"]
    assert p["questions"] == [{"name": "www.example.com", "type": "A", "class": 1}]
    assert p["answers"] == [
        {"name": "www.example.com", "type": "CNAME", "ttl": 60, "data": "cdn.example.com"},
        {"name": "cdn.example.com", "type": "A", "ttl": 30, "data": "93.184.216.34"},
    ]
    json.dumps(p)


def test_aaaa_mx_txt():
    v6 = socket.inet_pton(socket.AF_INET6, "2001:db8::1")
    p = dw.parse_response(hdr(1, an=1) + question("example.com", 28) + rr(ptr(12), 28, v6))
    assert p["answers"][0]["data"] == "2001:db8::1" and p["answers"][0]["type"] == "AAAA"

    mx = struct.pack("!H", 10) + b"\x04mail" + ptr(12)
    p = dw.parse_response(hdr(2, an=1) + question("example.com", 15) + rr(ptr(12), 15, mx))
    assert p["answers"][0]["data"] == {"preference": 10, "exchange": "mail.example.com"}

    txt = b"\x05hello" + b"\x00" + bytes([3]) + "é!".encode()
    p = dw.parse_response(hdr(3, an=1) + question("example.com", 16) + rr(ptr(12), 16, txt))
    assert p["answers"][0]["data"] == ["hello", "", "é!"]


def test_nxdomain_with_soa_and_opt_excluded():
    soa = b"\x02ns" + ptr(12) + b"\x0ahostmaster" + ptr(12) + struct.pack("!5I", 2024, 7200, 900, 1209600, 86400)
    body = hdr(9, flags=0x8183, ns=1, ar=1) + question("example.com")   # example.com at offset 12
    body += rr(ptr(12), 6, soa, ttl=900) + b"\x00" + struct.pack("!HHIH", 41, 1232, 0, 0)
    p = dw.parse_response(body)
    assert p["rcode"] == 3 and p["rcode_name"] == "NXDOMAIN" and p["answers"] == [] and p["additional"] == []
    assert p["authority"] == [{"name": "example.com", "type": "SOA", "ttl": 900, "data": {
        "mname": "ns.example.com", "rname": "hostmaster.example.com", "serial": 2024, "refresh": 7200,
        "retry": 900, "expire": 1209600, "minimum": 86400}}]


def test_unknown_type_is_hex():
    p = dw.parse_response(hdr(4, an=1) + question("example.com", 99) + rr(ptr(12), 99, b"\xde\xad"))
    assert p["answers"][0]["type"] == "TYPE99" and p["answers"][0]["data"] == {"type_code": 99, "hex": "dead"}


def test_compression_loop_is_malformed():
    body = hdr(5, an=1) + question("example.com") + rr(ptr(len(hdr(0)) + 17), 1, b"\x01\x02\x03\x04")
    loop_off = len(hdr(0)) + 17                       # the answer owner points at itself
    assert body[loop_off:loop_off + 2] == ptr(loop_off)
    assert dw.parse_response(body)["error"] == "malformed"
    two = hdr(5, qd=1, an=0) + ptr(14) + ptr(12) + b"\x00\x01\x00\x01"   # 12 -> 14 -> 12 ...
    assert dw.parse_response(two)["error"] == "malformed"


@pytest.mark.parametrize("cut", [5, 13, 20, 30, -3, -1])
def test_truncated_packet_is_malformed(cut):
    full = hdr(6, an=1) + question("example.com") + rr(ptr(12), 1, b"\x01\x02\x03\x04")
    p = dw.parse_response(full[:cut])
    assert p["error"] == "malformed" and p["rcode"] is None and p["answers"] == []


def test_ptr_name():
    assert dw.ptr_name("192.0.2.5") == "5.2.0.192.in-addr.arpa"
    assert dw.ptr_name("2001:db8::1").endswith(".8.b.d.0.1.0.0.2.ip6.arpa")


# ---------------------------------------------------------------- local responders (127.0.0.1 only, no internet)
def reply_for(request, an=b"", ancount=0, flags=0x8180, qid=None):
    qend = request.index(b"\x00", 12) + 5
    rid = request[:2] if qid is None else struct.pack("!H", qid)
    return rid + struct.pack("!5H", flags, 1, ancount, 0, 0) + request[12:qend] + an


class UdpResponder:
    def __init__(self, handler):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.handler = handler
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        try:
            data, peer = self.sock.recvfrom(4096)
        except OSError:
            return
        for d in self.handler(data):
            self.sock.sendto(d, peer)

    def close(self):
        self.sock.close()
        self.t.join(2)


def a_answer(ip="10.9.8.7"):
    return rr(ptr(12), 1, socket.inet_aton(ip), ttl=42)


def test_udp_end_to_end():
    srv = UdpResponder(lambda req: [reply_for(req, a_answer(), 1)])
    try:
        r = dw.query("Test.Example", "A", server="127.0.0.1", port=srv.port, timeout=2)
    finally:
        srv.close()
    assert r["error"] is None and r["transport"] == "udp" and r["rcode_name"] == "NOERROR"
    assert r["answers"] == [{"name": "test.example", "type": "A", "ttl": 42, "data": "10.9.8.7"}]
    assert r["rtt_ms"] >= 0 and r["server"] == "127.0.0.1" and r["name"] == "test.example"
    json.dumps(r)


def test_spoofed_datagrams_ignored_then_real_answer():
    def handler(req):
        qid = struct.unpack("!H", req[:2])[0]
        wrong_q = reply_for(req, a_answer("6.6.6.6"), 1).replace(wname("spoof.example"), wname("other.example"))
        return [reply_for(req, a_answer("6.6.6.6"), 1, qid=qid ^ 1), wrong_q, reply_for(req, a_answer(), 1)]
    srv = UdpResponder(handler)
    try:
        r = dw.query("spoof.example", server="127.0.0.1", port=srv.port, timeout=2)
    finally:
        srv.close()
    assert r["error"] is None and [a["data"] for a in r["answers"]] == ["10.9.8.7"]


def test_mismatched_id_ignored_then_timeout():
    srv = UdpResponder(lambda req: [reply_for(req, a_answer(), 1, qid=struct.unpack("!H", req[:2])[0] ^ 0xFFFF)])
    try:
        r = dw.query("x.example", server="127.0.0.1", port=srv.port, timeout=0.5)
    finally:
        srv.close()
    assert r["error"] == "timeout" and r["rcode"] is None and r["answers"] == []


def test_tc_bit_falls_back_to_tcp():
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for _ in range(20):                                # find a port free for both UDP and TCP
        udp = UdpResponder(lambda req: [reply_for(req, flags=0x8380)])   # TC set, no answers
        try:
            tcp.bind(("127.0.0.1", udp.port))
            break
        except OSError:
            udp.close()
    else:
        pytest.skip("no free UDP+TCP port pair")
    tcp.listen(1)
    seen = {}

    def serve_tcp():
        conn, _ = tcp.accept()
        with conn:
            n = struct.unpack("!H", conn.recv(2))[0]
            req = b""
            while len(req) < n:
                req += conn.recv(n - len(req))
            seen["req"] = req
            big = b"".join(rr(ptr(12), 1, bytes([10, 0, 0, i])) for i in range(1, 6))
            resp = reply_for(req, big, 5)
            conn.sendall(struct.pack("!H", len(resp)) + resp)
    t = threading.Thread(target=serve_tcp, daemon=True)
    t.start()
    try:
        r = dw.query("big.example", server="127.0.0.1", port=udp.port, timeout=2)
    finally:
        udp.close()
        t.join(2)
        tcp.close()
    assert r["error"] is None and r["transport"] == "tcp" and not r["flags"]["tc"]
    assert [a["data"] for a in r["answers"]] == [f"10.0.0.{i}" for i in range(1, 6)]
    assert seen["req"][12:12 + len(wname("big.example"))] == wname("big.example")


def test_closed_port_never_raises():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = dw.query("x.example", server="127.0.0.1", port=port, timeout=0.5)
    assert r["error"] in ("timeout", "refused-connection") and r["rcode"] is None
    r = dw.query("x.example", server="127.0.0.1", port=port, timeout=0.5, tcp=True)
    assert r["error"] in ("timeout", "refused-connection") and r["transport"] == "tcp"
