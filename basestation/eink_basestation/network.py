"""Netwerk van het basisstation: Ethernet, Wi-Fi en de installatie-hotspot.

Op het echte apparaat via NetworkManager (`nmcli`); voor ontwikkeling een simulatie.

Voorrang: Ethernet (route-metric 100) gaat altijd voor Wi-Fi (600). Is er na het opstarten
geen enkele verbinding, dan start het basisstation een hotspot "Eink-XXXX" zodat een installateur
met telefoon of laptop de webinterface kan openen (http://10.42.0.1:8080) en het netwerk kan
instellen.
"""

import ipaddress
import logging
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("eink_basestation.network")

ETH_CONNECTION = "eink-ethernet"
WIFI_CONNECTION = "eink-wifi"
HOTSPOT_CONNECTION = "eink-hotspot"
ETH_METRIC = 100
WIFI_METRIC = 600


class NetworkError(Exception):
    pass


@dataclass
class InterfaceStatus:
    name: str
    kind: str  # "ethernet" of "wifi"
    connected: bool
    state: str  # leesbare toestand, bv. "verbonden", "geen kabel"
    connection: str | None = None
    address: str | None = None  # "192.168.1.20/24"
    gateway: str | None = None
    dns: list[str] = field(default_factory=list)
    mac: str | None = None
    ssid: str | None = None
    signal: int | None = None


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    in_use: bool = False


@dataclass
class EthernetConfig:
    method: str = "dhcp"  # "dhcp" of "static"
    address: str = ""  # "192.168.1.50/24"
    gateway: str = ""
    dns: list[str] = field(default_factory=list)

    def validate(self) -> "EthernetConfig":
        """Controleert een vast IP-adres zodat de installateur zichzelf niet buitensluit."""
        if self.method == "dhcp":
            return EthernetConfig()
        if self.method != "static":
            raise ValueError("kies DHCP of vast IP-adres")
        try:
            iface = ipaddress.IPv4Interface(self.address.strip())
        except ValueError:
            raise ValueError("ongeldig IP-adres, gebruik bv. 192.168.1.50/24") from None
        if "/" not in self.address:
            raise ValueError("geef ook het netwerkprefix op, bv. 192.168.1.50/24")
        if iface.ip in (iface.network.network_address, iface.network.broadcast_address) and iface.network.prefixlen < 31:
            raise ValueError("IP-adres mag niet het netwerk- of broadcastadres zijn")
        gateway = None
        if self.gateway.strip():
            try:
                gateway = ipaddress.IPv4Address(self.gateway.strip())
            except ValueError:
                raise ValueError("ongeldige gateway") from None
            if gateway not in iface.network:
                raise ValueError(f"gateway {gateway} ligt niet in het netwerk {iface.network}")
            if gateway == iface.ip:
                raise ValueError("gateway mag niet gelijk zijn aan het eigen IP-adres")
        dns = []
        for d in self.dns:
            if d.strip():
                try:
                    dns.append(str(ipaddress.IPv4Address(d.strip())))
                except ValueError:
                    raise ValueError(f"ongeldige DNS-server: {d}") from None
        return EthernetConfig("static", str(iface), str(gateway) if gateway else "", dns)


class NetworkBackend(Protocol):
    def status(self) -> list[InterfaceStatus]: ...
    def ethernet_config(self) -> EthernetConfig: ...
    def set_ethernet(self, config: EthernetConfig) -> None: ...
    def scan_wifi(self, rescan: bool = False) -> list[WifiNetwork]: ...
    def connect_wifi(self, ssid: str, password: str | None) -> None: ...
    def forget_wifi(self) -> None: ...
    def hotspot_active(self) -> bool: ...
    def start_hotspot(self, ssid: str, password: str) -> None: ...
    def stop_hotspot(self) -> None: ...


def online(interfaces: list[InterfaceStatus]) -> bool:
    return any(i.connected and i.connection != HOTSPOT_CONNECTION for i in interfaces)


# --- NetworkManager -----------------------------------------------------------------------------

Runner = Callable[[list[str]], str]


def run_nmcli(args: list[str]) -> str:
    try:
        result = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NetworkError(f"nmcli mislukt: {exc}") from exc
    if result.returncode != 0:
        raise NetworkError((result.stderr or result.stdout).strip().removeprefix("Error: ") or "nmcli mislukt")
    return result.stdout


def split_terse(line: str) -> list[str]:
    """Splitst een regel uit `nmcli -t` op ':'; '\\:' en '\\\\' zijn escapes."""
    fields, current, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    fields.append("".join(current))
    return fields


DEVICE_STATES = {
    "connected": "verbonden",
    "disconnected": "niet verbonden",
    "unavailable": "geen kabel / niet beschikbaar",
    "connecting": "verbinden…",
    "unmanaged": "niet beheerd",
}


class NetworkManagerBackend:
    def __init__(self, runner: Runner = run_nmcli):
        self.run = runner

    def _devices(self) -> list[tuple[str, str, str, str]]:
        out = self.run(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        rows = [split_terse(l) for l in out.splitlines() if l.strip()]
        return [(r[0], r[1], r[2], r[3]) for r in rows if len(r) >= 4 and r[1] in ("ethernet", "wifi")]

    def _show(self, device: str) -> dict[str, list[str]]:
        out = self.run(["-t", "-f", "GENERAL.HWADDR,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS", "device", "show", device])
        info: dict[str, list[str]] = {}
        for line in out.splitlines():
            key, _, value = line.partition(":")
            if value:
                info.setdefault(key.split("[")[0], []).append(value.replace("\\:", ":"))
        return info

    def status(self) -> list[InterfaceStatus]:
        result = []
        for name, kind, state, connection in self._devices():
            connected = state.startswith("connected")
            info = self._show(name)
            st = InterfaceStatus(
                name=name,
                kind=kind,
                connected=connected,
                state=DEVICE_STATES.get(state.split(" ")[0], state),
                connection=connection if connection and connection != "--" else None,
                address=(info.get("IP4.ADDRESS") or [None])[0],
                gateway=(info.get("IP4.GATEWAY") or [None])[0] or None,
                dns=info.get("IP4.DNS", []),
                mac=(info.get("GENERAL.HWADDR") or [None])[0],
            )
            if st.connection == HOTSPOT_CONNECTION:
                st.state = "installatie-hotspot actief"
            elif kind == "wifi" and connected:
                net = next((n for n in self._scan(rescan="no") if n.in_use), None)
                if net:
                    st.ssid, st.signal = net.ssid, net.signal
            result.append(st)
        return result

    def _ethernet_device(self) -> str:
        for name, kind, *_ in self._devices():
            if kind == "ethernet":
                return name
        raise NetworkError("geen Ethernet-aansluiting gevonden")

    def _wifi_device(self) -> str:
        for name, kind, *_ in self._devices():
            if kind == "wifi":
                return name
        raise NetworkError("geen Wi-Fi-adapter gevonden")

    def _connection_exists(self, name: str) -> bool:
        out = self.run(["-t", "-f", "NAME", "connection", "show"])
        return name in (split_terse(l)[0] for l in out.splitlines())

    def ethernet_config(self) -> EthernetConfig:
        if not self._connection_exists(ETH_CONNECTION):
            return EthernetConfig()
        out = self.run(["-t", "-f", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns", "connection", "show", ETH_CONNECTION])
        values = {}
        for line in out.splitlines():
            key, _, value = line.partition(":")
            values[key] = value.replace("\\:", ":")
        if values.get("ipv4.method") != "manual":
            return EthernetConfig()
        return EthernetConfig(
            "static",
            values.get("ipv4.addresses", "").split(",")[0].strip(),
            "" if values.get("ipv4.gateway") in (None, "--") else values["ipv4.gateway"],
            [d.strip() for d in values.get("ipv4.dns", "").split(",") if d.strip() and d.strip() != "--"],
        )

    def set_ethernet(self, config: EthernetConfig) -> None:
        config = config.validate()
        if not self._connection_exists(ETH_CONNECTION):
            self.run(["connection", "add", "type", "ethernet", "ifname", self._ethernet_device(),
                      "con-name", ETH_CONNECTION, "connection.autoconnect", "yes"])
        if config.method == "dhcp":
            settings = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
        else:
            settings = ["ipv4.method", "manual", "ipv4.addresses", config.address,
                        "ipv4.gateway", config.gateway, "ipv4.dns", ",".join(config.dns)]
        self.run(["connection", "modify", ETH_CONNECTION, *settings, "ipv4.route-metric", str(ETH_METRIC)])
        try:
            self.run(["connection", "up", ETH_CONNECTION])
        except NetworkError as exc:
            # Geen kabel: instelling is opgeslagen en wordt actief zodra de kabel erin gaat.
            log.info("ethernet nog niet actief: %s", exc)

    def _scan(self, rescan: str) -> list[WifiNetwork]:
        out = self.run(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", rescan])
        best: dict[str, WifiNetwork] = {}
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) < 4 or not parts[1]:
                continue  # verborgen netwerken hebben geen SSID
            net = WifiNetwork(parts[1], int(parts[2] or 0), parts[3] or "open", parts[0].strip() == "*")
            # Meerdere access points met hetzelfde SSID: sterkste tonen.
            if net.ssid not in best or net.signal > best[net.ssid].signal or net.in_use:
                best[net.ssid] = net
        return sorted(best.values(), key=lambda n: (not n.in_use, -n.signal))

    def scan_wifi(self, rescan: bool = False) -> list[WifiNetwork]:
        return self._scan("yes" if rescan else "auto")

    def connect_wifi(self, ssid: str, password: str | None) -> None:
        if not ssid or len(ssid) > 32:
            raise NetworkError("netwerknaam (SSID) moet 1–32 tekens zijn")
        if password is not None and not 8 <= len(password) <= 63:
            raise NetworkError("Wi-Fi-wachtwoord moet 8–63 tekens zijn")
        device = self._wifi_device()
        if self.hotspot_active():
            self.stop_hotspot()
        if self._connection_exists(WIFI_CONNECTION):
            self.run(["connection", "delete", WIFI_CONNECTION])
        add = ["connection", "add", "type", "wifi", "ifname", device, "con-name", WIFI_CONNECTION,
               "ssid", ssid, "connection.autoconnect", "yes", "ipv4.route-metric", str(WIFI_METRIC)]
        if password:
            add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
        self.run(add)
        try:
            self.run(["connection", "up", WIFI_CONNECTION])
        except NetworkError as exc:
            self.run(["connection", "delete", WIFI_CONNECTION])
            raise NetworkError(f"verbinden met {ssid} mislukt: {exc}") from exc

    def forget_wifi(self) -> None:
        if self._connection_exists(WIFI_CONNECTION):
            self.run(["connection", "delete", WIFI_CONNECTION])

    def hotspot_active(self) -> bool:
        out = self.run(["-t", "-f", "NAME", "connection", "show", "--active"])
        return HOTSPOT_CONNECTION in (split_terse(l)[0] for l in out.splitlines())

    def start_hotspot(self, ssid: str, password: str) -> None:
        self.run(["device", "wifi", "hotspot", "ifname", self._wifi_device(), "con-name", HOTSPOT_CONNECTION,
                  "ssid", ssid, "password", password])

    def stop_hotspot(self) -> None:
        if self._connection_exists(HOTSPOT_CONNECTION):
            self.run(["connection", "delete", HOTSPOT_CONNECTION])


# --- Simulatie (ontwikkeling zonder NetworkManager) ---------------------------------------------


@dataclass
class SimulatedNetwork:
    cable: bool = True
    eth: EthernetConfig = field(default_factory=EthernetConfig)
    wifi_ssid: str | None = None
    hotspot: str | None = None
    networks: list[WifiNetwork] = field(default_factory=lambda: [
        WifiNetwork("Winkel-WiFi", 82, "WPA2"),
        WifiNetwork("Winkel-Gasten", 64, "WPA2"),
        WifiNetwork("Buren-5G", 31, "WPA2 WPA3"),
    ])
    passwords: dict[str, str] = field(default_factory=lambda: {"Winkel-WiFi": "geheim123", "Winkel-Gasten": "gast1234"})

    def status(self) -> list[InterfaceStatus]:
        eth_addr = self.eth.address if self.eth.method == "static" else "192.168.1.23/24"
        eth = InterfaceStatus("eth0", "ethernet", self.cable, "verbonden" if self.cable else "geen kabel / niet beschikbaar",
                              ETH_CONNECTION if self.cable else None, eth_addr if self.cable else None,
                              (self.eth.gateway or "192.168.1.1") if self.cable else None,
                              (self.eth.dns or ["192.168.1.1"]) if self.cable else [], "D8:3A:DD:00:00:01")
        if self.hotspot:
            wlan = InterfaceStatus("wlan0", "wifi", True, "installatie-hotspot actief", HOTSPOT_CONNECTION,
                                   "10.42.0.1/24", None, [], "D8:3A:DD:00:00:02", self.hotspot)
        elif self.wifi_ssid:
            signal = next((n.signal for n in self.networks if n.ssid == self.wifi_ssid), None)
            wlan = InterfaceStatus("wlan0", "wifi", True, "verbonden", WIFI_CONNECTION, "192.168.1.57/24",
                                   "192.168.1.1", ["192.168.1.1"], "D8:3A:DD:00:00:02", self.wifi_ssid, signal)
        else:
            wlan = InterfaceStatus("wlan0", "wifi", False, "niet verbonden", mac="D8:3A:DD:00:00:02")
        return [eth, wlan]

    def ethernet_config(self) -> EthernetConfig:
        return self.eth

    def set_ethernet(self, config: EthernetConfig) -> None:
        self.eth = config.validate()

    def scan_wifi(self, rescan: bool = False) -> list[WifiNetwork]:
        return sorted((WifiNetwork(n.ssid, n.signal, n.security, n.ssid == self.wifi_ssid) for n in self.networks),
                      key=lambda n: (not n.in_use, -n.signal))

    def connect_wifi(self, ssid: str, password: str | None) -> None:
        if ssid in self.passwords and password != self.passwords[ssid]:
            raise NetworkError(f"verbinden met {ssid} mislukt: onjuist wachtwoord")
        self.hotspot = None
        self.wifi_ssid = ssid

    def forget_wifi(self) -> None:
        self.wifi_ssid = None

    def hotspot_active(self) -> bool:
        return self.hotspot is not None

    def start_hotspot(self, ssid: str, password: str) -> None:
        self.hotspot = ssid

    def stop_hotspot(self) -> None:
        self.hotspot = None


def detect_backend() -> NetworkBackend:
    if shutil.which("nmcli"):
        return NetworkManagerBackend()
    log.warning("nmcli niet gevonden: netwerk wordt gesimuleerd")
    return SimulatedNetwork()


# --- Bewaking: hotspot aan als er geen netwerk is ------------------------------------------------


class NetworkWatchdog:
    """Start de installatie-hotspot als er `grace_s` lang geen netwerk is; stopt hem bij Ethernet."""

    def __init__(self, backend: NetworkBackend, ssid: str, password: str, grace_s: float = 120,
                 enabled: Callable[[], bool] = lambda: True, clock: Callable[[], float] = time.monotonic):
        self.backend, self.ssid, self.password = backend, ssid, password
        self.grace_s, self.enabled, self.clock = grace_s, enabled, clock
        self._offline_since: float | None = None

    def tick(self) -> None:
        interfaces = self.backend.status()
        hotspot = self.backend.hotspot_active()
        if online(interfaces):
            self._offline_since = None
            eth_up = any(i.kind == "ethernet" and i.connected for i in interfaces)
            if hotspot and eth_up:
                log.info("Ethernet verbonden: installatie-hotspot uit")
                self.backend.stop_hotspot()
            return
        now = self.clock()
        if self._offline_since is None:
            self._offline_since = now
        if not hotspot and self.enabled() and now - self._offline_since >= self.grace_s:
            log.warning("geen netwerk: installatie-hotspot %s gestart", self.ssid)
            self.backend.start_hotspot(self.ssid, self.password)

    def run_forever(self, interval_s: float = 10) -> None:
        while True:
            try:
                self.tick()
            except NetworkError as exc:
                log.warning("netwerkbewaking: %s", exc)
            time.sleep(interval_s)


def start_watchdog(watchdog: NetworkWatchdog) -> threading.Thread:
    t = threading.Thread(target=watchdog.run_forever, name="network-watchdog", daemon=True)
    t.start()
    return t
