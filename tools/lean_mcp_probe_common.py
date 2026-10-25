"""Shared command and environment for the Lean MCP probes.

Keep this module aligned with build_lean_preset.py. The probes are intended to
exercise the same pinned server and disabled-tool policy as the DSH preset.
"""

from pathlib import Path
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from lean_capabilities import read_spec, disabled_tools

SPEC = read_spec()
PACKAGE = os.environ.get("LEAN_MCP_PACKAGE", SPEC["mcp"]["servers"]["lean-lsp"]["command"][1])
DISABLED_TOOLS = ",".join(disabled_tools(SPEC, "lsp-fallback"))
REQUIRED_TOOLS = set(SPEC["mcp"]["capabilityProfiles"]["lsp-fallback"]["requiredTools"]["lean-lsp"])
FORBIDDEN_TOOLS = set(disabled_tools(SPEC, "lsp-fallback"))


def resolve_uvx() -> str:
    override = os.environ.get("LEAN_UVX")
    if override:
        return override
    local = Path.home() / ".local" / "bin"
    for candidate in (local / "uvx.exe", local / "uvx"):
        if candidate.is_file():
            return str(candidate)
    for name in ("uvx.exe", "uvx"):
        found = shutil.which(name)
        if found:
            return found
    return "uvx.exe" if os.name == "nt" else "uvx"


def command() -> list[str]:
    direct = os.environ.get("LEAN_MCP_SERVER")
    if direct:
        return [direct]
    return [resolve_uvx(), PACKAGE]


def make_env(with_local_bin: bool = True) -> dict[str, str]:
    env = dict(os.environ)
    env["LEAN_LOG_LEVEL"] = os.environ.get("LEAN_MCP_PROBE_LOG_LEVEL", "NONE")
    env["LEAN_MCP_DISABLED_TOOLS"] = DISABLED_TOOLS
    env["LEAN_MCP_MAX_OUTPUT_CHARS"] = "12000"
    local_bin = str(Path.home() / ".local" / "bin")
    path = env.get("PATH", "")
    entries = [p for p in path.split(os.pathsep) if p]
    if with_local_bin:
        entries = [local_bin] + [p for p in entries if p.lower() != local_bin.lower()]
    else:
        entries = [p for p in entries if p.lower() != local_bin.lower()]
    env["PATH"] = os.pathsep.join(entries)
    # The live host may export a cache root that is readable from PowerShell
    # but not writable by a child spawned through uvx.  Keep the production
    # environment untouched unless the caller explicitly provides probe-local
    # roots; this makes the ACL workaround auditable and reversible.
    probe_cache = os.environ.get("LEAN_MCP_UV_CACHE_DIR")
    probe_tool_dir = os.environ.get("LEAN_MCP_UV_TOOL_DIR")
    if probe_cache:
        env["UV_CACHE_DIR"] = probe_cache
    if probe_tool_dir:
        env["UV_TOOL_DIR"] = probe_tool_dir
    return env


def default_project() -> Path:
    return Path(os.environ.get("LEAN_PROBE_PROJECT", str(Path.home() / ".lean-formalization" / "probe")))


def assert_tool_surface(tools: list[dict]) -> tuple[list[str], list[str]]:
    names = sorted(str(tool.get("name")) for tool in tools)
    missing = sorted(f"lean:{name}" for name in REQUIRED_TOOLS if name not in names)
    forbidden = sorted(name for name in FORBIDDEN_TOOLS if name in names)
    return missing, forbidden


class ProbeTimeout(RuntimeError):
    """A bounded MCP request did not receive its matching response."""


class StdioClient:
    """Small newline-delimited JSON-RPC client with bounded reads.

    MCP stdio uses one JSON object per line (not HTTP ``Content-Length``
    framing).  A reader thread is used solely to make the blocking Windows
    pipe observable through a queue; every request has a hard deadline.
    """

    def __init__(self, *, timeout: float | None = None, with_local_bin: bool = True,
                 server_command: list[str] | None = None, env: dict | None = None,
                 cwd: str | None = None):
        self.timeout = float(
            timeout if timeout is not None
            else os.environ.get("LEAN_MCP_PROBE_TIMEOUT", "20")
        )
        self.proc = subprocess.Popen(
            server_command if server_command is not None else command(),
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env if env is not None else make_env(with_local_bin),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stderr: list[str] = []
        self._stderr_lock = threading.Lock()
        threading.Thread(
            target=self._pump, args=(self.proc.stdout, self._stdout), daemon=True
        ).start()
        threading.Thread(
            target=self._pump_stderr, args=(self.proc.stderr,), daemon=True
        ).start()
        self.next_id = 0

    @staticmethod
    def _pump(stream, target: queue.Queue[str | None]) -> None:
        if stream is None:
            target.put(None)
            return
        try:
            for line in stream:
                target.put(line)
        finally:
            target.put(None)

    def _pump_stderr(self, stream) -> None:
        if stream is None:
            return
        for line in stream:
            with self._stderr_lock:
                self._stderr.append(line.rstrip("\r\n"))
                del self._stderr[:-20]

    def stderr_tail(self) -> list[str]:
        with self._stderr_lock:
            return list(self._stderr[-8:])

    def send(self, method: str, params: dict | None = None, *, notification: bool = False) -> int | None:
        if self.proc.stdin is None:
            raise RuntimeError("MCP server stdin is unavailable")
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        ident = None
        if not notification:
            self.next_id += 1
            ident = self.next_id
            message["id"] = ident
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return ident

    def request(self, method: str, params: dict | None = None) -> dict:
        ident = self.send(method, params)
        assert ident is not None
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeTimeout(
                    f"no response to request id {ident} within {self.timeout:.0f}s; "
                    f"server pid={self.proc.pid} returncode={self.proc.poll()}; "
                    f"stderr={self.stderr_tail()!r}"
                )
            try:
                line = self._stdout.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise ProbeTimeout(
                    f"server closed stdout before request id {ident}; "
                    f"returncode={self.proc.poll()}; stderr={self.stderr_tail()!r}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                # A few wrappers log to stdout.  Ignore those lines while
                # preserving the deadline for the JSON-RPC response.
                continue
            if reply.get("id") == ident:
                return reply

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            # EOF lets a Beam MCP owner clean up its workspace processes.
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
