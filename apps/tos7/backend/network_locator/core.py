"""Network discovery, neighbor parsing, and background scan state."""

from __future__ import annotations

import concurrent.futures
import inspect
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Iterable, Sequence

APP_ID = "network-locator"
DEFAULT_MAX_HOSTS = 1022
DEFAULT_CONCURRENCY = 64
MAX_SCAN_SUFFIXES = 8
MAX_NETWORK_SELECTION = 64
MAX_NETWORK_ID_LENGTH = 256
ALLOWED_NEIGHBOR_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE"}
DEVICE_STATE_PRIORITY = {
    "STALE": 1,
    "PROBE": 2,
    "DELAY": 3,
    "REACHABLE": 4,
    "LOCAL": 5,
}
MAC_SUFFIX_PATTERN = re.compile(
    r"^(?:[0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2}|[0-9A-Fa-f]{4})$"
)
VIRTUAL_INTERFACE_PREFIXES = (
    "docker",
    "veth",
    "virbr",
    "vmnet",
    "tailscale",
    "tun",
    "tap",
    "wg",
    "zt",
    "cni",
    "flannel",
    "podman",
    "lxc",
    "kube",
    "dummy",
    "lo",
)


class CommandError(RuntimeError):
    """Raised when a required local network command fails."""


class ScanCancelled(RuntimeError):
    """Internal cancellation signal."""


@dataclass(frozen=True)
class NetworkTarget:
    interface: str
    alias: str
    local_ip: str
    prefix_length: int
    gateway: str
    network: str
    broadcast: str
    scan_range: str
    host_count: int
    local_source: str
    local_mac: str

    def as_dict(self) -> dict:
        return asdict(self)


def network_target_key(target: NetworkTarget) -> str:
    return f"{target.interface}|{target.scan_range}"


def network_target_payload(target: NetworkTarget) -> dict:
    payload = target.as_dict()
    payload["network_id"] = network_target_key(target)
    return payload


def normalize_network_ids(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("network_ids 必须是数组")
    selected: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("network_ids 只能包含字符串")
        text = item.strip()
        if not text:
            raise ValueError("network_ids 不能包含空值")
        if len(text) > MAX_NETWORK_ID_LENGTH:
            raise ValueError("网段标识过长")
        if text not in selected:
            selected.append(text)
    if not selected:
        raise ValueError("至少选择一个网段")
    if len(selected) > MAX_NETWORK_SELECTION:
        raise ValueError(f"最多选择 {MAX_NETWORK_SELECTION} 个网段")
    return selected


def select_network_targets(
    targets: Sequence[NetworkTarget],
    network_ids: Sequence[str] | None,
) -> tuple[list[NetworkTarget], list[str]]:
    available = list(targets)
    if network_ids is None:
        return available, []
    wanted = set(network_ids)
    available_ids = {network_target_key(target) for target in available}
    selected = [
        target for target in available if network_target_key(target) in wanted
    ]
    missing = [network_id for network_id in network_ids if network_id not in available_ids]
    return selected, missing


@dataclass(frozen=True)
class NeighborRecord:
    interface: str
    ip: str
    mac: str
    state: str


def normalize_mac_suffix(value: str) -> str | None:
    text = str(value or "").strip()
    if MAC_SUFFIX_PATTERN.fullmatch(text) is None:
        return None
    return re.sub(r"[-:]", "", text).upper()


def normalize_mac_suffixes(value: object) -> list[str]:
    """Normalize one suffix or a list of suffixes for a multi-target scan."""

    if isinstance(value, str):
        values: list[object] = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise ValueError("MAC suffixes must be an array")

    suffixes: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError("MAC suffixes must be strings")
        normalized = normalize_mac_suffix(item)
        if normalized is None:
            raise ValueError("MAC suffix must use AA-BB, AA:BB, or AABB format")
        if normalized not in suffixes:
            suffixes.append(normalized)

    if not suffixes:
        raise ValueError("at least one MAC suffix is required")
    if len(suffixes) > MAX_SCAN_SUFFIXES:
        raise ValueError(f"at most {MAX_SCAN_SUFFIXES} MAC suffixes are allowed")
    return suffixes


def normalize_mac(value: str) -> str | None:
    text = str(value or "").strip().replace("-", "").replace(":", "")
    if re.fullmatch(r"[0-9A-Fa-f]{12}", text) is None:
        return None
    upper = text.upper()
    return "-".join(upper[index : index + 2] for index in range(0, 12, 2))


def parse_ipv4_network(address: str, prefix_length: int) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(
            f"{address}/{int(prefix_length)}",
            strict=False,
        )
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
        raise CommandError(f"invalid IPv4 network {address}/{prefix_length}: {exc}") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise CommandError(f"not an IPv4 network: {address}/{prefix_length}")
    return network


def network_host_count(network: ipaddress.IPv4Network) -> int:
    """Count probe targets without materializing every address in the subnet."""

    if network.prefixlen <= 30:
        return max(0, network.num_addresses - 2)
    if network.prefixlen == 31:
        return 2
    return 1


def network_hosts(network: ipaddress.IPv4Network) -> list[ipaddress.IPv4Address]:
    if network.prefixlen <= 30:
        return list(network.hosts())
    if network.prefixlen == 31:
        return list(network)
    return [network.network_address]


def is_scannable_local_address(address: str) -> bool:
    """Reject addresses that cannot identify a real LAN interface."""

    try:
        parsed = ipaddress.IPv4Address(str(address or "").strip())
    except ValueError:
        return False
    return not (
        parsed.is_unspecified
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
    )


def is_virtual_interface(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    if not lowered:
        return True
    return any(
        lowered == prefix or lowered.startswith(prefix)
        for prefix in VIRTUAL_INTERFACE_PREFIXES
    )


def run_command(command: Sequence[str], timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandError(f"{' '.join(command)} failed: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CommandError(
            f"{' '.join(command)} exited {result.returncode}: {detail or 'no output'}"
        )
    return result.stdout


def resolve_ip_command(ip_command: str | None = None) -> str:
    if ip_command:
        return ip_command
    for candidate in ("ip", "/usr/sbin/ip", "/sbin/ip", "/usr/bin/ip", "/bin/ip"):
        resolved = shutil.which(candidate) if os.path.sep not in candidate else candidate
        if resolved and os.path.isfile(resolved):
            return resolved
    raise CommandError("the iproute2 'ip' command is not available")


def _json_items(raw: str, label: str) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise CommandError(f"{label} returned invalid JSON: {exc}") from exc
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise CommandError(f"{label} returned an unexpected JSON value")
    return [item for item in value if isinstance(item, dict)]


def discover_networks(
    *,
    runner: Callable[[Sequence[str]], str] = run_command,
    ip_command: str | None = None,
    max_hosts: int | None = None,
) -> tuple[list[NetworkTarget], list[str]]:
    """Discover routed physical IPv4 networks without scanning them yet."""

    command = resolve_ip_command(ip_command)
    configured_max = (
        int(os.environ.get("SCAN_MAX_HOSTS", DEFAULT_MAX_HOSTS))
        if max_hosts is None
        else int(max_hosts)
    )
    limit = max(1, configured_max)
    routes = _json_items(
        runner([command, "-j", "-4", "route", "show", "default"]),
        "ip route",
    )
    addresses = _json_items(
        runner([command, "-j", "-4", "addr", "show"]),
        "ip addr",
    )
    links = _json_items(
        runner([command, "-j", "link", "show"]),
        "ip link",
    )

    by_interface: dict[str, list[dict]] = {}
    interface_macs: dict[str, str] = {}
    for entry in addresses:
        name = str(entry.get("ifname") or "")
        inet_items = [
            item
            for item in (entry.get("addr_info") or [])
            if isinstance(item, dict)
            and item.get("family") == "inet"
            and item.get("local")
            and item.get("prefixlen") is not None
        ]
        if name and inet_items:
            by_interface[name] = inet_items
    for entry in links:
        name = str(entry.get("ifname") or "")
        mac = normalize_mac(str(entry.get("address") or ""))
        if name and mac:
            interface_macs[name] = mac

    warnings: list[str] = []
    skipped_virtual: set[str] = set()
    targets: list[NetworkTarget] = []
    seen: set[tuple[str, str]] = set()
    sorted_routes = sorted(
        routes,
        key=lambda item: int(item.get("metric") or 0),
    )
    for route in sorted_routes:
        interface = str(route.get("dev") or "")
        gateway = str(route.get("gateway") or "")
        if not interface:
            continue
        if is_virtual_interface(interface):
            if interface not in skipped_virtual:
                warnings.append(f"已跳过虚拟网卡 {interface}")
                skipped_virtual.add(interface)
            continue
        interface_addresses = by_interface.get(interface, [])
        if not interface_addresses:
            warnings.append(f"{interface} 没有可用的 IPv4 地址")
            continue
        for address in interface_addresses:
            local_ip = str(address.get("local") or "")
            if not is_scannable_local_address(local_ip):
                continue
            try:
                network = parse_ipv4_network(local_ip, int(address["prefixlen"]))
            except (CommandError, KeyError, TypeError, ValueError) as exc:
                warnings.append(str(exc))
                continue
            key = (interface, str(network))
            if key in seen:
                continue
            host_count = network_host_count(network)
            if host_count > limit:
                warnings.append(
                    f"{interface} 的 {network} 包含 {host_count} 台主机，"
                    f"超过安全上限 {limit}，已跳过"
                )
                continue
            seen.add(key)
            target = NetworkTarget(
                interface=interface,
                alias=interface,
                local_ip=local_ip,
                prefix_length=network.prefixlen,
                gateway=gateway,
                network=str(network.network_address),
                broadcast=str(network.broadcast_address),
                scan_range=str(network),
                host_count=host_count,
                local_source=str(address.get("local") or ""),
                local_mac=interface_macs.get(interface, ""),
            )
            targets.append(target)

    targets.sort(key=lambda target: (target.interface, target.scan_range))
    if not targets and not warnings:
        warnings.append("未找到同时具有 IPv4 地址和默认网关的物理网卡")
    return targets, warnings


def parse_neighbor_items(
    items: Iterable[dict],
    interface: str,
) -> list[NeighborRecord]:
    records: list[NeighborRecord] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_state = item.get("state")
        state_values = raw_state if isinstance(raw_state, list) else [raw_state]
        normalized_states = [
            str(value).upper()
            for value in state_values
            if value is not None and str(value).strip()
        ]
        state = next(
            (
                value
                for value in normalized_states
                if value in ALLOWED_NEIGHBOR_STATES
            ),
            "",
        )
        if not state:
            continue
        ip_value = str(item.get("dst") or "")
        try:
            address = ipaddress.ip_address(ip_value)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address):
            continue
        mac = normalize_mac(str(item.get("lladdr") or ""))
        if mac is None:
            continue
        key = (str(address), mac)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            NeighborRecord(
                interface=str(item.get("dev") or interface),
                ip=str(address),
                mac=mac,
                state=state,
            )
        )
    return records


def read_neighbors(
    interface: str,
    *,
    runner: Callable[[Sequence[str]], str] = run_command,
    ip_command: str | None = None,
) -> list[NeighborRecord]:
    command = resolve_ip_command(ip_command)
    arguments = [command, "-j", "-4", "neigh", "show"]
    if interface:
        arguments.extend(["dev", interface])
    output = runner(arguments)
    return parse_neighbor_items(_json_items(output, "ip neigh"), interface)


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def resolve_ping_command() -> str | None:
    for candidate in ("ping", "/usr/bin/ping", "/bin/ping", "/sbin/ping"):
        resolved = shutil.which(candidate) if os.path.sep not in candidate else candidate
        if resolved and os.path.isfile(resolved):
            return resolved
    return None


def prime_neighbor_cache(
    source_ip: str,
    hosts: Iterable[ipaddress.IPv4Address],
) -> None:
    """Send empty UDP datagrams so the kernel resolves local ARP entries."""

    if not str(source_ip or "").strip():
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((source_ip, 0))
        for host in hosts:
            try:
                sock.sendto(b"", (str(host), 9))
            except OSError:
                continue
    finally:
        sock.close()


def _ping_host(
    ping_command: str,
    interface: str,
    address: ipaddress.IPv4Address,
    timeout_ms: int,
) -> bool:
    wait_seconds = max(1, int(math.ceil(timeout_ms / 1000)))
    command = [
        ping_command,
        "-n",
        "-c",
        "1",
        "-W",
        str(wait_seconds),
    ]
    if interface:
        command.extend(["-I", interface])
    command.append(str(address))
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=wait_seconds + 1.25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def scan_hosts(
    target: NetworkTarget,
    cancel_event: threading.Event,
    progress: Callable[[int], None] | None = None,
    *,
    timeout_ms: int | None = None,
    concurrency: int | None = None,
    ping_command: str | None = None,
    pause_event: threading.Event | None = None,
    primer: Callable[[str, Iterable[ipaddress.IPv4Address]], None] = prime_neighbor_cache,
) -> bool:
    """Probe every host in a bounded network. Return whether ping was available."""

    network = parse_ipv4_network(target.local_ip, target.prefix_length)
    hosts = network_hosts(network)
    configured_timeout = (
        _safe_int(os.environ.get("SCAN_PING_TIMEOUT_MS"), 1000)
        if timeout_ms is None
        else int(timeout_ms)
    )
    batch_size = max(
        1,
        min(
            128,
            _safe_int(os.environ.get("SCAN_CONCURRENCY"), DEFAULT_CONCURRENCY)
            if concurrency is None
            else int(concurrency),
        ),
    )
    ping_path = resolve_ping_command() if ping_command is None else ping_command
    completed = 0
    for start in range(0, len(hosts), batch_size):
        if cancel_event.is_set():
            raise ScanCancelled("scan stopped")
        if pause_event is not None:
            while pause_event.is_set():
                if cancel_event.wait(0.2):
                    raise ScanCancelled("scan stopped")
        batch = hosts[start : start + batch_size]
        try:
            primer(target.local_source, batch)
        except OSError:
            pass
        if ping_path:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(batch),
                thread_name_prefix="lan-ping",
            ) as executor:
                futures = [
                    executor.submit(
                        _ping_host,
                        ping_path,
                        target.interface,
                        address,
                        configured_timeout,
                    )
                    for address in batch
                ]
                for future in concurrent.futures.as_completed(futures):
                    if cancel_event.is_set():
                        for pending in futures:
                            pending.cancel()
                        raise ScanCancelled("scan stopped")
                    try:
                        future.result()
                    except Exception:
                        pass
        completed += len(batch)
        if progress:
            progress(completed)
    time.sleep(0.15)
    return bool(ping_path)


def match_neighbor_records(
    records: Iterable[NeighborRecord],
    suffix: str,
    scan_range: str,
) -> list[dict]:
    normalized = normalize_mac_suffix(suffix)
    if normalized is None:
        raise ValueError("invalid MAC suffix")
    matches: list[dict] = []
    for record in records:
        compact = record.mac.replace("-", "")
        if not compact.endswith(normalized):
            continue
        matches.append(
            {
                "interface": record.interface,
                "scan_range": scan_range,
                "ip": record.ip,
                "mac": record.mac,
                "state": record.state,
            }
        )
    return matches


def match_neighbor_records_multi(
    records: Iterable[NeighborRecord],
    suffixes: Sequence[str] | str,
    scan_range: str,
) -> list[dict]:
    """Return neighbor matches annotated with every requested suffix they hit."""

    normalized_suffixes = normalize_mac_suffixes(suffixes)
    matches: list[dict] = []
    for record in records:
        compact = record.mac.replace("-", "")
        matched = [
            suffix for suffix in normalized_suffixes if compact.endswith(suffix)
        ]
        if not matched:
            continue
        matches.append(
            {
                "interface": record.interface,
                "scan_range": scan_range,
                "ip": record.ip,
                "mac": record.mac,
                "state": record.state,
                "matched_suffixes": matched,
            }
        )
    return matches


def _sort_results(results: Iterable[dict]) -> list[dict]:
    def key(item: dict) -> tuple:
        try:
            ip_value = int(ipaddress.ip_address(item.get("ip", "")))
        except ValueError:
            ip_value = 0
        return (item.get("interface", ""), ip_value, item.get("mac", ""))

    return sorted(results, key=key)


def _merge_device(unique: dict[tuple[str, str, str], dict], item: dict) -> None:
    key = (
        str(item.get("scan_range", "")),
        str(item.get("ip", "")),
        str(item.get("mac", "")),
    )
    existing = unique.get(key)
    if existing is None:
        unique[key] = dict(item)
        return
    suffixes = list(existing.get("matched_suffixes") or [])
    for suffix in item.get("matched_suffixes") or []:
        if suffix not in suffixes:
            suffixes.append(suffix)
    item_priority = DEVICE_STATE_PRIORITY.get(str(item.get("state", "")), 0)
    existing_priority = DEVICE_STATE_PRIORITY.get(str(existing.get("state", "")), 0)
    merged = dict(item) if item_priority > existing_priority else dict(existing)
    if suffixes:
        merged["matched_suffixes"] = sorted(suffixes)
    unique[key] = merged


def _merge_devices(results: Iterable[dict]) -> dict[tuple[str, str, str], dict]:
    unique: dict[tuple[str, str, str], dict] = {}
    for item in results:
        _merge_device(unique, item)
    return unique


def _sweep_groups(targets: Iterable[NetworkTarget]) -> list[list[NetworkTarget]]:
    grouped: dict[str, list[NetworkTarget]] = {}
    for target in targets:
        grouped.setdefault(target.scan_range, []).append(target)
    return list(grouped.values())


def collect_neighbor_devices(
    targets: Iterable[NetworkTarget],
    neighbors: Callable[[str], list[NeighborRecord]] = read_neighbors,
) -> tuple[list[dict], list[str]]:
    """Return every known neighbor that belongs to a scannable routed network."""

    warnings: list[str] = []
    records_by_interface: dict[str, list[NeighborRecord]] = {}
    devices: dict[tuple[str, str, str], dict] = {}

    for target in targets:
        local_mac = normalize_mac(target.local_mac)
        if local_mac:
            _merge_device(
                devices,
                {
                    "interface": target.interface,
                    "scan_range": target.scan_range,
                    "ip": target.local_ip,
                    "mac": local_mac,
                    "state": "LOCAL",
                },
            )
        interface = target.interface
        if interface not in records_by_interface:
            try:
                records_by_interface[interface] = neighbors(interface)
            except (CommandError, OSError) as exc:
                records_by_interface[interface] = []
                warnings.append(f"{interface} 邻居表读取失败：{exc}")

        network = parse_ipv4_network(target.local_ip, target.prefix_length)
        for record in records_by_interface[interface]:
            try:
                address = ipaddress.ip_address(record.ip)
            except ValueError:
                continue
            if not isinstance(address, ipaddress.IPv4Address) or address not in network:
                continue
            _merge_device(
                devices,
                {
                    "interface": record.interface,
                    "scan_range": target.scan_range,
                    "ip": record.ip,
                    "mac": record.mac,
                    "state": record.state,
                },
            )

    return _sort_results(devices.values()), warnings


def probe_network_devices(
    targets: Iterable[NetworkTarget],
    *,
    sweep: Callable[..., bool] = scan_hosts,
    neighbors: Callable[[str], list[NeighborRecord]] = read_neighbors,
) -> tuple[list[dict], list[str]]:
    """Actively probe each routed network, then return every known neighbor."""

    target_list = list(targets)
    warnings: list[str] = []
    cancel_event = threading.Event()
    for group in _sweep_groups(target_list):
        target = group[0]
        try:
            sweep(target, cancel_event)
        except (CommandError, OSError) as exc:
            warnings.append(f"{target.interface} 探测失败：{exc}")

    devices, neighbor_warnings = collect_neighbor_devices(target_list, neighbors)
    return devices, warnings + neighbor_warnings


def match_local_target(target: NetworkTarget, suffix: str) -> list[dict]:
    normalized = normalize_mac_suffix(suffix)
    local_mac = normalize_mac(target.local_mac)
    if normalized is None or local_mac is None:
        return []
    if not local_mac.replace("-", "").endswith(normalized):
        return []
    return [
        {
            "interface": target.interface,
            "scan_range": target.scan_range,
            "ip": target.local_ip,
            "mac": local_mac,
            "state": "LOCAL",
        }
    ]


def match_local_target_multi(
    target: NetworkTarget,
    suffixes: Sequence[str] | str,
) -> list[dict]:
    normalized_suffixes = normalize_mac_suffixes(suffixes)
    local_mac = normalize_mac(target.local_mac)
    if local_mac is None:
        return []
    compact = local_mac.replace("-", "")
    matched = [
        suffix for suffix in normalized_suffixes if compact.endswith(suffix)
    ]
    if not matched:
        return []
    return [
        {
            "interface": target.interface,
            "scan_range": target.scan_range,
            "ip": target.local_ip,
            "mac": local_mac,
            "state": "LOCAL",
            "matched_suffixes": matched,
        }
    ]


PING_LOSS_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)% packet loss")
PING_RTT_PATTERN = re.compile(
    r"rtt min/avg/max/mdev = ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+) ms"
)
PING_HOST_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def expand_custom_range(text: str) -> list[str]:
    """Expand one CIDR or start-end range into bounded IPv4 CIDRs."""

    limit = max_configured_hosts()
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("自定义范围不能为空")
    networks: list[ipaddress.IPv4Network] = []
    if "-" in raw and ":" not in raw:
        start_text, end_text = [part.strip() for part in raw.split("-", 1)]
        try:
            start = ipaddress.IPv4Address(start_text)
            end = ipaddress.IPv4Address(end_text)
        except ValueError as exc:
            raise ValueError(f"自定义范围格式不正确：{raw}") from exc
        if int(end) < int(start):
            raise ValueError("自定义范围的结束地址不能小于开始地址")
        networks = list(ipaddress.summarize_address_range(start, end))
    else:
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError as exc:
            raise ValueError(f"自定义范围格式不正确：{raw}") from exc
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError("仅支持 IPv4 自定义范围")
        networks = [network]
    result: list[str] = []
    for network in networks:
        if network_host_count(network) > limit:
            raise ValueError(f"{network} 包含的主机数超过上限 {limit}")
        result.append(str(network))
    return result


def normalize_custom_ranges(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise ValueError("custom_ranges 必须是数组")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError("custom_ranges 只能包含字符串")
        if not item.strip():
            continue
        for network in expand_custom_range(item):
            if network not in result:
                result.append(network)
    if len(result) > MAX_NETWORK_SELECTION:
        raise ValueError(f"最多选择 {MAX_NETWORK_SELECTION} 个范围")
    return result


def build_custom_targets(
    custom_ranges: Sequence[str],
    discovered: Sequence[NetworkTarget],
) -> list[NetworkTarget]:
    """Turn custom CIDRs into scan targets, borrowing a routed interface."""

    targets: list[NetworkTarget] = []
    for text in custom_ranges:
        network = ipaddress.ip_network(text, strict=False)
        parent: NetworkTarget | None = None
        for candidate in discovered:
            try:
                candidate_network = parse_ipv4_network(
                    candidate.local_ip, candidate.prefix_length
                )
            except CommandError:
                continue
            if network.subnet_of(candidate_network) or candidate_network.subnet_of(network):
                parent = candidate
                break
        targets.append(
            NetworkTarget(
                interface=parent.interface if parent else "",
                alias=parent.alias if parent else "custom",
                local_ip=str(network.network_address),
                prefix_length=network.prefixlen,
                gateway=parent.gateway if parent else "",
                network=str(network.network_address),
                broadcast=str(network.broadcast_address),
                scan_range=str(network),
                host_count=network_host_count(network),
                local_source=parent.local_source if parent else "",
                local_mac=parent.local_mac if parent else "",
            )
        )
    return targets


def merge_custom_targets(
    discovered: Sequence[NetworkTarget],
    custom_ranges: Sequence[str],
) -> list[NetworkTarget]:
    merged = list(discovered)
    seen = {(target.interface, target.scan_range) for target in merged}
    for target in build_custom_targets(custom_ranges, discovered):
        key = (target.interface, target.scan_range)
        if key not in seen:
            merged.append(target)
            seen.add(key)
    return merged


def ping_statistics(
    host: str,
    *,
    count: int = 4,
    timeout_ms: int = 1000,
    ping_command: str | None = None,
) -> dict:
    """Run a real ICMP ping and return latency and packet loss statistics."""

    text = str(host or "").strip()
    if not text or PING_HOST_PATTERN.fullmatch(text) is None:
        raise ValueError("请输入有效的 IPv4 地址或主机名")
    ping_path = resolve_ping_command() if ping_command is None else ping_command
    if not ping_path:
        raise CommandError("系统没有可用的 ping 命令")
    safe_count = max(1, min(20, int(count)))
    wait_seconds = max(1, int(math.ceil(int(timeout_ms) / 1000)))
    command = [
        ping_path,
        "-n",
        "-c",
        str(safe_count),
        "-W",
        str(wait_seconds),
        text,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=safe_count * (wait_seconds + 0.6) + 4,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandError(f"ping 执行失败：{exc}") from exc
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    loss_match = PING_LOSS_PATTERN.search(output)
    rtt_match = PING_RTT_PATTERN.search(output)
    loss = float(loss_match.group(1)) if loss_match else (0.0 if result.returncode == 0 else 100.0)
    received = int(round(safe_count * (100.0 - loss) / 100.0))
    stats = {
        "host": text,
        "transmitted": safe_count,
        "received": max(0, min(safe_count, received)),
        "loss_percent": round(loss, 1),
        "reachable": result.returncode == 0 and loss < 100.0,
        "min_ms": None,
        "avg_ms": None,
        "max_ms": None,
        "mdev_ms": None,
    }
    if rtt_match:
        stats.update(
            {
                "min_ms": float(rtt_match.group(1)),
                "avg_ms": float(rtt_match.group(2)),
                "max_ms": float(rtt_match.group(3)),
                "mdev_ms": float(rtt_match.group(4)),
            }
        )
    return stats


def read_dns_servers(path: str = "/etc/resolv.conf") -> list[str]:
    servers: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver" and parts[1] not in servers:
                    servers.append(parts[1])
    except OSError:
        pass
    return servers


class ScanManager:
    """Run one scan at a time and expose polling-friendly state."""

    def __init__(
        self,
        *,
        discover: Callable[..., tuple[list[NetworkTarget], list[str]]] = discover_networks,
        neighbors: Callable[[str], list[NeighborRecord]] = read_neighbors,
        sweep: Callable[..., bool] = scan_hosts,
        on_finish: Callable[[dict], None] | None = None,
    ) -> None:
        self._discover = discover
        self._neighbors = neighbors
        self._sweep = sweep
        self._on_finish = on_finish
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._requested_network_ids: list[str] | None = None
        self._custom_ranges: list[str] = []
        self._state = self._idle_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "status": "idle",
            "running": False,
            "stopping": False,
            "paused": False,
            "job_id": "",
            "suffix": "",
            "suffixes": [],
            "selected_network_ids": [],
            "custom_ranges": [],
            "custom_only": False,
            "started_at": None,
            "finished_at": None,
            "networks": [],
            "warnings": [],
            "total_hosts": 0,
            "probed_hosts": 0,
            "progress_percent": 0,
            "current_interface": "",
            "current_range": "",
            "results": [],
            "error": "",
        }

    def status(self) -> dict:
        with self._lock:
            snapshot = dict(self._state)
            snapshot["suffixes"] = list(self._state["suffixes"])
            snapshot["selected_network_ids"] = list(
                self._state["selected_network_ids"]
            )
            snapshot["custom_ranges"] = list(self._state.get("custom_ranges") or [])
            snapshot["custom_only"] = bool(self._state.get("custom_only"))
            snapshot["paused"] = bool(self._state.get("paused"))
            snapshot["networks"] = [dict(item) for item in self._state["networks"]]
            snapshot["warnings"] = list(self._state["warnings"])
            snapshot["results"] = [dict(item) for item in self._state["results"]]
            return snapshot

    def start(
        self,
        suffixes: Sequence[str] | str,
        network_ids: Sequence[str] | None = None,
        custom_ranges: Sequence[str] | None = None,
        custom_only: bool = False,
    ) -> bool:
        normalized = normalize_mac_suffixes(suffixes)
        selected_network_ids = normalize_network_ids(network_ids)
        normalized_ranges = normalize_custom_ranges(custom_ranges)
        with self._lock:
            if self._state["running"]:
                return False
            self._requested_network_ids = (
                list(selected_network_ids)
                if selected_network_ids is not None
                else None
            )
            self._custom_ranges = list(normalized_ranges)
            self._custom_only = bool(custom_only and normalized_ranges)
            self._cancel = threading.Event()
            self._pause.clear()
            self._state = self._idle_state()
            self._state.update(
                {
                    "status": "discovering",
                    "running": True,
                    "job_id": uuid.uuid4().hex,
                    "suffix": normalized[0],
                    "suffixes": normalized,
                    "selected_network_ids": selected_network_ids or [],
                    "custom_ranges": normalized_ranges,
                    "custom_only": self._custom_only,
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(
                    self._state["job_id"],
                    normalized,
                    self._cancel,
                    selected_network_ids,
                    normalized_ranges,
                    self._custom_only,
                ),
                name="lan-mac-scan",
                daemon=True,
            )
            self._thread.start()
        return True

    def matches_request(
        self,
        suffixes: Sequence[str] | str,
        network_ids: Sequence[str] | None = None,
        custom_ranges: Sequence[str] | None = None,
        custom_only: bool = False,
    ) -> bool:
        normalized = normalize_mac_suffixes(suffixes)
        requested = normalize_network_ids(network_ids)
        requested_ranges = normalize_custom_ranges(custom_ranges)
        with self._lock:
            active_suffixes = self._state["suffixes"] or [self._state["suffix"]]
            if set(active_suffixes) != set(normalized):
                return False
            if set(self._custom_ranges) != set(requested_ranges):
                return False
            if bool(custom_only and requested_ranges) != bool(self._custom_only):
                return False
            active = self._requested_network_ids
            if active is None or requested is None:
                return active is None and requested is None
            return set(active) == set(requested)

    def stop(self) -> bool:
        with self._lock:
            if not self._state["running"]:
                return False
            self._state["stopping"] = True
            self._state["paused"] = False
            self._pause.clear()
            self._cancel.set()
            return True

    def pause(self) -> bool:
        with self._lock:
            if not self._state["running"] or self._state["stopping"]:
                return False
            self._pause.set()
            self._state["paused"] = True
            self._state["status"] = "paused"
            return True

    def resume(self) -> bool:
        with self._lock:
            if not self._state["running"] or not self._state["paused"]:
                return False
            self._pause.clear()
            self._state["paused"] = False
            self._state["status"] = "scanning"
            return True

    def wait(self, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _update(self, **values) -> None:
        with self._lock:
            self._state.update(values)

    def _append_results(self, values: Iterable[dict]) -> None:
        with self._lock:
            combined = list(self._state["results"]) + list(values)
            unique = _merge_devices(combined)
            self._state["results"] = _sort_results(unique.values())

    def _run(
        self,
        job_id: str,
        suffixes: list[str],
        cancel_event: threading.Event,
        selected_network_ids: list[str] | None,
        custom_ranges: list[str] | None = None,
        custom_only: bool = False,
    ) -> None:
        try:
            targets, warnings = self._discover()
            if custom_only and custom_ranges:
                targets = build_custom_targets(custom_ranges, targets)
                missing: list[str] = []
            else:
                targets, missing = select_network_targets(targets, selected_network_ids)
                targets = merge_custom_targets(targets, custom_ranges or [])
            if missing:
                warnings = warnings + ["所选网段当前不可用：" + "、".join(missing)]
            if cancel_event.is_set():
                raise ScanCancelled("scan stopped")
            if not targets:
                message = (
                    "所选网段当前不可用，请刷新网段后重试"
                    if selected_network_ids is not None
                    else (warnings[0] if warnings else "no scannable physical networks")
                )
                self._update(
                    status="error",
                    running=False,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    warnings=warnings,
                    error=message,
                )
                return

            sweep_groups = _sweep_groups(targets)
            total = sum(group[0].host_count for group in sweep_groups)
            self._update(
                status="scanning",
                networks=[network_target_payload(target) for target in targets],
                selected_network_ids=[
                    network_target_key(target) for target in targets
                ],
                warnings=warnings,
                total_hosts=total,
            )
            probed_before = 0
            for group in sweep_groups:
                if cancel_event.is_set():
                    raise ScanCancelled("scan stopped")
                target = group[0]
                self._update(
                    current_interface=target.interface,
                    current_range=target.scan_range,
                )

                def on_progress(completed: int, offset: int = probed_before) -> None:
                    done = min(total, offset + completed)
                    percent = 0 if total <= 0 else int(done * 100 / total)
                    self._update(
                        probed_hosts=done,
                        progress_percent=percent,
                    )

                sweep_parameters = inspect.signature(self._sweep).parameters
                if "pause_event" in sweep_parameters:
                    self._sweep(
                        target,
                        cancel_event,
                        on_progress,
                        pause_event=self._pause,
                    )
                else:
                    self._sweep(target, cancel_event, on_progress)
                for member in group:
                    self._append_results(match_local_target_multi(member, suffixes))
                    records = self._neighbors(member.interface)
                    try:
                        member_network = parse_ipv4_network(
                            member.local_ip, member.prefix_length
                        )
                        records = [
                            record
                            for record in records
                            if ipaddress.ip_address(record.ip) in member_network
                        ]
                    except (CommandError, ValueError):
                        pass
                    self._append_results(
                        match_neighbor_records_multi(
                            records,
                            suffixes,
                            member.scan_range,
                        )
                    )
                probed_before += target.host_count

            if cancel_event.is_set():
                raise ScanCancelled("scan stopped")
            self._update(
                status="completed",
                running=False,
                stopping=False,
                probed_hosts=total,
                progress_percent=100,
                current_interface="",
                current_range="",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        except ScanCancelled:
            self._update(
                status="stopped",
                running=False,
                stopping=False,
                current_interface="",
                current_range="",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        except Exception as exc:
            self._update(
                status="error",
                running=False,
                stopping=False,
                current_interface="",
                current_range="",
                error=str(exc),
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        finally:
            with self._lock:
                if self._state["job_id"] == job_id:
                    self._state["running"] = False
                    self._state["paused"] = False
            callback = self._on_finish
            if callback is not None:
                try:
                    callback(self.status())
                except Exception:
                    pass


def max_configured_hosts() -> int:
    return max(1, _safe_int(os.environ.get("SCAN_MAX_HOSTS"), DEFAULT_MAX_HOSTS))
