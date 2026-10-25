#!/usr/bin/env python3
"""Run this repository's acceptance ladder and write an evidence directory.

The ladder is the one documented in docs/acceptance.md:

  1. node verify/validate_repo.mjs                 (required)
  2. python verify/smoke.py --with-gate            (required)
  3. python verify/probe_mcp.py --command ...      (required when uvx is present)
  4. python install/install.py --doctor            (informational)
  5. a dry run against the project given by --project (informational, writes nothing)
  6. the harness's own listing, when it can run non-interactively (informational)

Evidence lands in evidence/<UTC stamp>-<short id>/ with report.md, report.json and
one command-*.log per step. Exit 0 only if every REQUIRED step exited 0.

Usage:
    python verify/acceptance.py [--project DIR] [--no-probe]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence"


class Step:
    def __init__(self, name: str, cmd: list[str], required: bool, cwd: Path | None = None,
                 env: dict | None = None, note: str = ""):
        self.name = name
        self.cmd = cmd
        self.required = required
        self.cwd = cwd or REPO
        self.env = env
        self.note = note
        self.code: int | None = None
        self.seconds = 0.0
        self.output = ""


def cli(name: str, *args: str) -> list[str]:
    """A runnable command line for a harness CLI, including Windows script shims."""
    path = shutil.which(name)
    if path is None:
        return [name, *args]
    if path.lower().endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path, *args]
    if path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path, *args]
    return [path, *args]


def run(step: Step) -> Step:
    started = datetime.now(timezone.utc)
    env = dict(os.environ)
    # Children may print non-ASCII paths; keep every hop UTF-8 so evidence logs do
    # not turn into mojibake on a non-UTF-8 Windows code page.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.update(step.env or {})
    print("==> %s" % step.name)
    try:
        proc = subprocess.run(step.cmd, cwd=str(step.cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env)
        step.code = proc.returncode
        step.output = (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as exc:
        step.code = 127
        step.output = "command not found: %s" % exc
    step.seconds = (datetime.now(timezone.utc) - started).total_seconds()
    print("    exit %s in %.0fs" % (step.code, step.seconds))
    return step


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acceptance.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None,
                        help="a real Lean project to dry-run against (no writes)")
    parser.add_argument("--no-probe", action="store_true", help="skip the MCP stdio probe")
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = "%s-%s" % (stamp, secrets.token_hex(3))
    run_dir = EVIDENCE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    # Scratch trees live outside the evidence directory on purpose: evidence is a
    # run record (reports + raw logs), not a copy of everything the run built.
    scratch = REPO / ".smoke" / run_id
    scratch.mkdir(parents=True, exist_ok=True)
    smoke_work = scratch / "smoke"

    steps: list[Step] = [
        Step("validate-repo", ["node", "verify/validate_repo.mjs"], required=True),
        Step("smoke", [python, "verify/smoke.py", "--with-gate", "--work", str(smoke_work)],
             required=True, note="install → assert → idempotence → uninstall, plus a real Lean build"),
        Step("gate-shell", [python, "verify/check_gate_shell.py"], required=True,
             note="the POSIX gate's embedded Python: parses, reads config, enforces the whitelist "
                  "(the shell wrapper itself needs a real bash and is not covered)"),
        Step("provenance-recheck", [python, "verify/provenance_recheck.py"], required=True,
             note="a second, independent implementation of the vendored-hash check"),
    ]

    if not args.no_probe and shutil.which("uvx"):
        # Keep uv's cache OUT of the evidence directory: it holds hundreds of
        # package files that have no business in a run record.
        uv_cache = REPO / ".uv-probe" / "cache"
        uv_tools = REPO / ".uv-probe" / "tools"
        uv_cache.mkdir(parents=True, exist_ok=True)
        uv_tools.mkdir(parents=True, exist_ok=True)
        steps.append(Step(
            "probe-lean-lsp",
            [python, "verify/probe_mcp.py", "--command", "uvx lean-lsp-mcp",
             "--env", "LEAN_LOG_LEVEL=NONE",
             "--env", "LEAN_MCP_DISABLED_TOOLS=lean_build,lean_run_code",
             "--env", "UV_CACHE_DIR=%s" % uv_cache, "--env", "UV_TOOL_DIR=%s" % uv_tools,
             "--expect", "lean_goal", "--expect", "lean_diagnostic_messages",
             "--expect", "lean_local_search", "--forbid", "lean_build", "--forbid", "lean_run_code",
             "--timeout", "300"],
            required=True,
            note="the exact command the lsp-fallback configuration records",
        ))
    else:
        steps.append(Step("probe-lean-lsp", [python, "-c", "print('skipped: uvx not on PATH')"],
                          required=False, note="skipped"))

    doctor_project = args.project or str(smoke_work / "FixtureProj")
    steps.append(Step("doctor", [python, "install/install.py", "--doctor", "--project", doctor_project],
                      required=False, note="per-harness detection and file presence"))

    if args.project:
        steps.append(Step("dry-run-target-project",
                          [python, "install/install.py", "--project", args.project,
                           "--home", str(scratch / "dryrun-home"), "--scope", "both", "--dry-run"],
                          required=False, note="writes nothing; the plan is inspected by the reviewer"))

    # A harness-level check: does an installed harness actually READ what we wrote?
    # Optional, because it needs that harness's CLI and a non-interactive shell.
    if shutil.which("claude"):
        probe_project = scratch / "harness-probe"
        probe_project.mkdir(parents=True, exist_ok=True)
        (probe_project / "lean-toolchain").write_text("leanprover/lean4:v4.34.0\n", encoding="utf-8")
        (probe_project / "lakefile.toml").write_text(
            'name = "HarnessProbe"\ndefaultTargets = ["HarnessProbe"]\n\n[[lean_lib]]\nname = "HarnessProbe"\n',
            encoding="utf-8")
        (probe_project / "HarnessProbe.lean").write_text("import Lean\n", encoding="utf-8")
        steps.append(Step("install-for-harness-probe",
                          [python, "install/install.py", "--project", str(probe_project),
                           "--home", str(scratch / "harness-home"),
                           "--dsh-home", str(scratch / "harness-home" / "dsh-home"),
                           "--agents-home", str(scratch / "harness-home" / ".agents"),
                           "--scope", "both"],
                          required=False, note="install into a throwaway Lean project + home"))
        steps.append(Step("claude-mcp-list", cli("claude", "mcp", "list"), cwd=probe_project,
                          required=False,
                          note="informational: does Claude Code read the .mcp.json we wrote? (.mcp.json is the installer's own surface; .claude.json is not touched)"))
        if shutil.which("codex"):
            steps.append(Step("codex-mcp-list", cli("codex", "mcp", "list"), cwd=probe_project,
                              env={"CODEX_HOME": str(scratch / "harness-home" / ".codex")},
                              required=False,
                              note="informational: does Codex read the config.toml we wrote? (CODEX_HOME points at the throwaway home)"))
        if shutil.which("opencode"):
            # Run outside every git repository: OpenCode walks up looking for one and,
            # inside a sandbox, is refused permission to spawn `git` there.
            opencode_cwd = Path(tempfile.mkdtemp(prefix="lf-opencode-"))
            steps.append(Step("opencode-mcp-list", cli("opencode", "mcp", "list"),
                              cwd=opencode_cwd,
                              env={
                                  "XDG_CONFIG_HOME": str(scratch / "harness-home" / ".config"),
                                  "XDG_DATA_HOME": str(scratch / "harness-home" / ".local" / "share"),
                                  "XDG_STATE_HOME": str(scratch / "harness-home" / ".local" / "state"),
                                  "XDG_CACHE_HOME": str(scratch / "harness-home" / ".local" / "cache"),
                              },
                              required=False,
                              note="informational: does OpenCode read the opencode.json we wrote? (run outside a git repo: OpenCode itself may be refused permission to spawn git/uvx inside a sandbox — that is not a config failure)"))

    for step in steps:
        run(step)
        (run_dir / ("command-%s.log" % step.name)).write_text(
            "$ %s\n\n%s" % (" ".join(step.cmd), step.output), encoding="utf-8", newline="\n")

    required_failed = [s for s in steps if s.required and s.code != 0]
    ok = not required_failed

    report = {
        "gate": "lean-formalization acceptance",
        "runId": run_id,
        "timestampUtc": stamp,
        "ok": ok,
        "repo": str(REPO),
        "python": python,
        "uvx": shutil.which("uvx"),
        "steps": [{"name": s.name, "command": " ".join(s.cmd), "exitCode": s.code,
                   "seconds": round(s.seconds, 1), "required": s.required, "note": s.note,
                   "cwd": str(s.cwd)} for s in steps],
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = ["# lean-formalization acceptance — %s" % run_id, "",
             "- repository: `%s`" % REPO,
             "- result: **%s**" % ("PASS" if ok else "FAIL"),
             "- steps not marked required are informational; read their logs, do not assume.", "",
             "| step | required | exit | seconds | note |", "|---|---|---|---|---|"]
    for s in steps:
        lines.append("| %s | %s | %s | %.0f | %s |" % (
            s.name, "yes" if s.required else "no", s.code, s.seconds, s.note.replace("|", "\\|")))
    lines += ["", "## raw output", "", "See `command-*.log` next to this file.", "",
              "Unknowns are written as unknown: a step with exit `None` or a skipped note was not run."]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print("")
    print("evidence: %s" % run_dir)
    if not ok:
        print("FAILED required steps: %s" % ", ".join(s.name for s in required_failed))
        return 1
    print("acceptance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
