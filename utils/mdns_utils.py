"""mDNS utility for discovering Matter and smart home devices on local network."""
import ipaddress
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from utils import logging_utils
logger = logging_utils.get_logger(__name__, "mdns_utils")
def _normalize_mac(mac: str) -> Optional[str]:
    """Normalize a MAC address ('8:3a:f2:1:2:3' -> '08:3a:f2:01:02:03')."""
    try:
        parts = mac.strip().lower().split(":")
        if len(parts) != 6:
            return None
        return ":".join(f"{int(p, 16):02x}" for p in parts)
    except (ValueError, AttributeError):
        return None
def _normalize_ip(addr: str) -> Optional[str]:
    """Normalize an IPv4/IPv6 string (drops %scope, canonical IPv6 form)."""
    try:
        return str(ipaddress.ip_address(str(addr).split("%", 1)[0].strip()))
    except ValueError:
        return None
def _run(cmd: List[str], timeout: float) -> str:
    """Run a command and return stdout, even on timeout (dns-sd never exits on its own)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout or ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            return out.decode("utf-8", errors="ignore")
        return out or ""
    except Exception as e:
        logger.debug(f"Command failed {cmd}: {e}")
        return ""


class _TargetIdentity:
    """Everything that can identify the target device on the LAN (IPv4, MAC, IPv6, Device ID)."""
    MAX_MAC_PROBES = 6
    def __init__(self, ipv4: str, device_id: Optional[str]):
        self.ipv4 = _normalize_ip(ipv4) or ipv4
        dev = (device_id or "").strip().upper()
        self.device_id: Optional[str] = dev if dev and dev not in ("UNKNOWN", "N/A") else None
        self.iface: Optional[str] = None
        self.mac: Optional[str] = None
        self.ipv6: Set[str] = set()
        self._ndp: Dict[str, str] = {}
        self._mac_probes_left = self.MAX_MAC_PROBES

    @classmethod
    def build(cls, ipv4: str, device_id: Optional[str]) -> "_TargetIdentity":
        ident = cls(ipv4, device_id)
        route_out = _run(["route", "-n", "get", ident.ipv4], timeout=2.0)
        m_iface = re.search(r"interface:\s*(\S+)", route_out)
        ident.iface = m_iface.group(1) if m_iface else None
        _run(["ping", "-c", "1", "-t", "1", ident.ipv4], timeout=2.0)  # populate ARP cache
        arp_out = _run(["arp", "-n", ident.ipv4], timeout=2.0)
        m_mac = re.search(r"\sat\s+([0-9a-fA-F:]+)\s", arp_out)
        ident.mac = _normalize_mac(m_mac.group(1)) if m_mac else None
        if ident.mac and ident.iface:
            _run(["ping6", "-c", "2", f"ff02::1%{ident.iface}"], timeout=3.0)  # populate NDP cache
        ident._refresh_ndp()
        if ident.mac:
            ident.ipv6 = {addr for addr, mac in ident._ndp.items() if mac == ident.mac}
        logger.info(
            f"mDNS target identity: ipv4={ident.ipv4} iface={ident.iface} mac={ident.mac} "
            f"ipv6={sorted(ident.ipv6)} device_id={ident.device_id}"
        )
        if not ident.mac:
            logger.warning(
                f"Could not resolve MAC for {ident.ipv4} (route iface={ident.iface}). "
                "Host may not be on the same L2 network as the device."
            )
        return ident

    def _refresh_ndp(self) -> None:
        table: Dict[str, str] = {}
        for line in _run(["ndp", "-an"], timeout=3.0).splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            addr, mac = _normalize_ip(parts[0]), _normalize_mac(parts[1])
            if addr and mac:
                table[addr] = mac
        self._ndp = table

    def _mac_for_ipv6(self, addr: str) -> Optional[str]:
        if addr in self._ndp:
            return self._ndp[addr]
        if self._mac_probes_left <= 0:
            return None
        self._mac_probes_left -= 1
        target = addr
        try:
            if ipaddress.ip_address(addr).is_link_local and self.iface:
                target = f"{addr}%{self.iface}"
        except ValueError:
            return None
        _run(["ping6", "-c", "1", target], timeout=1.5)
        self._refresh_ndp()
        return self._ndp.get(addr)

    def match(self, service_name: str, addresses: List[str]) -> Optional[str]:
        """Return the match method ('device_id'/'ipv4'/'ipv6_ndp'/'ipv6_mac') or None."""
        instance = service_name.split(".")[0].upper()
        if self.device_id and instance.endswith("-" + self.device_id):
            return "device_id"
        normalized = {n for n in (_normalize_ip(a) for a in addresses) if n}
        if self.ipv4 in normalized:
            return "ipv4"
        if normalized & self.ipv6:
            return "ipv6_ndp"
        if self.mac:
            for addr in sorted(normalized):
                if ":" in addr and self._mac_for_ipv6(addr) == self.mac:
                    self.ipv6.add(addr)
                    return "ipv6_mac"
        return None


class MDNSUtils:
    """Utility to query and resolve local network mDNS information."""
    MATTER_OPERATIONAL = "_matter._tcp.local."
    MATTER_COMMISSIONABLE = "_matterc._udp.local."
    GOOGLECAST = "_googlecast._tcp.local."
    RESOLVE_TIMEOUT_MS = 1500
    DNS_SD_BUDGET_S = 10.0

    @staticmethod
    def _empty_result(status: str = "NOT_FOUND") -> Dict[str, Any]:
        return {
            "mdns_status": status,
            "mdns_hostname": "N/A",
            "mdns_service_name": "N/A",
            "mdns_port": "N/A",
            "mdns_txt": "N/A"
        }

    @classmethod
    def resolve_mdns_by_ip(
            cls,
            target_ip: str,
            service_type: str = MATTER_OPERATIONAL,
            timeout: float = 3.5,
            device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve mDNS hostname, service name, and port for a specific device.
        Args:
            target_ip: Device IPv4 extracted from GHA (e.g. '192.168.1.100').
            service_type: mDNS service type (default: Matter operational).
            timeout: Browse window in seconds.
            device_id: Optional GHA Device ID; matched against the Matter instance name suffix (NodeID).
        Returns:
            Dict containing:
                - mdns_status: 'DISCOVERED', 'NOT_FOUND' or 'NO_IP'
                - mdns_hostname: e.g. 'ABCDEF123456.local'
                - mdns_service_name: e.g. '1234567890ABCDEF-8E2AA8779CFCFD0D'
                - mdns_port: e.g. '5540'
                - mdns_txt: Formatted string of key=value pairs
        """
        if not target_ip or target_ip == "UNKNOWN":
            return cls._empty_result("NO_IP")
        logger.info(f"Resolving mDNS for IP: {target_ip} (service={service_type}, device_id={device_id})...")
        start = time.time()
        session = cls._start_zeroconf_browse(service_type)
        ident = _TargetIdentity.build(target_ip, device_id)  # runs while zeroconf is browsing
        if session is not None:
            remaining = timeout - (time.time() - start)
            if remaining > 0:
                time.sleep(remaining)
            matched, seen = cls._match_zeroconf(session, ident, service_type)
            if matched:
                return matched
            if seen:
                logger.info(
                    f"mDNS NOT_FOUND: none of {seen} {service_type} instance(s) matched "
                    f"{target_ip} ({time.time() - start:.1f}s)."
                )
                return cls._empty_result()
            logger.warning(
                "zeroconf saw no instances at all. Check macOS Local Network permission for the app "
                "running Python (System Settings > Privacy & Security > Local Network). Trying dns-sd..."
            )
        return cls._resolve_via_macos_dns_sd(ident, service_type, timeout)

    @staticmethod
    def _start_zeroconf_browse(service_type: str) -> Optional[Tuple[Any, Any, Any]]:
        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
        except ImportError:
            logger.debug("Python 'zeroconf' package not available, will use macOS 'dns-sd'.")
            return None
        class _NameCollector(ServiceListener):
            """Only collects names; resolution happens later on the caller thread."""
            def __init__(self) -> None:
                self.names: List[str] = []
            def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
                if name not in self.names:
                    self.names.append(name)
            def update_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
                self.add_service(zc, type_, name)
            def remove_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
                pass
        try:
            try:
                zc = Zeroconf(ip_version=IPVersion.All)
            except Exception as e:
                logger.debug(f"zeroconf IPv4+IPv6 init failed ({e}); using IPv4 only.")
                zc = Zeroconf(ip_version=IPVersion.V4Only)
            collector = _NameCollector()
            browser = ServiceBrowser(zc, service_type, collector)
            return zc, browser, collector
        except Exception as e:
            logger.warning(f"zeroconf init error: {e}")
            return None

    @classmethod
    def _zc_info(cls, zc: Any, service_type: str, name: str) -> Optional[Any]:
        try:
            return zc.get_service_info(service_type, name, timeout=cls.RESOLVE_TIMEOUT_MS)
        except Exception as e:
            logger.debug(f"zeroconf resolve failed for {name}: {e}")
            return None

    @classmethod
    def _match_zeroconf(
            cls, session: Tuple[Any, Any, Any], ident: _TargetIdentity, service_type: str
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        zc, browser, collector = session
        try:
            names = list(collector.names)
            logger.info(
                f"zeroconf saw {len(names)} instance(s) of {service_type}: "
                f"{[n.split('.')[0] for n in names]}"
            )
            for name in names:  # fast path: Device ID in instance name, no address resolution needed
                if ident.match(name, []) == "device_id":
                    return cls._result_from_zc(name, cls._zc_info(zc, service_type, name), "device_id"), len(names)
            for name in names:
                info = cls._zc_info(zc, service_type, name)
                if info is None:
                    continue
                addresses = info.parsed_addresses()
                how = ident.match(name, addresses)
                logger.debug(f"zeroconf {name.split('.')[0]} addrs={addresses} -> {how}")
                if how:
                    return cls._result_from_zc(name, info, how), len(names)
            return None, len(names)
        except Exception as e:
            logger.warning(f"zeroconf match error: {e}")
            return None, 0
        finally:
            try:
                browser.cancel()
            except Exception:
                pass
            try:
                zc.close()
            except Exception:
                pass

    @staticmethod
    def _format_txt(properties: Optional[Dict[Any, Any]]) -> str:
        pairs = []
        for k, v in (properties or {}).items():
            key = k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)
            if v is None:
                val = ""
            elif isinstance(v, bytes):
                val = v.decode("utf-8", errors="ignore")
            else:
                val = str(v)
            pairs.append(f"{key}={val}")
        return "; ".join(pairs) or "None"

    @classmethod
    def _result_from_zc(cls, name: str, info: Optional[Any], how: str) -> Dict[str, Any]:
        res = cls._empty_result("DISCOVERED")
        res["mdns_service_name"] = name.split(".")[0]
        if info is not None:
            if info.server:
                res["mdns_hostname"] = info.server.rstrip(".")
            if info.port:
                res["mdns_port"] = str(info.port)
            res["mdns_txt"] = cls._format_txt(info.properties)
        logger.info(
            f"mDNS matched via zeroconf [{how}]: {res['mdns_service_name']} -> "
            f"{res['mdns_hostname']}:{res['mdns_port']}"
        )
        return res

    @staticmethod
    def _dns_sd_addresses(host: str) -> List[str]:
        """Resolve both A and AAAA records for host via dns-sd (fallback: getaddrinfo)."""
        addrs: List[str] = []
        for line in _run(["dns-sd", "-G", "v4v6", host], timeout=1.5).splitlines():
            parts = line.split()
            if len(parts) < 6 or parts[1] != "Add":
                continue
            for tok in parts[5:]:
                n = _normalize_ip(tok)
                if n and n not in addrs:
                    addrs.append(n)
        if not addrs:
            try:
                for info in socket.getaddrinfo(host, None):
                    n = _normalize_ip(info[4][0])
                    if n and n not in addrs:
                        addrs.append(n)
            except (socket.gaierror, OSError):
                pass
        return addrs
    @classmethod
    def _resolve_via_macos_dns_sd(
            cls, ident: _TargetIdentity, service_type: str, timeout: float
    ) -> Dict[str, Any]:
        """Fallback resolver using native macOS dns-sd tool."""
        res = cls._empty_result()
        reg_type = service_type.replace(".local.", "").replace(".local", "").rstrip(".")  # "_matter._tcp"
        output = _run(["dns-sd", "-B", reg_type, "local."], timeout=timeout)
        instances: List[str] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 7 and parts[1] == "Add":
                inst = " ".join(parts[6:])
                if inst not in instances:
                    instances.append(inst)
        logger.info(f"dns-sd saw {len(instances)} instance(s) of {reg_type}: {instances}")
        if not instances:
            logger.warning(
                "dns-sd also saw nothing. The host is probably not receiving mDNS from the device's LAN "
                "(different network/band, AP isolation, or Local Network permission)."
            )
            return res
        deadline = time.time() + cls.DNS_SD_BUDGET_S
        ordered = sorted(instances, key=lambda i: 0 if ident.match(i, []) == "device_id" else 1)
        for inst in ordered:
            if time.time() > deadline:
                logger.warning("dns-sd resolve budget exhausted.")
                break
            l_out = _run(["dns-sd", "-L", inst, reg_type, "local."], timeout=2.0)
            m_host = re.search(r"can be reached at\s+(\S+):(\d+)", l_out)
            host = m_host.group(1).rstrip(".") if m_host else ""
            port = m_host.group(2) if m_host else "N/A"
            txt = "N/A"
            if m_host:
                after = l_out[m_host.end():].splitlines()[1:]
                pairs = [tok for line in after for tok in line.split() if "=" in tok]
                if pairs:
                    txt = "; ".join(pairs)
            addrs = cls._dns_sd_addresses(host) if host else []
            how = ident.match(inst, addrs)
            logger.debug(f"dns-sd {inst} host={host} addrs={addrs} -> {how}")
            if how:
                logger.info(f"mDNS matched via dns-sd [{how}]: {inst} -> {host}:{port}")
                return {
                    "mdns_status": "DISCOVERED",
                    "mdns_hostname": host or "N/A",
                    "mdns_service_name": inst,
                    "mdns_port": str(port),
                    "mdns_txt": txt
                }
        return res