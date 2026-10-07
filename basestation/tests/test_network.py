import pytest

from eink_basestation.network import (
    ETH_CONNECTION, HOTSPOT_CONNECTION, WIFI_CONNECTION, EthernetConfig, NetworkError,
    NetworkManagerBackend, NetworkWatchdog, SimulatedNetwork, split_terse,
)


def test_split_terse_escapes():
    assert split_terse("eth0:ethernet:connected:eink-ethernet") == ["eth0", "ethernet", "connected", "eink-ethernet"]
    assert split_terse(r"*:Bakkerij\:Gast:70:WPA2") == ["*", "Bakkerij:Gast", "70", "WPA2"]
    assert split_terse(r"a\\:b") == ["a\\", "b"]


@pytest.mark.parametrize("cfg, error", [
    (EthernetConfig("static", "192.168.1.50"), "prefix"),
    (EthernetConfig("static", "192.168.1.300/24"), "ongeldig IP"),
    (EthernetConfig("static", "192.168.1.0/24"), "netwerk- of broadcast"),
    (EthernetConfig("static", "192.168.1.50/24", "10.0.0.1"), "ligt niet in het netwerk"),
    (EthernetConfig("static", "192.168.1.50/24", "192.168.1.50"), "gelijk"),
    (EthernetConfig("static", "192.168.1.50/24", "192.168.1.1", ["dns.example"]), "DNS"),
    (EthernetConfig("bridge"), "DHCP"),
])
def test_ethernet_validation(cfg, error):
    with pytest.raises(ValueError, match=error):
        cfg.validate()


def test_ethernet_validation_ok():
    cfg = EthernetConfig("static", " 192.168.1.50/24 ", "192.168.1.1", ["1.1.1.1", ""]).validate()
    assert cfg == EthernetConfig("static", "192.168.1.50/24", "192.168.1.1", ["1.1.1.1"])
    assert EthernetConfig("dhcp", "rommel").validate() == EthernetConfig()


class FakeNmcli:
    """Bootst de nmcli-uitvoer na en onthoudt alle aanroepen."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.connections = {"Wired connection 1"}
        self.active = set()
        self.fail_up = False

    def __call__(self, args):
        self.calls.append(args)
        a = " ".join(args)
        if a.endswith("device status"):
            return "eth0:ethernet:connected:eink-ethernet\nwlan0:wifi:connected:eink-wifi\nlo:loopback:unmanaged:--\n"
        if "device show eth0" in a:
            return ("GENERAL.HWADDR:D8\\:3A\\:DD\\:00\\:00\\:01\nIP4.ADDRESS[1]:192.168.1.23/24\n"
                    "IP4.GATEWAY:192.168.1.1\nIP4.DNS[1]:192.168.1.1\nIP4.DNS[2]:1.1.1.1\n")
        if "device show wlan0" in a:
            return "GENERAL.HWADDR:D8\\:3A\\:DD\\:00\\:00\\:02\nIP4.ADDRESS[1]:192.168.1.57/24\nIP4.GATEWAY:\n"
        if "device wifi list" in a:
            return "*:Winkel:80:WPA2\n :Winkel:40:WPA2\n :Buren:30:WPA1 WPA2\n ::50:WPA2\n :Open-Net:20:\n"
        if a.startswith("-t -f NAME connection show --active"):
            return "".join(f"{c}\n" for c in self.active)
        if a.startswith("-t -f NAME connection show"):
            return "".join(f"{c}\n" for c in self.connections)
        if args[:2] == ["connection", "add"]:
            self.connections.add(args[args.index("con-name") + 1])
        if args[:2] == ["connection", "delete"]:
            self.connections.discard(args[2])
            self.active.discard(args[2])
        if args[:2] == ["connection", "up"]:
            if self.fail_up:
                raise NetworkError("Secrets were required, but not provided")
            self.active.add(args[2])
        if args[:3] == ["device", "wifi", "hotspot"]:
            self.connections.add(HOTSPOT_CONNECTION)
            self.active.add(HOTSPOT_CONNECTION)
        if "connection show eink-ethernet" in a:
            return "ipv4.method:manual\nipv4.addresses:192.168.1.50/24\nipv4.gateway:192.168.1.1\nipv4.dns:1.1.1.1,8.8.8.8\n"
        return ""


def test_nm_status_and_scan():
    nm = NetworkManagerBackend(FakeNmcli())
    eth, wlan = nm.status()
    assert (eth.name, eth.connected, eth.address, eth.gateway, eth.dns, eth.mac) == (
        "eth0", True, "192.168.1.23/24", "192.168.1.1", ["192.168.1.1", "1.1.1.1"], "D8:3A:DD:00:00:01")
    assert (wlan.ssid, wlan.signal, wlan.gateway) == ("Winkel", 80, None)
    nets = nm.scan_wifi()
    assert [(n.ssid, n.signal, n.in_use) for n in nets] == [("Winkel", 80, True), ("Buren", 30, False), ("Open-Net", 20, False)]
    assert nets[2].security == "open"


def test_nm_set_ethernet_static_and_dhcp():
    fake = FakeNmcli()
    nm = NetworkManagerBackend(fake)
    nm.set_ethernet(EthernetConfig("static", "192.168.1.50/24", "192.168.1.1", ["1.1.1.1"]))
    assert ["connection", "add", "type", "ethernet", "ifname", "eth0", "con-name", ETH_CONNECTION,
            "connection.autoconnect", "yes"] in fake.calls
    modify = next(c for c in fake.calls if c[:2] == ["connection", "modify"])
    assert modify[modify.index("ipv4.method") + 1] == "manual"
    assert modify[modify.index("ipv4.addresses") + 1] == "192.168.1.50/24"
    assert modify[modify.index("ipv4.route-metric") + 1] == "100"
    assert nm.ethernet_config() == EthernetConfig("static", "192.168.1.50/24", "192.168.1.1", ["1.1.1.1", "8.8.8.8"])

    fake.calls.clear()
    nm.set_ethernet(EthernetConfig("dhcp"))
    modify = next(c for c in fake.calls if c[:2] == ["connection", "modify"])
    assert modify[modify.index("ipv4.method") + 1] == "auto"
    assert not any(c[:2] == ["connection", "add"] for c in fake.calls)  # bestaat al


def test_nm_wifi_connect_stops_hotspot_and_cleans_up_on_failure():
    fake = FakeNmcli()
    nm = NetworkManagerBackend(fake)
    nm.start_hotspot("Eink-AB12", "hotspotpw")
    assert nm.hotspot_active()
    nm.connect_wifi("Winkel", "geheim123")
    assert not nm.hotspot_active() and WIFI_CONNECTION in fake.active
    add = next(c for c in fake.calls if c[:2] == ["connection", "add"] and "wifi" in c)
    assert add[add.index("wifi-sec.psk") + 1] == "geheim123" and add[add.index("ipv4.route-metric") + 1] == "600"

    fake.fail_up = True
    with pytest.raises(NetworkError, match="verbinden met Winkel mislukt"):
        nm.connect_wifi("Winkel", "fout-wachtwoord")
    assert WIFI_CONNECTION not in fake.connections  # geen kapotte verbinding achterlaten

    with pytest.raises(NetworkError, match="8–63"):
        nm.connect_wifi("Winkel", "kort")


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_watchdog_starts_and_stops_hotspot():
    net, clock = SimulatedNetwork(cable=False), Clock()
    wd = NetworkWatchdog(net, "Eink-AB12", "hotspotpw", grace_s=120, clock=clock)
    wd.tick()
    assert not net.hotspot_active()
    clock.t = 119
    wd.tick()
    assert not net.hotspot_active()
    clock.t = 121
    wd.tick()
    assert net.hotspot == "Eink-AB12"
    clock.t = 500
    wd.tick()  # hotspot telt niet als "online": blijft gewoon aan
    assert net.hotspot_active()

    net.cable = True  # monteur steekt kabel in
    wd.tick()
    assert not net.hotspot_active()


def test_watchdog_respects_disabled_and_wifi():
    net, clock = SimulatedNetwork(cable=False), Clock()
    enabled = [False]
    wd = NetworkWatchdog(net, "Eink-AB12", "pw", grace_s=0, clock=clock, enabled=lambda: enabled[0])
    wd.tick()
    assert not net.hotspot_active()
    enabled[0] = True
    net.connect_wifi("Winkel-WiFi", "geheim123")
    wd.tick()
    assert not net.hotspot_active()  # Wi-Fi verbonden = online
