from nobadvpn import netinfo as ni

ROUTE4 = """
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.50     35
          0.0.0.0          0.0.0.0         On-link        10.2.0.2      5
        127.0.0.0        255.0.0.0         On-link       127.0.0.1    331
"""
ROUTE6 = """
 If Metric Network Destination      Gateway
 12    281 ::/0                     fe80::1
  5      5 ::/0                     On-link
"""


def test_route_parse_skips_tunnel_and_onlink():
    assert ni.parse_route_v4(ROUTE4, ["10.2.0.2"]) == [("192.168.1.1", "192.168.1.50", 35)]
    assert ni.parse_route_v4(ROUTE4) == [("192.168.1.1", "192.168.1.50", 35)]
    assert ni.parse_route_v6(ROUTE6) == [("fe80::1", "12")]


def test_ssid_parse():
    out = "    Name  : Wi-Fi\n    SSID                   : Home 5G\n    BSSID                  : aa:bb:cc:dd:ee:ff\n"
    assert ni.parse_ssid(out) == "Home 5G"
    assert ni.parse_ssid("There is no wireless interface") is None
