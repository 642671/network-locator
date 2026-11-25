"""Network Locator V2 JSON API.

The legacy endpoints in :mod:`network_locator.server` are intentionally left
untouched. This module adds the V2 routes used by the new pages. It is imported
lazily from the request dispatcher so the package keeps its original import
graph and test surface.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from .core import (
    CommandError,
    ScanManager,
    discover_networks,
    merge_custom_targets,
    network_target_payload,
    normalize_custom_ranges,
    normalize_network_ids,
    ping_statistics,
    probe_network_devices,
    read_dns_servers,
    select_network_targets,
)
from .oui import classify_query, lookup_vendor_prefixes, vendor_count
from .store import SCHEMA_VERSION, Store

MAX_BATCH_LOOKUPS = 100


class V2Error(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _query(handler: Any) -> dict[str, list[str]]:
    return parse_qs(urlsplit(handler.path).query, keep_blank_values=True)


def _one(values: Mapping[str, list[str]], key: str, default: str = "") -> str:
    items = values.get(key)
    return items[-1] if items else default


def _store(handler: Any) -> Store:
    store = getattr(handler.server, "store", None)
    if store is None:
        raise V2Error(503, "数据存储尚未就绪")
    return store


def _manager(handler: Any) -> ScanManager:
    manager = getattr(handler.server, "scan_manager", None)
    if manager is None:
        raise V2Error(503, "扫描服务尚未就绪")
    return manager


def _bool_param(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _network_payloads(targets: Any) -> list[dict[str, Any]]:
    return [network_target_payload(target) for target in targets]


def _analysis(store: Store) -> dict[str, Any]:
    targets, warnings = discover_networks()
    devices = store.list_devices(limit=5000)["devices"]
    counts: dict[str, dict[str, int]] = {}
    vendors: dict[str, int] = {}
    for device in devices:
        key = str(device.get("network_id") or device.get("interface") or "未知")
        bucket = counts.setdefault(
            key, {"total": 0, "online": 0, "offline": 0, "unknown": 0}
        )
        bucket["total"] += 1
        status = str(device.get("status") or "unknown")
        bucket[status] = bucket.get(status, 0) + 1
        vendor = str(device.get("vendor") or "未知厂商")
        vendors[vendor] = vendors.get(vendor, 0) + 1
    interfaces = []
    for target in targets:
        payload = network_target_payload(target)
        bucket = counts.get(payload["network_id"], {})
        payload["device_count"] = int(bucket.get("total", 0))
        payload["online_count"] = int(bucket.get("online", 0))
        interfaces.append(payload)
    return {
        "interfaces": interfaces,
        "warnings": warnings,
        "dns_servers": read_dns_servers(),
        "networks": [
            {
                "network_id": key,
                "total": value["total"],
                "online": value["online"],
                "offline": value["offline"],
                "unknown": value["unknown"],
            }
            for key, value in sorted(counts.items())
        ],
        "vendors": [
            {"vendor": vendor, "count": count}
            for vendor, count in sorted(vendors.items(), key=lambda item: -item[1])[:12]
        ],
    }


def _summary(handler: Any) -> dict[str, Any]:
    store = _store(handler)
    targets, warnings = discover_networks()
    devices = store.list_devices(limit=5000)["devices"]
    by_network: dict[str, int] = {}
    for device in devices:
        key = str(device.get("network_id") or "")
        if key:
            by_network[key] = by_network.get(key, 0) + 1
    networks = []
    for target in targets:
        payload = network_target_payload(target)
        payload["device_count"] = by_network.get(payload["network_id"], 0)
        networks.append(payload)
    settings = store.get_settings()
    return {
        "ok": True,
        "app": "network-locator",
        "stats": store.stats(),
        "recent": store.recent_devices(6),
        "networks": networks,
        "warnings": warnings,
        "settings": settings,
        "storage": store.storage_info(),
        "vendor_count": vendor_count(),
        "schema_version": SCHEMA_VERSION,
    }


def _list_devices(handler: Any, method: str) -> None:
    store = _store(handler)
    if method == "GET":
        values = _query(handler)
        result = store.list_devices(
            query=_one(values, "query"),
            status=_one(values, "status"),
            favorite=_bool_param(_one(values, "favorite")),
            sort=_one(values, "sort", "last_seen"),
            direction=_one(values, "direction", "desc"),
            limit=int(_one(values, "limit", "500") or 500),
            offset=int(_one(values, "offset", "0") or 0),
        )
        handler._send_json(
            200,
            {
                "ok": True,
                **result,
                "stats": store.stats(),
                "settings": store.get_settings(),
            },
            head_only=handler.command == "HEAD",
        )
        return
    raise V2Error(405, "method not allowed")


def _device_detail(handler: Any, method: str, device_id: str) -> None:
    store = _store(handler)
    if method in {"GET", "HEAD"}:
        device = store.get_device(device_id)
        if device is None:
            raise V2Error(404, "设备不存在")
        handler._send_json(
            200,
            {"ok": True, "device": device},
            head_only=method == "HEAD",
        )
        return
    if method == "PATCH":
        body = handler._read_json_body()
        allowed = {
            key: body[key]
            for key in ("display_name", "note", "favorite")
            if key in body
        }
        try:
            device = store.update_device(device_id, allowed)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        if device is None:
            raise V2Error(404, "设备不存在")
        handler._send_json(200, {"ok": True, "device": device})
        return
    raise V2Error(405, "method not allowed")


def _inventory_scan(handler: Any) -> None:
    store = _store(handler)
    manager = _manager(handler)
    body = handler._read_json_body()
    try:
        network_ids = normalize_network_ids(body.get("network_ids"))
        custom_ranges = normalize_custom_ranges(body.get("custom_ranges"))
    except ValueError as exc:
        raise V2Error(400, str(exc)) from exc
    lock = getattr(handler.server, "device_scan_lock", None)
    if lock is None:
        raise V2Error(503, "扫描锁不可用")
    if not lock.acquire(blocking=False):
        raise V2Error(409, "设备扫描正在进行中")
    try:
        if manager.status().get("running"):
            raise V2Error(409, "另一个扫描任务正在进行中")
        targets, warnings = discover_networks()
        targets, missing = select_network_targets(targets, network_ids)
        targets = merge_custom_targets(targets, custom_ranges)
        if missing:
            warnings = warnings + ["所选网段当前不可用：" + "、".join(missing)]
        if not targets:
            raise V2Error(409, "当前没有可扫描的网段")
        started_at = _now()
        devices, probe_warnings = probe_network_devices(targets)
        finished_at = _now()
        total = sum(target.host_count for target in targets)
        snapshot = {
            "job_id": "inv_" + uuid.uuid4().hex,
            "status": "completed",
            "started_at": started_at,
            "finished_at": finished_at,
            "networks": _network_payloads(targets),
            "selected_network_ids": [
                payload["network_id"] for payload in _network_payloads(targets)
            ],
            "suffixes": [],
            "custom_ranges": custom_ranges,
            "total_hosts": total,
            "probed_hosts": total,
            "results": devices,
            "warnings": warnings + probe_warnings,
            "error": "",
        }
        task = store.record_scan_task(
            snapshot, kind="inventory", custom_ranges=custom_ranges
        )
        result = store.list_devices(limit=5000)
        handler._send_json(
            200,
            {
                "ok": True,
                "devices": result["devices"],
                "total": result["total"],
                "task": task,
                "warnings": warnings + probe_warnings,
                "stats": store.stats(),
            },
        )
    finally:
        lock.release()


def _live_mac_matches(handler: Any, query: str, mode: str) -> list[dict[str, Any]]:
    try:
        status = _manager(handler).status()
    except Exception:
        return []
    compact = "".join(
        character for character in str(query or "").upper()
        if character in "0123456789ABCDEF"
    )
    if not compact:
        return []
    matches: list[dict[str, Any]] = []
    for item in status.get("results") or []:
        mac = str(item.get("mac") or "").replace("-", "")
        if not mac:
            continue
        if mode == "full" and mac != compact:
            continue
        if mode == "prefix" and not mac.startswith(compact):
            continue
        if mode == "suffix" and not mac.endswith(compact):
            continue
        if mode == "any" and compact not in mac:
            continue
        matches.append(
            {
                "device_id": "",
                "name": "扫描结果 " + mac[-4:],
                "display_name": "",
                "favorite": False,
                "vendor": "",
                "vendor_known": False,
                "mac": str(item.get("mac") or ""),
                "ip": str(item.get("ip") or ""),
                "interface": str(item.get("interface") or ""),
                "network_id": str(item.get("scan_range") or ""),
                "status": "online"
                if str(item.get("state") or "").upper() in {"LOCAL", "REACHABLE"}
                else "unknown",
                "status_state": str(item.get("state") or ""),
                "status_reason": "来自当前扫描结果，尚未写入设备档案",
                "last_seen": status.get("finished_at") or status.get("started_at") or "",
                "random_mac": False,
                "matched_macs": [str(item.get("mac") or "")],
                "live": True,
            }
        )
    return matches


def _mac_lookup(handler: Any, method: str) -> None:
    store = _store(handler)
    if method == "GET":
        values = _query(handler)
        query = _one(values, "q") or _one(values, "query")
        mode = _one(values, "mode", "auto")
        try:
            result = store.lookup_mac(query, mode)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        live = _live_mac_matches(handler, query, result["mode"])
        if live:
            known = {item["mac"].replace("-", "") for item in result["matches"]}
            result["matches"].extend(
                item for item in live if item["mac"].replace("-", "") not in known
            )
            result["count"] = len(result["matches"])
        kind, compact = classify_query(query)
        result["input_kind"] = kind
        result["vendor_prefixes"] = lookup_vendor_prefixes(compact) if compact else []
        handler._send_json(200, {"ok": True, **result}, head_only=handler.command == "HEAD")
        return
    if method == "POST":
        body = handler._read_json_body()
        raw_queries = body.get("queries")
        if raw_queries is None:
            raw_queries = [body.get("query") or ""]
        if not isinstance(raw_queries, list) or not raw_queries:
            raise V2Error(400, "请输入至少一个 MAC 查询")
        if len(raw_queries) > MAX_BATCH_LOOKUPS:
            raise V2Error(400, f"一次最多查询 {MAX_BATCH_LOOKUPS} 个 MAC")
        results = []
        for query in raw_queries:
            text = str(query or "").strip()
            if not text:
                continue
            try:
                result = store.lookup_mac(text, "auto")
            except ValueError as exc:
                results.append({"query": text, "error": str(exc), "matches": [], "count": 0})
                continue
            live = _live_mac_matches(handler, text, result["mode"])
            if live:
                known = {item["mac"].replace("-", "") for item in result["matches"]}
                result["matches"].extend(
                    item for item in live if item["mac"].replace("-", "") not in known
                )
                result["count"] = len(result["matches"])
            kind, compact = classify_query(text)
            result["input_kind"] = kind
            result["vendor_prefixes"] = lookup_vendor_prefixes(compact) if compact else []
            results.append(result)
        handler._send_json(200, {"ok": True, "results": results})
        return
    raise V2Error(405, "method not allowed")


def _analysis_route(handler: Any, method: str) -> None:
    store = _store(handler)
    if method in {"GET", "HEAD"}:
        handler._send_json(
            200,
            {
                "ok": True,
                **_analysis(store),
                "stats": store.stats(),
                "settings": store.get_settings(),
                "storage": store.storage_info(),
            },
            head_only=method == "HEAD",
        )
        return
    if method == "POST":
        body = handler._read_json_body()
        count = int(body.get("count") or 4)
        host = str(body.get("host") or "").strip()
        interface = str(body.get("interface") or "").strip()
        if not host or body.get("gateway"):
            targets, warnings = discover_networks()
            target = None
            for candidate in targets:
                if interface and candidate.interface != interface:
                    continue
                if candidate.gateway:
                    target = candidate
                    break
            if target is None:
                raise V2Error(409, "没有可用的默认网关")
            host = target.gateway
        try:
            stats = ping_statistics(host, count=count)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        except CommandError as exc:
            raise V2Error(503, str(exc)) from exc
        handler._send_json(200, {"ok": True, "measured_at": _now(), **stats})
        return
    raise V2Error(405, "method not allowed")


def _scans_route(handler: Any, method: str, parts: list[str]) -> None:
    store = _store(handler)
    if len(parts) == 2 and method in {"GET", "HEAD"}:
        values = _query(handler)
        result = store.list_tasks(
            limit=int(_one(values, "limit", "50") or 50),
            offset=int(_one(values, "offset", "0") or 0),
        )
        handler._send_json(200, {"ok": True, **result}, head_only=method == "HEAD")
        return
    if len(parts) == 3 and parts[2] == "purge" and method == "POST":
        body = handler._read_json_body()
        days = body.get("older_than_days")
        removed = store.purge_history(int(days) if days is not None else None)
        handler._send_json(200, {"ok": True, "removed": removed})
        return
    if len(parts) == 3 and method in {"GET", "HEAD"}:
        task = store.get_task(parts[2])
        if task is None:
            raise V2Error(404, "扫描任务不存在")
        handler._send_json(200, {"ok": True, "task": task}, head_only=method == "HEAD")
        return
    raise V2Error(404, "not found")


def _settings_route(handler: Any, method: str) -> None:
    store = _store(handler)
    if method in {"GET", "HEAD"}:
        handler._send_json(
            200,
            {
                "ok": True,
                "settings": store.get_settings(),
                "storage": store.storage_info(),
                "vendor_count": vendor_count(),
                "schema_version": SCHEMA_VERSION,
                "capabilities": [
                    "store/sqlite",
                    "devices",
                    "scan-history",
                    "mac-lookup",
                    "network-analysis",
                    "custom-ranges",
                    "pause-resume",
                ],
            },
            head_only=method == "HEAD",
        )
        return
    if method in {"PATCH", "POST"}:
        body = handler._read_json_body()
        try:
            settings = store.update_settings(body)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        handler._send_json(200, {"ok": True, "settings": settings})
        return
    raise V2Error(405, "method not allowed")


def handle_v2(handler: Any, method: str, parts: list[str]) -> bool:
    """Handle a V2 request. Return False when the path is not a V2 route."""

    if not parts or parts[0] != "v2":
        return False
    try:
        if parts == ["v2", "summary"]:
            if method not in {"GET", "HEAD"}:
                raise V2Error(405, "method not allowed")
            payload = _summary(handler)
            handler._send_json(200, payload, head_only=method == "HEAD")
            return True
        if parts == ["v2", "devices"]:
            _list_devices(handler, method)
            return True
        if parts == ["v2", "devices", "scan"] and method == "POST":
            _inventory_scan(handler)
            return True
        if len(parts) == 3 and parts[:2] == ["v2", "devices"]:
            _device_detail(handler, method, parts[2])
            return True
        if parts in (["v2", "mac", "lookup"], ["v2", "mac"]):
            _mac_lookup(handler, method)
            return True
        if parts in (["v2", "analysis"], ["v2", "analysis", "ping"]):
            _analysis_route(handler, method)
            return True
        if parts[:2] == ["v2", "scans"]:
            _scans_route(handler, method, parts)
            return True
        if parts == ["v2", "settings"]:
            _settings_route(handler, method)
            return True
        raise V2Error(404, "not found")
    except V2Error as exc:
        handler._send_json(
            exc.status,
            {"ok": False, "app": "network-locator", "error": str(exc)},
            head_only=method == "HEAD",
        )
        return True
    except (BrokenPipeError, ConnectionResetError):
        return True
    except Exception as exc:  # pragma: no cover - defensive boundary
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        handler._send_json(
            500,
            {"ok": False, "app": "network-locator", "error": "internal server error"},
            head_only=method == "HEAD",
        )
        return True