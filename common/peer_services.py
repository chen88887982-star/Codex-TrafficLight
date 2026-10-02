"""Bounded background polling of explicitly configured status services.

Tokens are persisted only in the private runtime configuration. Requests served
to clients copy already fetched snapshots and never wait for a remote device.
"""

from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024


class PeerFetchError(Exception):
    """A public error label without request headers, credentials, or URLs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise PeerFetchError("服务地址发生重定向，请填写最终地址")


def validate_service_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("服务地址长度无效")
    value = value.strip()
    if any(ord(character) <= 32 for character in value):
        raise ValueError("服务地址包含空白或控制字符")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("服务地址格式无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("请填写完整的 http 或 https 服务地址")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("服务地址不能包含账号或令牌")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("请只填写服务根地址，不能包含路径、查询参数或片段")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("服务端口无效")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), "", "", ""))


def _fetch_peer_snapshot_in_worker(url: str, token: str = "", *, timeout: float = 3.0) -> dict[str, object]:
    """Read one peer response inside the independently terminable worker."""
    request = Request(f"{url}/api/snapshot", headers={"Accept": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # A configured service cannot forward a private token to another origin.
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            size = 0
            deadline = time.monotonic() + timeout
            while True:
                if time.monotonic() > deadline:
                    raise PeerFetchError("服务响应超时")
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PeerFetchError("服务响应超过大小限制")
            data = b"".join(chunks)
        if len(data) > MAX_RESPONSE_BYTES:
            raise PeerFetchError("服务响应超过大小限制")
        snapshot = json.loads(data.decode("utf-8-sig"))
        if not isinstance(snapshot, dict) or not all(
            isinstance(snapshot.get(key), dict) for key in ("status", "usage", "task", "health")
        ):
            raise PeerFetchError("服务响应格式不兼容，请升级对端状态服务")
        # The public contract is a single device snapshot, never a recursively
        # aggregated list of peers or a response containing credential fields.
        result = {key: snapshot[key] for key in ("status", "usage", "task", "health")}
        if isinstance(snapshot.get("usage_refresh"), dict):
            result["usage_refresh"] = snapshot["usage_refresh"]
        return result
    except HTTPError as exc:
        exc.close()
        if exc.code in {401, 403}:
            raise PeerFetchError("访问被拒绝，请检查对端访问令牌") from exc
        if exc.code == 404:
            raise PeerFetchError("对端不支持看板接口，请升级对端状态服务") from exc
        raise PeerFetchError(f"服务返回 HTTP {exc.code}") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise PeerFetchError("服务无法连接或响应超时") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PeerFetchError("服务返回了无效 JSON") from exc


def fetch_peer_snapshot(url: str, token: str = "", *, timeout: float = 3.0) -> dict[str, object]:
    """Enforce one wall-clock limit across DNS, connect, TLS, headers and body.

    A socket inactivity timeout alone cannot stop a peer that continuously sends
    incomplete response headers. A short-lived child owns the socket, so killing
    and reaping that child closes every network operation, without stranded
    polling threads. Credentials travel over stdin rather than argv or logs.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("服务查询超时必须为正数")
    deadline = time.monotonic() + timeout
    arguments = [sys.executable, "-I", str(Path(__file__).resolve()), "--fetch-peer"]
    try:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise PeerFetchError("无法启动设备查询进程") from exc
    payload = json.dumps({"url": url, "token": token, "timeout": timeout}, ensure_ascii=False).encode("utf-8")
    try:
        output, _ = process.communicate(payload, timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise PeerFetchError("服务响应超时") from exc
    except Exception:
        process.kill()
        process.communicate()
        raise
    if process.returncode != 0 or len(output) > MAX_RESPONSE_BYTES + 1024:
        raise PeerFetchError("设备查询进程未返回有效快照")
    try:
        result = json.loads(output)
    except (ValueError, UnicodeError) as exc:
        raise PeerFetchError("设备查询进程未返回有效快照") from exc
    if not isinstance(result, dict):
        raise PeerFetchError("设备查询进程未返回有效快照")
    if result.get("ok") is not True:
        raise PeerFetchError(str(result.get("error") or "服务响应处理失败"))
    snapshot = result.get("snapshot")
    if not isinstance(snapshot, dict):
        raise PeerFetchError("设备查询进程未返回有效快照")
    return snapshot


def _fetch_worker_main() -> int:
    try:
        raw = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise PeerFetchError("设备查询参数无效")
        parameters = json.loads(raw)
        snapshot = _fetch_peer_snapshot_in_worker(
            parameters["url"], parameters.get("token", ""), timeout=float(parameters["timeout"])
        )
        output = json.dumps({"ok": True, "snapshot": snapshot}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except Exception as exc:
        label = str(exc) if isinstance(exc, PeerFetchError) else "服务响应处理失败"
        output = json.dumps({"ok": False, "error": label}, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    return 0


class PeerServiceManager:
    def __init__(
        self, config_path: Path, *, poll_interval: float = 5.0, timeout: float = 3.0, max_peers: int = 8
    ) -> None:
        self.config_path = Path(config_path)
        self.poll_interval = max(1.0, float(poll_interval))
        self.timeout = min(15.0, max(0.1, float(timeout)))
        self.max_peers = min(8, max(1, int(max_peers)))
        self._lock = threading.RLock()
        self._peers: dict[str, dict[str, str]] = {}
        self._cache: dict[str, dict[str, object]] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._configuration_error = ""
        self._load()

    def _load(self) -> None:
        try:
            if self.config_path.stat().st_size > MAX_RESPONSE_BYTES:
                raise ValueError("configuration too large")
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("peers"), list):
                raise ValueError("configuration format")
            for item in data["peers"][: self.max_peers]:
                if not isinstance(item, dict):
                    continue
                try:
                    name, url, token = self._validate(item.get("name"), item.get("url"), item.get("token", ""))
                except ValueError:
                    self._configuration_error = "部分设备配置无效，请重新添加设备"
                    continue
                peer_id = str(item.get("id") or uuid.uuid4().hex)
                if len(peer_id) > 64 or not peer_id.replace("-", "").isalnum():
                    peer_id = uuid.uuid4().hex
                self._peers[peer_id] = {"id": peer_id, "name": name, "url": url, "token": token}
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError):
            self._configuration_error = "设备配置读取失败，请检查本地运行目录"

    @staticmethod
    def _validate(name: object, url: object, token: object) -> tuple[str, str, str]:
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("设备名称不能为空，最多 80 个字符")
        if any(ord(character) < 32 for character in name):
            raise ValueError("设备名称包含控制字符")
        if not isinstance(token, str) or len(token) > 4096 or any(ord(character) < 32 for character in token):
            raise ValueError("访问令牌格式无效")
        return name.strip(), validate_service_url(url), token.strip()  # type: ignore[arg-type]

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_name(f".{self.config_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "peers": list(self._peers.values())}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
            if os.name != "nt":
                self.config_path.chmod(0o600)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def control(
        self, action: str, *, name: str = "", url: str = "", token: str = "", peer_id: str = ""
    ) -> dict[str, object]:
        if action not in {"add", "remove"}:
            raise ValueError("未知设备操作")
        with self._lock:
            previous = self._peers.copy()
            if action == "add":
                name, url, token = self._validate(name, url, token)
                existing = next((item for item in self._peers.values() if item["url"] == url), None)
                if not existing and len(self._peers) >= self.max_peers:
                    raise ValueError(f"最多添加 {self.max_peers} 台设备")
                peer_id = existing["id"] if existing else uuid.uuid4().hex
                self._peers[peer_id] = {"id": peer_id, "name": name, "url": url, "token": token}
            else:
                if not peer_id and url:
                    normalized = validate_service_url(url)
                    peer_id = next((key for key, peer in self._peers.items() if peer["url"] == normalized), "")
                if peer_id not in self._peers:
                    raise ValueError("设备不存在或已被移除")
                self._peers.pop(peer_id)
            try:
                self._save()
            except OSError:
                self._peers = previous
                raise
            self._cache.pop(peer_id, None)
            self._configuration_error = ""
        self._wake.set()
        return {"ok": True, "peer_id": peer_id}

    def public_snapshot(self) -> dict[str, object]:
        now = time.time()
        with self._lock:
            items: list[dict[str, object]] = []
            for peer in self._peers.values():
                cached = self._cache.get(peer["id"], {})
                success = float(cached.get("last_success_at") or 0)
                stale = not success or bool(cached.get("error")) or now - success > max(15, self.poll_interval * 3)
                items.append(
                    {
                        "id": peer["id"],
                        "name": peer["name"],
                        "url": peer["url"],
                        "connected": bool(success) and not stale,
                        "stale": stale,
                        "last_success_at": success,
                        "last_attempt_at": cached.get("last_attempt_at", 0),
                        "error": cached.get("error", "等待首次连接" if not success else ""),
                        "snapshot": copy.deepcopy(cached.get("snapshot")),
                    }
                )
            return {
                "items": items,
                "total": len(items),
                "poll_interval_seconds": self.poll_interval,
                "configuration_error": self._configuration_error,
            }

    def _poll(self, peer: dict[str, str]) -> None:
        attempted_at = time.time()
        try:
            snapshot = fetch_peer_snapshot(peer["url"], peer["token"], timeout=self.timeout)
        except Exception as exc:
            error = str(exc) if isinstance(exc, PeerFetchError) else "服务响应处理失败"
            result = {"last_attempt_at": attempted_at, "error": error}
        else:
            result = {
                "last_attempt_at": attempted_at,
                "last_success_at": time.time(),
                "error": "",
                "snapshot": snapshot,
            }
        with self._lock:
            # Ignore work for a deleted/reconfigured source. In particular, never
            # attach an old response to a source with a replacement credential.
            if self._peers.get(peer["id"]) == peer:
                self._cache[peer["id"]] = {**self._cache.get(peer["id"], {}), **result}

    def _run(self) -> None:
        with ThreadPoolExecutor(max_workers=min(4, self.max_peers), thread_name_prefix="peer-poll") as executor:
            with self._lock:
                self._executor = executor
            while not self._stop.is_set():
                self._wake.clear()
                with self._lock:
                    if self._stop.is_set():
                        break
                    peers = [peer.copy() for peer in self._peers.values()]
                    futures = [executor.submit(self._poll, peer) for peer in peers]
                for future in futures:
                    try:
                        future.result()
                    except CancelledError:
                        pass
                if not self._stop.is_set():
                    self._wake.wait(self.poll_interval)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="peer-services", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._wake.set()
            executor = self._executor
            if executor:
                executor.shutdown(wait=False, cancel_futures=True)
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=min(1.0, self.timeout + 0.1))


if __name__ == "__main__":
    raise SystemExit(_fetch_worker_main() if sys.argv[1:] == ["--fetch-peer"] else 2)
