"""HTTP-over-Unix-socket server for the TOS Network Locator WebUI."""

from __future__ import annotations

import inspect
import json
import os
import signal
import socketserver
import sys
import tempfile
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .store import Store
from .core import (
    APP_ID,
    ScanManager,
    collect_neighbor_devices,
    discover_networks,
    max_configured_hosts,
    network_target_payload,
    normalize_mac_suffixes,
    normalize_network_ids,
    probe_network_devices,
    select_network_targets,
)

SOCKET_DIR = "/var/api"
SOCKET_PATH = os.path.join(SOCKET_DIR, f"{APP_ID}.sock")
MAX_BODY_BYTES = 64 * 1024


def log(level: str, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [{APP_ID}] {message}", flush=True)


def route_parts(path: str) -> list[str]:
    raw = str(path or "").split("?", 1)[0].split("#", 1)[0]
    parts = [unquote(part) for part in raw.split("/") if part]
    while APP_ID in parts:
        index = parts.index(APP_ID)
        del parts[: index + 1]
    if parts and parts[0] == "api":
        parts = parts[1:]
    return parts


def health_payload() -> dict:
    return {
        "ok": True,
        "status": "ok",
        "app": APP_ID,
        "version": __version__,
        "python": sys.version.split()[0],
        "max_hosts": max_configured_hosts(),
    }


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def parse_network_selection(body: Mapping[str, Any]) -> list[str] | None:
    try:
        return normalize_network_ids(body.get("network_ids"))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc


def _supports_argument(func: Any, name: str) -> bool:
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def start_scan_result(
    manager: Any,
    suffixes: list[str],
    network_ids: list[str] | None = None,
    custom_ranges: list[str] | None = None,
    custom_only: bool = False,
) -> tuple[int, dict]:
    if custom_ranges and _supports_argument(manager.start, "custom_only"):
        started = manager.start(suffixes, network_ids, custom_ranges, custom_only)
    elif custom_ranges and _supports_argument(manager.start, "custom_ranges"):
        started = manager.start(suffixes, network_ids, custom_ranges)
    else:
        started = manager.start(suffixes, network_ids)
    actual = manager.status()
    if not started:
        matches_request = getattr(manager, "matches_request", None)
        same_request = actual.get("suffix") == suffixes[0]
        if callable(matches_request):
            if custom_ranges and _supports_argument(matches_request, "custom_only"):
                same_request = bool(
                    matches_request(suffixes, network_ids, custom_ranges, custom_only)
                )
            elif custom_ranges and _supports_argument(matches_request, "custom_ranges"):
                same_request = bool(matches_request(suffixes, network_ids, custom_ranges))
            else:
                same_request = bool(matches_request(suffixes, network_ids))
        if not same_request:
            raise ApiError(
                409,
                "another scan with different MAC suffixes, network selection or "
                "custom range is already running",
            )
    return (
        202 if started else 200,
        {
            "ok": True,
            "app": APP_ID,
            "started": started,
            "running": bool(actual.get("running")),
            "status": actual.get("status"),
            "job_id": actual.get("job_id", ""),
            "suffix": actual.get("suffix", ""),
            "suffixes": actual.get("suffixes", []),
            "selected_network_ids": actual.get("selected_network_ids", []),
            "custom_ranges": actual.get("custom_ranges", custom_ranges or []),
            "custom_only": bool(actual.get("custom_only", custom_only)),
            "paused": bool(actual.get("paused")),
            "message": "scan started" if started else "scan already running",
        },
    )


class NetworkLocatorHandler(BaseHTTPRequestHandler):
    server_version = f"{APP_ID}/{__version__}"
    timeout = 30

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _origin(self) -> str:
        return self.headers.get("Origin") or "null"

    def _manager(self) -> ScanManager:
        manager = getattr(self.server, "scan_manager", None)
        if manager is None:
            raise ApiError(503, "scan manager is unavailable")
        return manager

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
        *,
        head_only: bool = False,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, HEAD, POST, PATCH, PUT, DELETE, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Csrf-Token, Cookie",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ApiError(413, "request body is too large")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise ApiError(400, "JSON body must be an object")
        return value

    def _dispatch(self, method: str) -> None:
        head_only = method == "HEAD"
        try:
            parts = route_parts(self.path)
            if not parts or parts == ["info"]:
                self._send_json(
                    200,
                    {
                        **health_payload(),
                        "capabilities": [
                            "health",
                            "networks",
                            "devices",
                            "devices/scan",
                            "scan/start",
                            "scan/status",
                            "scan/stop",
                            "scan/pause",
                            "scan/resume",
                            "v2/summary",
                            "v2/devices",
                            "v2/devices/scan",
                            "v2/mac/lookup",
                            "v2/analysis",
                            "v2/scans",
                            "v2/settings",
                        ],
                    },
                    head_only=head_only,
                )
                return
            if parts == ["health"]:
                if method not in {"GET", "HEAD"}:
                    raise ApiError(405, "method not allowed")
                self._send_json(200, health_payload(), head_only=head_only)
                return
            if parts == ["networks"]:
                if method not in {"GET", "HEAD"}:
                    raise ApiError(405, "method not allowed")
                targets, warnings = discover_networks()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "version": __version__,
                        "max_hosts": max_configured_hosts(),
                        "networks": [network_target_payload(target) for target in targets],
                        "warnings": warnings,
                    },
                    head_only=head_only,
                )
                return
            if parts == ["devices"]:
                if method not in {"GET", "HEAD"}:
                    raise ApiError(405, "method not allowed")
                targets, warnings = discover_networks()
                devices, neighbor_warnings = collect_neighbor_devices(targets)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "version": __version__,
                        "devices": devices,
                        "warnings": warnings + neighbor_warnings,
                    },
                    head_only=head_only,
                )
                return
            if parts == ["devices", "scan"]:
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                body = self._read_json_body()
                network_ids = parse_network_selection(body)
                inventory_lock = getattr(self.server, "device_scan_lock", None)
                if inventory_lock is None:
                    inventory_lock = threading.Lock()
                if not inventory_lock.acquire(blocking=False):
                    raise ApiError(409, "device inventory scan is already running")
                try:
                    if self._manager().status().get("running"):
                        raise ApiError(409, "another scan is already running")
                    targets, warnings = discover_networks()
                    targets, missing = select_network_targets(targets, network_ids)
                    if missing:
                        warnings = warnings + [
                            "所选网段当前不可用：" + "、".join(missing)
                        ]
                    if network_ids is not None and not targets:
                        raise ApiError(
                            409,
                            "所选网段当前不可用，请刷新网段后重试",
                        )
                    devices, probe_warnings = probe_network_devices(targets)
                finally:
                    inventory_lock.release()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "version": __version__,
                        "devices": devices,
                        "warnings": warnings + probe_warnings,
                    },
                )
                return
            if parts == ["scan", "status"]:
                if method not in {"GET", "HEAD"}:
                    raise ApiError(405, "method not allowed")
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "version": __version__,
                        **self._manager().status(),
                    },
                    head_only=head_only,
                )
                return
            if parts == ["scan", "start"]:
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                body = self._read_json_body()
                raw_suffixes = body.get("suffixes")
                if raw_suffixes is None:
                    legacy_suffix = body.get("suffix")
                    raw_suffixes = [legacy_suffix] if legacy_suffix else []
                try:
                    suffixes = normalize_mac_suffixes(raw_suffixes)
                except ValueError as exc:
                    raise ApiError(400, str(exc)) from exc
                custom_only_flag = bool(body.get("custom_only"))
                if custom_only_flag and body.get("network_ids") == []:
                    network_ids = None
                else:
                    network_ids = parse_network_selection(body)
                custom_ranges = body.get("custom_ranges")
                if custom_ranges is not None and not isinstance(
                    custom_ranges, (list, tuple)
                ):
                    raise ApiError(400, "custom_ranges 必须是数组")
                inventory_lock = getattr(self.server, "device_scan_lock", None)
                if inventory_lock is None:
                    inventory_lock = threading.Lock()
                if not inventory_lock.acquire(blocking=False):
                    raise ApiError(409, "device inventory scan is already running")
                try:
                    status, payload = start_scan_result(
                        self._manager(),
                        suffixes,
                        network_ids,
                        list(custom_ranges or []),
                        custom_only_flag,
                    )
                except ValueError as exc:
                    raise ApiError(400, str(exc)) from exc
                finally:
                    inventory_lock.release()
                self._send_json(status, payload)
                return
            if parts in (["scan", "pause"], ["scan", "resume"]):
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                self._read_json_body()
                manager = self._manager()
                if parts[1] == "pause":
                    changed = manager.pause()
                    message = "paused" if changed else "scan is not running"
                else:
                    changed = manager.resume()
                    message = "resumed" if changed else "scan is not paused"
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "changed": changed,
                        "paused": bool(manager.status().get("paused")),
                        "status": manager.status().get("status"),
                        "message": message,
                    },
                )
                return
            if parts == ["scan", "stop"]:
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                self._read_json_body()
                stopping = self._manager().stop()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "app": APP_ID,
                        "stopping": stopping,
                        "message": "stopping" if stopping else "scan is not running",
                    },
                )
                return
            from .v2_api import handle_v2
            if handle_v2(self, method, parts):
                return
            raise ApiError(404, "not found")
        except ApiError as exc:
            self._send_json(
                exc.status,
                {"ok": False, "app": APP_ID, "error": str(exc)},
                head_only=head_only,
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            log("ERROR", f"Unhandled request failure for {self.path}: {exc}")
            self._send_json(
                500,
                {"ok": False, "app": APP_ID, "error": "internal server error"},
                head_only=head_only,
            )


if hasattr(socketserver, "UnixStreamServer"):
    class ThreadingUnixHTTPServer(
        socketserver.ThreadingMixIn,
        socketserver.UnixStreamServer,
    ):
        daemon_threads = True
        block_on_close = False
        allow_reuse_address = True
        request_queue_size = 128
else:
    # Windows cannot bind an AF_UNIX HTTP server, but importing the module must
    # still work so pure route tests and local tooling remain cross-platform.
    class ThreadingUnixHTTPServer(
        socketserver.ThreadingMixIn,
        socketserver.TCPServer,
    ):
        daemon_threads = True
        block_on_close = False
        allow_reuse_address = True
        request_queue_size = 128


def prepare_socket(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.lexists(path):
        try:
            os.unlink(path)
        except OSError as exc:
            raise RuntimeError(
                f"{path} exists but cannot be removed: {exc}. "
                "The shared /var/api directory is sticky; a foreign-owned "
                "socket must be removed by its owner or root."
            ) from exc


def serve(socket_path: str = SOCKET_PATH) -> int:
    prepare_socket(socket_path)
    try:
        store = Store()
    except Exception as exc:
        log("ERROR", f"persistent store unavailable, using temporary storage: {exc}")
        store = Store(os.path.join(tempfile.gettempdir(), f"{APP_ID}.db"))
    try:
        # Apply persisted timeout/concurrency before the first scan can start.
        store.get_settings()
    except Exception as exc:
        log("WARNING", f"failed to apply persisted settings: {exc}")

    def record_scan(snapshot: dict) -> None:
        try:
            store.record_scan_task(
                snapshot,
                kind=str(snapshot.get("kind") or "mac"),
                custom_ranges=snapshot.get("custom_ranges") or [],
            )
        except Exception as record_error:
            log("ERROR", f"failed to record scan history: {record_error}")

    manager = ScanManager(on_finish=record_scan)
    server = ThreadingUnixHTTPServer(socket_path, NetworkLocatorHandler)
    server.scan_manager = manager
    server.store = store
    server.device_scan_lock = threading.Lock()
    from .v2_api import AutoScanScheduler

    scheduler = AutoScanScheduler(
        store,
        manager,
        server.device_scan_lock,
        logger=lambda message: log("INFO", message),
    )
    server.auto_scan_scheduler = scheduler
    os.chmod(socket_path, 0o660)
    stop_once = threading.Event()

    def request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        if stop_once.is_set():
            return
        stop_once.set()
        threading.Thread(target=server.shutdown, name="http-shutdown", daemon=True).start()

    for signal_name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), request_stop)

    log(
        "INFO",
        f"version={__version__} socket={socket_path} python={sys.version.split()[0]}",
    )
    scheduler.start()
    try:
        server.serve_forever(poll_interval=0.4)
    finally:
        scheduler.stop()
        manager.stop()
        manager.wait(2.0)
        server.server_close()
        try:
            if os.path.lexists(socket_path):
                os.unlink(socket_path)
        except OSError:
            pass
        log("INFO", "service stopped")
    return 0


def main() -> int:
    configured_socket = str(os.environ.get("APP_SOCKET_PATH") or SOCKET_PATH)
    try:
        return serve(configured_socket)
    except Exception as exc:
        log("ERROR", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
