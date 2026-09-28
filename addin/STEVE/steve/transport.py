"""Small, thread-safe JSON-RPC transport for a local Codex app-server."""
import json
import os
from pathlib import Path
import platform
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from .version import VERSION as STEVE_VERSION

# Reproducible build baseline, not a restriction on independently updated runtimes.
VERSION = "0.155.1"


class RuntimeUnavailable(RuntimeError):
    pass


def data_home(system=None):
    """Per-user STEVE data folder: LOCALAPPDATA on Windows, Application Support on macOS."""
    system = system or sys.platform
    if system == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "STEVE"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "STEVE"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "STEVE"


def host_target(system=None, machine=None):
    """Rust target triple of this Python process; the bundled Codex runtime must match it."""
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "win32":
        return f"{arch}-pc-windows-msvc"
    if system == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-musl"


def bundled_runtime():
    return Path(__file__).resolve().parents[1] / "runtime"


def selected_runtime(home=None, target=None):
    """An atomic pointer selects an independently installed, verified runtime."""
    folder = Path(home or data_home()) / "runtimes"
    target = target or host_target()
    try:
        selection = json.loads((folder / "active.json").read_text(encoding="utf-8"))
        name = selection.get("directory", "")
        if not re.fullmatch(r"codex-[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{32}", name):
            return bundled_runtime()
        root = folder / name
        if not root.resolve().is_relative_to(folder.resolve()):
            return bundled_runtime()
        runtime_command(root, target)
        return root
    except (OSError, ValueError, AttributeError, RuntimeUnavailable):
        return bundled_runtime()


def runtime_version(root=None):
    try:
        return json.loads(((root or selected_runtime()) / "steve-runtime.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def runtime_command(root=None, target=None):
    root = Path(root) if root else selected_runtime(target=target)
    target = target or host_target()
    suffix = ".exe" if target.endswith("-windows-msvc") else ""
    manifest = root / "steve-runtime.json"
    executable = root / "bin" / ("codex-app-server" + suffix)
    if not manifest.is_file() or not executable.is_file():
        raise RuntimeUnavailable("Codex is missing from STEVE. Install or repair STEVE using the complete STEVE package.")
    if not (root / "bin" / ("codex-code-mode-host" + suffix)).is_file():
        raise RuntimeUnavailable("Codex is incomplete: its Code Mode host is missing. Repair STEVE with the complete package.")
    if not (root / "codex-resources").is_dir() or not (root / "codex-package.json").is_file():
        raise RuntimeUnavailable("Codex's supporting resources are missing. Repair STEVE with the complete package.")
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        version = metadata.get("version")
        package = json.loads((root / "codex-package.json").read_text(encoding="utf-8"))
        package_version = package.get("version")
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeUnavailable("Codex's package metadata is damaged. Repair STEVE with the complete package.") from exc
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or package_version != version:
        raise RuntimeUnavailable("This Codex runtime is incompatible with STEVE. Repair STEVE with the complete package.")
    built_for = metadata.get("target") or package.get("target")
    if (built_for and built_for != target) or package.get("target", target) != target:
        raise RuntimeUnavailable(f"This Codex runtime was built for {built_for}, not this computer ({target}). "
                                 "Install the STEVE package made for your platform.")
    if not suffix and not os.access(executable, os.X_OK):
        raise RuntimeUnavailable("Codex's executable lost its run permission. Reinstall STEVE with its installer.")
    return [str(executable), "--listen", "stdio://"]


def process_options():
    """Hide the console on Windows; elsewhere own a process group so shutdown reaches Codex's helpers."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def terminate_tree(process):
    """Force-stop the runtime and any helper it started when EOF did not end it."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        process.kill()


def runtime_environment(home):
    env = dict(os.environ)
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CHATGPT_API_KEY", "STEVE_OLLAMA_API_KEY",
                 "STEVE_OPENAI_COMPAT_API_KEY"):
        env.pop(name, None)
    env["CODEX_HOME"] = str(home / "codex")
    env["RUST_LOG"] = "error"
    return env


class Transport:
    def __init__(self, on_event, command=None, home=None, on_request=None):
        self.on_event = on_event
        self.on_request = on_request
        self.debug = None
        self.command = command
        self.home = home or data_home()
        self.process = None
        self._pending = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._closed = False
        self._incoming = set()

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None and not self._closed

    def environment(self):
        return runtime_environment(self.home)

    def start(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "codex").mkdir(exist_ok=True)
        (self.home / "workspace").mkdir(exist_ok=True)
        root = selected_runtime() if self.command is None else None
        self.runtime_version = runtime_version(root) if root else ""
        self.runtime_managed = root is not None and root != bundled_runtime()
        try:
            self.process = subprocess.Popen(
                self.command or runtime_command(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=self.home / "workspace", env=self.environment(),
                **process_options(),
            )
        except OSError as exc:
            raise RuntimeUnavailable("Codex could not start. Repair STEVE's runtime, then try again.") from exc
        self._reader = threading.Thread(target=self._read, name="STEVE-Codex", daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="STEVE-Codex-errors", daemon=True)
        self._stderr_reader.start()
        self._reader.start()
        self._log("runtime.started")
        try:
            self.request("initialize", {"clientInfo": {"name": "steve", "title": "STEVE", "version": STEVE_VERSION},
                                        "capabilities": {"experimentalApi": True}})
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def _send(self, payload):
        with self._write_lock:
            if not self.alive:
                raise RuntimeError("Codex disconnected. Reconnect STEVE to continue.")
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def request(self, method, params=None, timeout=30):
        started = time.monotonic()
        mailbox = queue.Queue(maxsize=1)
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = mailbox
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                response = mailbox.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"Codex took too long to respond to {method}. Try reconnecting.") from None
            if "error" in response:
                raise RuntimeError(response["error"].get("message", "Codex request failed."))
            return response.get("result", {})
        except Exception as exc:
            self._log("rpc.error", method=method, error=type(exc).__name__ if method.startswith("account/") else str(exc))
            raise
        finally:
            self._log("rpc.completed", method=method, durationMs=round((time.monotonic() - started) * 1000))
            with self._lock:
                self._pending.pop(request_id, None)

    def notify(self, method, params):
        self._send({"method": method, "params": params})

    def _log(self, event, **details):
        if self.debug:
            self.debug.record(event, **details)

    def _read_stderr(self):
        try:
            while True:
                line = self.process.stderr.readline(16000)
                if not line:
                    break
                self._log("runtime.stderr", message=line.rstrip())
        except (OSError, ValueError):
            pass

    def reply(self, request_id, result=None, error=None):
        with self._lock:
            if self._closed or request_id not in self._incoming:
                return
            self._incoming.remove(request_id)
        try:
            self._send({"id": request_id, **({"error": error} if error else {"result": result})})
        except (RuntimeError, OSError, ValueError):
            if not self._closed:
                raise

    def _read(self):
        reason = "Codex disconnected. Reconnect STEVE to continue."
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if "method" in message:
                    if "id" in message:
                        request_id = message["id"]
                        with self._lock:
                            if request_id in self._incoming:
                                continue
                            self._incoming.add(request_id)
                        if self.on_request:
                            try:
                                # Handler enqueues work; it must not wait for Fusion here.
                                self.on_request(request_id, message["method"], message.get("params") or {})
                            except Exception as exc:
                                self.reply(request_id, error={"code": -32603, "message": str(exc)})
                        else:
                            self.reply(request_id, error={"code": -32601, "message": "Unsupported server request."})
                    else:
                        self.on_event(message["method"], message.get("params") or {})
                else:
                    with self._lock:
                        mailbox = self._pending.get(message.get("id"))
                    if mailbox:
                        mailbox.put_nowait(message)
        except Exception as exc:
            self._log("runtime.read_error", error=type(exc).__name__)
            reason = "The Codex connection stopped unexpectedly. Reconnect STEVE to continue."
        finally:
            self._fail_pending(reason)
            if not self._closed:
                self.on_event("steve/disconnected", {"message": reason})

    def _fail_pending(self, message):
        with self._lock:
            for mailbox in self._pending.values():
                try:
                    mailbox.put_nowait({"error": {"message": message}})
                except queue.Full:
                    pass

    def close(self):
        self._closed = True
        self._incoming.clear()
        self._fail_pending("STEVE is shutting down.")
        process = self.process
        if process:
            if process.poll() is None:
                # EOF lets app-server dispose its Code Mode companion before exiting.
                with self._write_lock:
                    try:
                        if not process.stdin.closed:
                            process.stdin.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    terminate_tree(process)
                    process.wait(timeout=2)
            if hasattr(self, "_stderr_reader"):
                self._stderr_reader.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        self._log("runtime.stopped")
