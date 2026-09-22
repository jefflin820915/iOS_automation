"""mDNS utility for discovering Matter and smart home devices on local network."""
import re
import socket
import subprocess
import time
from typing import Dict, Any, Optional
from utils import logging_utils


logger = logging_utils.get_logger(__name__, "mdns_utils")


class MDNSUtils:
    """Utility to query and resolve local network mDNS information."""
    MATTER_OPERATIONAL = "_matter._tcp.local."
    MATTER_COMMISSIONABLE = "_matterc._udp.local."
    GOOGLECAST = "_googlecast._tcp.local."

    @classmethod
    def resolve_mdns_by_ip(
            cls,
            target_ip: str,
            service_type: str = MATTER_OPERATIONAL,
            timeout: float = 3.5
    ) -> Dict[str, Any]:
        """Resolve mDNS hostname, service name, and port for a specific IP.
        Args:
            target_ip: Device IP extracted from GHA (e.g. '10.242.64.120').
            service_type: mDNS service type (default: Matter operational).
            timeout: Scan timeout in seconds.
        Returns:
            Dict containing:
                - mdns_status: 'DISCOVERED' or 'NOT_FOUND'
                - mdns_hostname: e.g. 'matter-camera.local.'
                - mdns_service_name: e.g. '1234567890ABCDEF-0000000000000001'
                - mdns_port: e.g. '5540'
                - mdns_txt: Formatted string of key=value pairs
        """
        result = {
            "mdns_status": "NOT_FOUND",
            "mdns_hostname": "N/A",
            "mdns_service_name": "N/A",
            "mdns_port": "N/A",
            "mdns_txt": "N/A"
        }
        if not target_ip or target_ip == "UNKNOWN":
            result["mdns_status"] = "NO_IP"
            return result
        logger.info(f"Resolving mDNS for IP: {target_ip} (service={service_type})...")
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceListener, ServiceInfo
            class Listener(ServiceListener):
                def __init__(self):
                    self.services = []
                def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                    info = zc.get_service_info(type_, name)
                    if info:
                        self.services.append(info)
                def update_service(self, zc, type_, name): pass
                def remove_service(self, zc, type_, name): pass
            zc = Zeroconf()
            listener = Listener()
            browser = ServiceBrowser(zc, service_type, listener)
            time.sleep(timeout)
            zc.close()
            for s_info in listener.services:
                ipv4_addrs = [socket.inet_ntoa(a) for a in s_info.addresses if len(a) == 4]
                if target_ip in ipv4_addrs:
                    txt_dict = {
                        k.decode("utf-8", errors="ignore"): v.decode("utf-8", errors="ignore")
                        for k, v in s_info.properties.items()
                    }
                    txt_str = "; ".join([f"{k}={v}" for k, v in txt_dict.items()])
                    logger.info(f"mDNS matched via zeroconf: {s_info.name} -> {s_info.server}")
                    return {
                        "mdns_status": "DISCOVERED",
                        "mdns_hostname": s_info.server.rstrip("."),
                        "mdns_service_name": s_info.name.split(".")[0],
                        "mdns_port": str(s_info.port),
                        "mdns_txt": txt_str or "None"
                    }
        except ImportError:
            logger.debug("Python 'zeroconf' package not installed, falling back to macOS 'dns-sd'...")
        except Exception as e:
            logger.warning(f"zeroconf scan error: {e}, falling back to dns-sd...")
        return cls._resolve_via_macos_dns_sd(target_ip, service_type, timeout)
    @classmethod
    def _resolve_via_macos_dns_sd(cls, target_ip: str, service_type: str, timeout: float) -> Dict[str, Any]:
        """Fallback resolver using native macOS dns-sd tool."""
        res = {
            "mdns_status": "NOT_FOUND",
            "mdns_hostname": "N/A",
            "mdns_service_name": "N/A",
            "mdns_port": "N/A",
            "mdns_txt": "N/A"
        }
        try:
            browse_cmd = ["dns-sd", "-B", service_type.rstrip("."), "local."]
            proc = subprocess.run(browse_cmd, capture_output=True, text=True, timeout=timeout)
            output = proc.stdout
        except subprocess.TimeoutExpired as e:
            output = e.stdout.decode("utf-8", errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
        except Exception:
            return res
        instances = []
        for line in output.splitlines():
            if "Add" in line and service_type.split(".")[0] in line:
                parts = line.split()
                if len(parts) >= 7:
                    instances.append(" ".join(parts[6:]))
        for inst in set(instances):
            try:
                lookup_cmd = ["dns-sd", "-L", inst, service_type.rstrip("."), "local."]
                proc = subprocess.run(lookup_cmd, capture_output=True, text=True, timeout=2.0)
                l_out = proc.stdout
            except subprocess.TimeoutExpired as e:
                l_out = e.stdout.decode("utf-8", errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
            except Exception:
                continue
            if m_host := re.search(r"can be reached at\s+([^\s:]+)\.?:(\d+)", l_out):
                host = m_host.group(1).rstrip(".")
                port = m_host.group(2)
                try:
                    resolved_ip = socket.gethostbyname(f"{host}.local")
                except Exception:
                    resolved_ip = ""
                if resolved_ip == target_ip:
                    logger.info(f"mDNS matched via dns-sd: {inst} -> {host}.local:{port}")
                    return {
                        "mdns_status": "DISCOVERED",
                        "mdns_hostname": f"{host}.local",
                        "mdns_service_name": inst,
                        "mdns_port": str(port),
                        "mdns_txt": "N/A (dns-sd)"
                    }
        return res