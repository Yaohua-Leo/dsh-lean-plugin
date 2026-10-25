#!/usr/bin/env python3
"""Lean formalization installer.

One implementation, three launchers (this file, `install.ps1`, `install.sh`), so
the two shell entry points cannot drift apart.

It reads `harnesses.json` — the single source of truth for per-harness surfaces —
and writes, idempotently, only the pieces this repository owns:

  * the contract block into each detected harness's instruction files
  * `skills/lean-formalization` and `skills/lean-beam` into each skill root
  * the Lean MCP servers into each harness's MCP configuration
  * the DSH bundle installation command (when DSH is detected); profile changes
    are left to the explicit `dsh plugin --profile … add …` command
  * `lean-formalization.json` plus the acceptance-gate scaffold into a Lean project

Every write is backed up and recorded in a manifest, so `--uninstall` restores
the machine exactly. `--dry-run` prints the plan and writes nothing.

Exit codes: 0 ok, 1 a step failed, 2 bad usage / not a Lean project when one was
required, 3 nothing to do (no harness detected).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "harnesses.json"
TAG = "lean-formalization"


# ─────────────────────────────────────────────────────────────────────────────
# helpers


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4 :].lstrip("\n")
    return text


class Installer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.repo = REPO
        self.spec = json.loads(read_text(SPEC_PATH))
        self.dry_run = bool(args.dry_run)

        self.home = Path(args.home).expanduser().resolve() if args.home else Path.home().resolve()
        self.project = Path(args.project).expanduser().resolve()
        # `--home` means "act as if this were the home directory". Ambient DSH_* env
        # variables must not leak a scratch run into the real DSH home, so they are
        # only consulted when --home was not given.
        explicit_home = bool(args.home)
        self.dsh_home = (
            Path(args.dsh_home).expanduser().resolve()
            if args.dsh_home
            else Path(
                os.environ.get("DSH_HOME") or (self.home / ".dsh")
            ).expanduser().resolve()
            if not explicit_home
            else (self.home / ".dsh").resolve()
        )
        self.agents_home = (
            Path(args.agents_home).expanduser().resolve()
            if args.agents_home
            else Path(
                os.environ.get("DSH_AGENTS_HOME") or (self.home / ".agents")
            ).expanduser().resolve()
            if not explicit_home
            else (self.home / ".agents").resolve()
        )
        self.scope = args.scope  # project | user | both
        self.stamp = utc_stamp()
        self.backup_root_project = self.project / ".lean-formalization" / "backups" / self.stamp
        self.backup_root_user = self.home / ".lean-formalization" / "backups" / self.stamp

        self.actions: list[dict] = []
        self.notes: list[str] = []
        self.warnings: list[str] = []
        self.failures: list[str] = []
        self.manifest_project: list[dict] = []
        self.manifest_user: list[dict] = []
        self.detected: list[str] = []
        self.skipped: list[str] = []
        self._project_scope_noted = False
        self.planned: dict[str, str] = {}   # resolved path -> content hash already planned
        self.planned_by: dict[str, str] = {}  # resolved path -> first harness that planned it

        self.lean_project = self._detect_lean_project()
        self.beam = self._detect_beam()
        # OpenCode changed its MCP config shape between 1.x and 2.x, and each major
        # rejects the other's shape outright, so the installed version decides.
        self.opencode_major = args.opencode_major or self._detect_opencode_major()
        self.project_cfg = self._load_or_build_project_config()

    # ── path expansion ──────────────────────────────────────────────────────

    def expand(self, raw: str, scope: str | None = None) -> Path:
        p = str(raw)
        p = p.replace("<project>", str(self.project))
        p = p.replace("<repo>", str(self.repo))
        p = p.replace("<DSH_HOME>", str(self.dsh_home))
        p = p.replace("<DSH_AGENTS_HOME or ~/.agents>", str(self.agents_home))
        p = p.replace("<DSH_AGENTS_HOME>", str(self.agents_home))
        if p.startswith("~/"):
            p = str(self.home) + p[1:]
        p = os.path.expandvars(p)
        path = Path(p)
        if not path.is_absolute():
            # A relative surface is relative to the scope it belongs to: project
            # surfaces land in the target project, user surfaces in the home.
            path = (self.project if scope == "project" else self.home) / path
        return path

    # ── detection ───────────────────────────────────────────────────────────

    def _detect_lean_project(self) -> bool:
        return (self.project / "lean-toolchain").is_file() and (
            (self.project / "lakefile.toml").is_file() or (self.project / "lakefile.lean").is_file()
        )

    def _detect_opencode_major(self) -> str | None:
        """Major version of the installed OpenCode, or None when it cannot be read."""
        exe = shutil.which("opencode")
        if not exe:
            return None
        try:
            proc = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                  timeout=30, encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(r"(\d+)\.[\d.]*", (proc.stdout or "") + (proc.stderr or ""))
        return match.group(1) if match else None

    def _detect_beam(self) -> dict | None:
        beam = self.spec["mcp"]["servers"]["lean-beam"]
        for probe in beam.get("detect", []):
            if probe["kind"] == "command":
                exe = probe["value"].split()[0]
                found = shutil.which(exe)
                if found:
                    return {"how": probe["value"], "command": [found]}
            elif probe["kind"] == "path":
                path = self.expand(probe["value"])
                if path.exists():
                    if "launcher" in probe:
                        # Only the path token is substituted; the rest are argv words
                        # like `powershell.exe` or `-NoProfile` and must stay verbatim.
                        # Forward slashes keep the same text valid in every harness's
                        # config format (JSON needs escaping, TOML does not).
                        project = str(self.project).replace("\\", "/")
                        cmd = [x.replace("<project>", project) for x in probe["launcher"]]
                    else:
                        cmd = [str(path)]
                    return {"how": str(path), "command": cmd}
        return None

    @property
    def beam_mode(self) -> bool:
        return self.beam is not None

    def harness_detected(self, h: dict) -> bool:
        detect = h.get("detect", {})
        if detect.get("always"):
            return True
        for cmd in detect.get("commands", []):
            if shutil.which(cmd):
                return True
        for env_name in detect.get("env", []):
            if os.environ.get(env_name):
                return True
        for raw in detect.get("paths", []):
            if self.expand(raw).exists():
                return True
        return False

    def select_harnesses(self) -> list[str]:
        chosen: list[str] = []
        forced = [x.strip() for x in (self.args.harnesses or "").split(",") if x.strip()]
        for hid, h in self.spec["harnesses"].items():
            if hid == "generic-agents-md":
                continue
            if forced:
                if hid in forced:
                    chosen.append(hid)
                continue
            tier = int(h.get("tier", 2))
            if tier == 1:
                if self.harness_detected(h):
                    chosen.append(hid)
                else:
                    self.skipped.append(hid)
            elif tier == 2 and self.args.include_unverified and self.harness_detected(h):
                chosen.append(hid)
        if not chosen and not forced:
            chosen.append("generic-agents-md")
            self.notes.append(
                "no tier-1 harness detected: falling back to the portable AGENTS.md surface"
            )
        return chosen

    # ── project config ──────────────────────────────────────────────────────

    def _default_project_config(self) -> dict:
        library = self.project.name
        lakefile = self.project / "lakefile.toml"
        if lakefile.is_file():
            lake_cfg = tomllib.loads(read_text(lakefile))
            libraries = lake_cfg.get("lean_lib", [])
            if libraries:
                library = libraries[0]["name"]
        elif (self.project / "lakefile.lean").is_file():
            m = re.search(r'(?m)^\s*lean_lib\s+([A-Za-z_][A-Za-z0-9_.]*)\b',
                          read_text(self.project / "lakefile.lean"))
            if m:
                library = m.group(1)
        return {
            "schemaVersion": 1,
            "mode": "beam" if self.beam_mode else "lsp-fallback",
            "library": library,
            "targets": [],
            "entryModules": [],
            "buildTargets": [library],
            "ownModulePrefixes": [library],
            "scanScript": "LeanScan.lean",
            "allowedAxioms": ["propext", "Classical.choice", "Quot.sound"],
            "evidenceDir": "evidence/lean",
            "lakeCommand": "lake",
            "leanAuditScript": "LeanAudit.lean",
            "checkCommand": "scripts/leancheck.ps1" if os.name == "nt" else "scripts/leancheck.sh",
            "gitSafeDirectories": [],
            "projectRules": [],
        }

    def _load_or_build_project_config(self) -> dict | None:
        if not self.lean_project:
            return None
        existing = self.project / "lean-formalization.json"
        cfg = json.loads(read_text(existing)) if existing.is_file() else self._default_project_config()
        if not cfg.get("library"):
            cfg["library"] = self._default_project_config()["library"]
        if not cfg.get("buildTargets"):
            cfg["buildTargets"] = [cfg["library"]]
        if not cfg.get("checkCommand"):
            cfg["checkCommand"] = self._default_project_config()["checkCommand"]
        if "ownModulePrefixes" not in cfg:
            cfg["ownModulePrefixes"] = [cfg["library"]]
        if not cfg.get("ownModulePrefixes"):
            self.warnings.append("ownModulePrefixes is empty; library scanning is disabled")
        cfg.setdefault("scanScript", "LeanScan.lean")
        # The mode is a fact about this machine, not a user preference: re-detect it
        # and report a change instead of silently keeping a stale value.
        detected_mode = "beam" if self.beam_mode else "lsp-fallback"
        if cfg.get("mode") != detected_mode:
            self.notes.append(
                "mode changed from %s to %s (Beam %s)"
                % (cfg.get("mode", "(unset)"), detected_mode,
                   "found at " + self.beam["how"] if self.beam else "not found on this machine")
            )
            cfg["mode"] = detected_mode
        return cfg

    # ── text composition ────────────────────────────────────────────────────

    def instruction_block(self, indent: int = 0) -> str:
        body = strip_frontmatter(read_text(self.repo / "contract.md"))
        head, _, _ = body.partition("## Project-specific rules (injected)")
        rules = [
            "## Project-specific rules (injected)",
            "",
            "The installer writes the project's own rules here, read from",
            "`lean-formalization.json`; nothing below weakens the non-negotiables above.",
            "",
        ]
        cfg = self.project_cfg or {}
        whitelist = cfg.get("allowedAxioms") or ["propext", "Classical.choice", "Quot.sound"]
        rules.append("- Axiom whitelist: %s." % ", ".join("`%s`" % a for a in whitelist))
        rules.append("- MCP mode on this machine: `%s`." % ("beam" if self.beam_mode else "lsp-fallback"))
        if cfg:
            rules.append("- Project root: `%s`." % self.project)
            rules.append("- Gate: `%s`; evidence under `%s/`." % (cfg.get("checkCommand"), cfg.get("evidenceDir")))
            if not cfg.get("targets"):
                rules.append(
                    "- This project has no audited targets yet: fill `targets` in "
                    "`lean-formalization.json` before claiming the gate passed."
                )
            for extra in cfg.get("projectRules") or []:
                rules.append("- %s" % extra)
        text = head.rstrip() + "\n\n" + "\n".join(rules) + "\n"
        if indent:
            text = "\n".join((" " * indent + line) if line.strip() else "" for line in text.splitlines()) + "\n"
        return text

    def marked_block(self) -> str:
        begin = self.spec["contract"]["blockBegin"]
        end = self.spec["contract"]["blockEnd"]
        return "%s\n%s\n%s\n" % (begin, self.instruction_block().rstrip(), end)

    # ── MCP composition ─────────────────────────────────────────────────────

    def mcp_env(self, server_id: str) -> dict:
        server = self.spec["mcp"]["servers"][server_id]
        env = dict(server.get("env") or {})
        if server_id == "lean-lsp":
            key = "beam" if self.beam_mode else "lspFallback"
            disabled = server["disabledTools"][key]
            env["LEAN_MCP_DISABLED_TOOLS"] = ",".join(disabled)
            if self.args.uv_cache_dir:
                env["UV_CACHE_DIR"] = self.args.uv_cache_dir
            if self.args.uv_tool_dir:
                env["UV_TOOL_DIR"] = self.args.uv_tool_dir
        return env

    def mcp_command(self, server_id: str) -> list[str]:
        if server_id == "lean-beam":
            assert self.beam is not None
            return list(self.beam["command"])
        return list(self.spec["mcp"]["servers"][server_id]["command"])

    def mcp_servers_to_mount(self) -> list[str]:
        return ["lean-beam", "lean-lsp"] if self.beam_mode else ["lean-lsp"]

    # ── action planning ─────────────────────────────────────────────────────

    def plan_harness(self, hid: str) -> None:
        h = self.spec["harnesses"][hid]
        scopes = {
            "project": ["project"],
            "user": ["user"],
            "both": ["project", "user"],
        }[self.scope]
        if "project" in scopes and not self.lean_project:
            # Project-scope surfaces only make sense in a Lean project; writing
            # AGENTS.md into an unrelated directory would be noise, and the user
            # asked for a Lean assistant.
            scopes = [scope for scope in scopes if scope != "project"]
            if not self._project_scope_noted:
                self.notes.append(
                    "project scope skipped: %s is not a Lean project (no lean-toolchain)" % self.project
                )
                self._project_scope_noted = True

        # instruction files
        for target in h.get("instructions", []):
            if target.get("method") in ("dsh-preset", "dsh-bundle"):
                continue
            if target["scope"] not in scopes:
                continue
            path = self.expand(target["path"], target["scope"])
            content = self.marked_block()
            digest = sha256_text(target.get("header", "") + content)
            if self.planned.get(str(path)) == digest:
                continue  # an earlier harness already planned this exact write
            self.planned[str(path)] = digest
            self.planned_by[str(path)] = hid
            self.actions.append({
                "kind": "block", "path": path, "scope": target["scope"],
                "label": "%s: contract block -> %s" % (hid, path), "content": content,
                "header": target.get("header", ""),
            })

        # skills
        for root in h.get("skillRoots", []):
            if root["scope"] not in scopes:
                continue
            base = self.expand(root["path"], root["scope"])
            for skill in self.spec["skills"]["owned"]:
                src = self.repo / "skills" / skill
                if not src.is_dir():
                    self.warnings.append("skill directory missing in repo: %s" % src)
                    continue
                dest = base / skill
                if str(dest) in self.planned:
                    continue  # shared skill root already covered
                self.planned[str(dest)] = "%s:%s" % (hid, self.planned_by.get(str(dest), hid))
                self.planned_by[str(dest)] = hid
                self.actions.append({
                    "kind": "copy_tree", "src": src, "dest": dest, "scope": root["scope"],
                    "label": "%s: skill %s -> %s" % (hid, skill, dest),
                })

        # MCP
        mcp = h.get("mcp", {})
        method = mcp.get("method")
        if method in ("dsh-preset", "dsh-bundle"):
            return  # handled once, in plan_dsh()
        if method in ("file-json", "file-toml") and not self.args.no_mcp:
            targets = mcp.get("targets") or [{"scope": scopes[0], "path": mcp.get("target")}]
            for target in targets:
                if target["scope"] not in scopes:
                    continue
                path = self.expand(target["path"], target["scope"])
                if method == "file-json":
                    if path.suffix == ".jsonc" or (not path.exists() and path.with_suffix(".jsonc").exists()):
                        self.warnings.append(
                            "%s: only a JSONC config exists at %s — add the server by hand "
                            "(docs/harness-matrix.md has the exact snippet)" % (hid, path)
                        )
                        continue
                    key_path, template, cleanup = self.json_shape(hid, mcp)
                    for server_id in self.mcp_servers_to_mount():
                        self.actions.append({
                            "kind": "json_entry", "path": path, "scope": target["scope"],
                            "key_path": key_path, "name": server_id,
                            "entry": self.render_entry(template, server_id), "cleanup": cleanup,
                            "label": "%s: mcp server %s -> %s" % (hid, server_id, path),
                        })
                else:
                    array_name = mcp.get("arrayOfTables")
                    if array_name:
                        # One action for ALL servers: per-server actions would rewrite
                        # the file once per server (new backup, churn) even when the
                        # final bytes are identical.
                        self.actions.append({
                            "kind": "toml_table", "path": path, "scope": target["scope"],
                            "array_of_tables": array_name,
                            "array_entries": [self.toml_fields(hid, sid)
                                              for sid in self.mcp_servers_to_mount()],
                            "label": "%s: mcp servers %s -> %s" % (
                                hid, "+".join(self.mcp_servers_to_mount()), path),
                        })
                    else:
                        for server_id in self.mcp_servers_to_mount():
                            self.actions.append({
                                "kind": "toml_table", "path": path, "scope": target["scope"],
                                "table": mcp.get("table", "mcp_servers").replace("{name}", server_id),
                                "fields": self.toml_fields(hid, server_id),
                                "label": "%s: mcp server %s -> %s" % (hid, server_id, path),
                            })

    def json_shape(self, hid: str, mcp: dict) -> tuple[list[str], dict, list[str] | None]:
        """Key path, entry template and stale key path — read from the table.

        A flat row carries `keyPath` + `entry`; a row with `shapeByMajor` carries
        one template per major version, and the installed version selects it. The
        template may also name a `staleKeyPath` whose OUR-only entries are removed
        when that shape is written (OpenCode 1.x rejects `mcp.servers` outright).
        """
        if "shapeByMajor" in mcp:
            shapes = mcp["shapeByMajor"]
            default = str(mcp.get("defaultMajor", "2"))
            if "versionProbe" in mcp and self.opencode_major is None:
                note = ("opencode: could not read `opencode --version`; wrote the %s.x shape. "
                        "If `opencode mcp list` says 'Configuration is invalid', re-run with "
                        "--opencode-major 1 (or 2)." % default)
                if note not in self.warnings:
                    self.warnings.append(note)
            major = self.opencode_major if self.opencode_major in shapes else default
            shape = shapes[major]
            return list(shape["keyPath"]), shape["entry"], shape.get("staleKeyPath")
        if "entry" in mcp:
            return list(mcp["keyPath"]), mcp["entry"], mcp.get("staleKeyPath")
        raise SystemExit(
            "harness %s: file-json needs an `entry` template (or `shapeByMajor`) in harnesses.json" % hid)

    def render_entry(self, template, server_id: str):
        if isinstance(template, dict):
            return {key: self.render_entry(value, server_id) for key, value in template.items()}
        if isinstance(template, list):
            return [self.render_entry(item, server_id) for item in template]
        return self.placeholder_value(template, server_id)

    def toml_fields(self, hid: str, server_id: str) -> dict:
        """Entry fields for a TOML harness, read from its `fields` template."""
        mcp = self.spec["harnesses"][hid]["mcp"]
        spec_fields = mcp.get("fields")
        if not spec_fields:
            raise SystemExit("harness %s has no TOML field template in harnesses.json" % hid)
        return {key: self.placeholder_value(value, server_id) for key, value in spec_fields.items()}

    def placeholder_value(self, value, server_id: str):
        if value == "{name}":
            return server_id
        if value == "{command}":
            return self.mcp_command(server_id)[0]
        if value == "{args}":
            return self.mcp_command(server_id)[1:]
        if value == "{command_array}":
            return self.mcp_command(server_id)
        if value == "{env}":
            return self.mcp_env(server_id)
        return value

    def plan_dsh(self) -> None:
        if "dsh" not in self.detected:
            return
        # Current DSH releases load preset layers from profile bundles.  The old
        # `$DSH_HOME/.agent-presets/lean/` directory is no longer read, and
        # writing it makes a successful-looking install that never appears in a
        # profile.  A profile name is user-owned, so the installer prepares the
        # bundle source and prints the exact command instead of editing an
        # arbitrary profile behind the user's back.
        bundle = self.repo / "preset"
        if not (bundle / "package.json").is_file() or not (bundle / "cordis.patch.yml").is_file():
            self.failures.append("DSH bundle is incomplete: %s" % bundle)
            return
        self.notes.append(
            "DSH bundle ready at %s; install it into each profile with: %s"
            % (bundle, self.dsh_bundle_command())
        )

    def dsh_bundle_command(self, profile: str = "<profile>") -> str:
        return "dsh plugin --profile %s add %s" % (
            profile, _quote_for_shell(str(self.repo / "preset"))
        )

    def render_dsh_composition(self) -> str:
        tmpl = read_text(self.repo / "dsh/preset/agent.cordis.yml.tmpl")
        identity = (
            "You are a Lean 4 formalization assistant powered by the {{model}} model, working on {{cwd}}.\n\n"
        )
        block = identity + self.instruction_block()
        yaml_block = "\n".join(
            (" " * 6 + line) if line.strip() else "" for line in block.splitlines()
        )
        rows = []
        if self.beam_mode:
            rows.append(
                "# Lean Beam is the inner loop: it drives the real Lean LSP session for a saved\n"
                "# file without editing it (`lean_run_at`), reports diagnostics and readiness\n"
                "# (`lean_sync`), inventories sorries/holes/diagnostics (`lean_todo`), and can\n"
                "# checkpoint the server's accepted state (`lean_save`). Launcher detected at\n"
                "# %s\n" % self.beam["how"]
            )
        else:
            rows.append(
                "# Lean Beam was NOT detected on this machine, so the lean-lsp server keeps its\n"
                "# own goal/diagnostic/hover/outline/completion tools (lsp-fallback mode).\n"
                "# Install Beam (https://github.com/leanprover/lean-beam) and re-run the\n"
                "# installer to switch this preset to Beam mode.\n"
            )
        for server_id in self.mcp_servers_to_mount():
            rows.append(self.render_dsh_mcp_row(server_id))
        detail = (
            "Beam detected at %s; the lean-lsp tools Beam owns are disabled by name."
            % self.beam["how"] if self.beam_mode
            else "Beam not detected; lean-lsp is the only proof-state server and keeps its goal/diagnostic tools."
        )
        return (
            tmpl.replace("{{CONTRACT_BLOCK_YAML}}", yaml_block)
            .replace("{{MCP_ROWS}}", "".join(rows))
            .replace("{{MCP_MODE}}", "beam" if self.beam_mode else "lsp-fallback")
            .replace("{{MCP_MODE_DETAIL}}", detail)
            .replace("{{CONTRACT_SOURCE}}", "contract.md v%s from %s" % (self.spec["contract"]["version"], TAG))
        )

    def render_dsh_mcp_row(self, server_id: str) -> str:
        cmd = self.mcp_command(server_id)
        env = self.mcp_env(server_id)
        timeout = self.spec["mcp"]["servers"][server_id]["timeoutMs"]
        lines = [
            "- id: mcp-%s" % server_id,
            "  name: '@deepseek-ai/dsh-mcp-client'",
            "  config:",
            "    serverName: %s" % server_id,
            "    transport: stdio",
            "    command: '%s'" % cmd[0].replace("\\", "/"),
        ]
        if len(cmd) > 1:
            lines.append("    args:")
            for a in cmd[1:]:
                lines.append("      - '%s'" % a.replace("\\", "/"))
        if env:
            lines.append("    env:")
            for k, v in env.items():
                lines.append("      %s: '%s'" % (k, v))
        lines.append("    toolCallTimeoutMs: %d" % timeout)
        startup = self.spec["mcp"]["servers"][server_id]["failOnStartupError"]
        lines.append("    failOnStartupError: %s" % str(startup).lower())
        return "\n".join(lines) + "\n\n"

    def plan_project(self) -> None:
        if not self.lean_project:
            return
        assert self.project_cfg is not None
        previous = self.previous_manifest_files()
        cfg_path = self.project / "lean-formalization.json"
        cfg_text = json.dumps(self.project_cfg, indent=2) + "\n"
        if cfg_path.is_file() and str(cfg_path) not in previous:
            # A config we did not write belongs to the project. Keep every key the
            # user set, refresh only the detected mode, and report the result.
            merged = {**self._default_project_config(), **self.project_cfg}
            merged["mode"] = "beam" if self.beam_mode else "lsp-fallback"
            self.project_cfg = merged
            cfg_text = json.dumps(merged, indent=2) + "\n"
            if cfg_path.read_text(encoding="utf-8") != cfg_text:
                self.notes.append("merged the existing lean-formalization.json (user keys kept)")
        if not cfg_path.is_file() or cfg_path.read_text(encoding="utf-8") != cfg_text:
            self.actions.append({
                "kind": "write_file", "path": cfg_path, "scope": "project", "content": cfg_text,
                "keep": True,
                "label": "project: lean-formalization.json -> %s" % cfg_path,
            })
        if self.args.no_project_gate:
            return
        # A gate file that already exists and that WE did not create is the project's
        # own: leave it alone and say so. Overwriting someone's LeanAudit.lean would
        # silently change what their acceptance pipeline means.
        gate = self.repo / "gate"
        plan = [
            (self.project / "LeanAudit.lean", read_text(gate / "LeanAudit.lean")),
            (self.project / "LeanScan.lean", read_text(gate / "LeanScan.lean")),
            (self.project / "scripts" / "leancheck.ps1", read_text(gate / "leancheck.ps1")),
            (self.project / "scripts" / "leancheck.sh", read_text(gate / "leancheck.sh")),
            (self.project / self.project_cfg.get("evidenceDir", "evidence/lean") / "README.md",
             "# Evidence\n\n"
             "`runs/<UTC stamp>-<short id>/` holds one directory per gate run "
             "(`report.md`, `report.json`, `command-*.log`). `LATEST.md` is a navigation "
             "copy, not a replacement for history: failed and corrected records are appended, "
             "never erased.\n"),
        ]
        for path, content in plan:
            if path.is_file() and str(path) not in previous:
                self.notes.append("existing gate file left untouched: %s" % path)
                continue
            self.actions.append({
                "kind": "write_file", "path": path, "scope": "project", "content": content,
                "label": "project: gate file -> %s" % path,
            })

    def previous_manifest_files(self) -> set[str]:
        paths: set[str] = set()
        for root in (self.project, self.home):
            manifest = root / ".lean-formalization" / "manifest.json"
            if manifest.is_file():
                try:
                    for entry in json.loads(read_text(manifest))["files"]:
                        paths.add(entry["path"])
                except (json.JSONDecodeError, KeyError):
                    self.warnings.append("unreadable manifest ignored: %s" % manifest)
        return paths

    # ── execution ───────────────────────────────────────────────────────────

    def backup_of(self, path: Path, scope: str) -> Path:
        root = self.backup_root_project if scope == "project" else self.backup_root_user
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", str(path))
        return root / slug

    def record(self, path: Path, scope: str, created: bool, backup: Path | None, label: str,
               keep: bool = False) -> None:
        entry = {
            "path": str(path), "scope": scope, "created": created,
            "backup": str(backup) if backup else None,
            "sha256": sha256_file(path) if path.is_file() else None,
            "label": label, "stamp": self.stamp, "keep": keep,
        }
        (self.manifest_project if scope == "project" else self.manifest_user).append(entry)

    def apply(self, action: dict) -> None:
        kind = action["kind"]
        if self.dry_run:
            print("    + %s" % action["label"])
            return
        path = action.get("path")
        if kind in ("block", "write_file", "json_entry", "toml_table", "copy_tree"):
            if kind == "copy_tree":
                for src in sorted(action["src"].rglob("*")):
                    if src.is_file():
                        rel = src.relative_to(action["src"])
                        self.apply_file(action["dest"] / rel, src.read_bytes(), action)
                return
            if kind == "block":
                new_text = self.compose_block_text(path, action.get("header", ""), action["content"])
                self.apply_file(path, new_text.encode("utf-8"), action)
                return
            if kind == "write_file":
                self.apply_file(path, action["content"].encode("utf-8"), action)
                return
            if kind == "json_entry":
                new_text = self.compose_json_entry(path, action)
                self.apply_file(path, new_text.encode("utf-8"), action)
                return
            if kind == "toml_table":
                if action.get("array_of_tables"):
                    new_text = self.compose_toml_array_table(path, action)
                else:
                    new_text = self.compose_toml_table(path, action)
                self.apply_file(path, new_text.encode("utf-8"), action)
                return
        if kind == "exec":
            printable = " ".join(_quote_for_shell(c) for c in action["cmd"])
            print("    > %s" % printable)
            proc = subprocess.run(action["cmd"], cwd=action["cwd"], capture_output=True, text=True)
            tail = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode != 0:
                self.warnings.append(
                    "native CLI failed (%d): %s\n%s" % (proc.returncode, printable, tail.strip()[:400])
                )
            else:
                self.notes.append("native CLI ok: %s" % printable)
            return
        raise SystemExit("unknown action kind: %s" % kind)

    def apply_file(self, path: Path, data: bytes, action: dict) -> None:
        scope = action.get("scope", "project")
        try:
            if path.is_file() and path.read_bytes() == data:
                print("    = %s (unchanged)" % path)
                self.record(path, scope, created=False, backup=None, label=action["label"],
                            keep=action.get("keep", False))
                return
            created = not path.is_file()
            backup = None
            if not created:
                backup = self.backup_of(path, scope)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            # A denied write (sandbox, read-only mount, another account's file) must
            # be reported as a failed surface, not as a crash halfway through.
            self.failures.append("could not write %s: %s" % (path, exc))
            print("    ! %s (refused: %s)" % (path, exc.strerror or exc))
            return
        print("    %s %s" % ("+" if created else "~", path))
        self.record(path, scope, created=created, backup=backup, label=action["label"],
                    keep=action.get("keep", False))

    # ── text editors ────────────────────────────────────────────────────────

    def compose_block_text(self, path: Path, header: str, block: str) -> str:
        begin = self.spec["contract"]["blockBegin"]
        end = self.spec["contract"]["blockEnd"]
        if not path.is_file():
            return header + block
        existing = read_text(path)
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
        if pattern.search(existing):
            # Replace only the delimited block: whatever the user wrote outside it,
            # and any file-level frontmatter we added the first time, stays put.
            # The replacer is a callable so backslashes in the contract (Windows
            # paths in the injected rules) are inserted literally, not as escapes.
            return pattern.sub(lambda _match: block, existing, count=1)
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + separator + "\n" + block

    def compose_json_entry(self, path: Path, action: dict) -> str:
        doc: dict = {}
        if path.is_file():
            raw = read_text(path)
            try:
                doc = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    "%s is not valid JSON (%s); refusing to rewrite it. Add the MCP entry by hand "
                    "using the snippet in docs/harness-matrix.md." % (path, exc)
                )
        node = doc
        for key in action["key_path"]:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                node[key] = nxt
            node = nxt
        node[action["name"]] = action["entry"]
        self.drop_stale_entries(doc, action.get("cleanup"))
        return json.dumps(doc, indent=2) + "\n"

    def drop_stale_entries(self, doc: dict, cleanup: list[str] | None) -> None:
        """Remove our own server entries from a key path the current shape rejects."""
        if not cleanup:
            return
        parent: dict | None = doc
        for key in cleanup[:-1]:
            nxt = parent.get(key) if isinstance(parent, dict) else None
            parent = nxt if isinstance(nxt, dict) else None
        if parent is None:
            return
        stale = parent.get(cleanup[-1])
        if not isinstance(stale, dict):
            return
        ours = set(self.mcp_servers_to_mount())
        remaining = {key: value for key, value in stale.items() if key not in ours}
        if len(remaining) == len(stale):
            return  # nothing of ours in there; leave the user's config alone
        if remaining:
            parent[cleanup[-1]] = remaining
        else:
            del parent[cleanup[-1]]

    def compose_toml_table(self, path: Path, action: dict) -> str:
        table = action["table"]
        fields = action["fields"]
        block = self.toml_block(table, fields)
        existing = read_text(path) if path.is_file() else ""
        header = re.compile(r"(?m)^\[%s(\..*)?\]\s*$" % re.escape(table))
        match = header.search(existing)
        if not match:
            if not existing:
                return block
            separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
            return existing + separator + "\n" + block
        start = match.start()
        rest = existing[match.end():]
        # The next top-level header that is NOT a sub-table of ours; our own
        # `[<table>.env]` belongs to this block and must be replaced with it.
        end = len(existing)
        for header_match in re.finditer(r"(?m)^\[([^\]]*)\]", rest):
            name = header_match.group(1)
            if name != table and not name.startswith(table + "."):
                end = match.end() + header_match.start()
                break
        return existing[:start] + block + existing[end:]

    def toml_array_block(self, name: str, fields: dict) -> str:
        lines = ["[[%s]]" % name]
        for key, value in fields.items():
            if isinstance(value, dict):
                # An array element cannot carry a sub-table of the same name; Vibe's
                # schema has no env field, so drop it loudly rather than emit a table
                # that would silently attach to the last element.
                if value:
                    self.warnings.append(
                        "[[%s]] entry has env keys that this harness's format cannot express: %s"
                        % (name, ", ".join(value))
                    )
                continue
            if isinstance(value, list):
                lines.append("%s = [%s]" % (key, ", ".join(_toml_scalar(v) for v in value)))
            else:
                lines.append("%s = %s" % (key, _toml_scalar(value)))
        return "\n".join(lines) + "\n\n"

    def compose_toml_array_table(self, path: Path, action: dict) -> str:
        """Replace OUR [[table]] entries (matched by `name`), keep everyone else's."""
        name = action["array_of_tables"]
        entries = action["array_entries"]
        ours = {str(entry.get("name")) for entry in entries}
        header = "[[%s]]" % name
        lines = read_text(path).splitlines(keepends=True) if path.is_file() else []
        kept: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.strip() == header:
                chunk = [line]
                index += 1
                while index < len(lines) and not lines[index].lstrip().startswith("["):
                    chunk.append(lines[index])
                    index += 1
                body = "".join(chunk)
                block_name = re.search(r'(?m)^\s*name\s*=\s*"([^"]*)"\s*$', body)
                if block_name and block_name.group(1) in ours:
                    continue  # ours: replaced below
                kept.append(body)
                continue
            kept.append(line)
            index += 1
        text = "".join(kept)
        # Vibe's own documentation asks for a bare `mcp_servers = []` to be removed
        # before the first table is added.
        text = re.sub(r"(?m)^%s\s*=\s*\[\s*\]\s*\n" % re.escape(name), "", text)
        if text and not text.endswith("\n"):
            text += "\n"
        if text.strip():
            text += "\n"
        return text + "".join(self.toml_array_block(name, entry) for entry in entries)

    def toml_block(self, table: str, fields: dict) -> str:
        lines = ["[%s]" % table]
        for key, value in fields.items():
            if isinstance(value, dict):
                continue
            if isinstance(value, list):
                lines.append("%s = [%s]" % (key, ", ".join(_toml_scalar(v) for v in value)))
            else:
                lines.append("%s = %s" % (key, _toml_scalar(value)))
        for key, value in fields.items():
            if isinstance(value, dict) and value:
                lines.append("")
                lines.append("[%s.%s]" % (table, key))
                for k2, v2 in value.items():
                    lines.append("%s = %s" % (k2, _toml_scalar(v2)))
        return "\n".join(lines) + "\n\n"

    # ── manifest / report ───────────────────────────────────────────────────

    def write_manifests(self) -> None:
        if self.dry_run:
            return
        for scope, entries in (("project", self.manifest_project), ("user", self.manifest_user)):
            if not entries:
                continue
            root = (self.project if scope == "project" else self.home) / ".lean-formalization"
            manifest_path = root / "manifest.json"
            previous = {}
            previous_stamp = self.stamp
            if manifest_path.is_file():
                try:
                    loaded = json.loads(read_text(manifest_path))
                    for old in loaded["files"]:
                        previous[old["path"]] = old
                    previous_stamp = loaded.get("stamp") or self.stamp
                except (json.JSONDecodeError, KeyError):
                    self.warnings.append("previous manifest was unreadable; it is replaced, not merged")
            for entry in entries:
                old = previous.get(entry["path"])
                if old is None:
                    previous[entry["path"]] = entry
                    continue
                # Keep what the FIRST run learned about a path: whether we created
                # it, where its original content was saved, and when. Later runs see
                # an already-matching file and would otherwise erase that knowledge —
                # and a fresh timestamp every run would make the file change even when
                # nothing did.
                merged = dict(entry)
                merged["created"] = bool(old.get("created"))
                merged["backup"] = old.get("backup") or entry.get("backup")
                merged["keep"] = bool(old.get("keep") or entry.get("keep"))
                merged["stamp"] = old.get("stamp", entry["stamp"])
                previous[entry["path"]] = merged
            payload = json.dumps(
                {
                    "tool": TAG,
                    "stamp": previous_stamp,
                    "scope": scope,
                    "uninstall": "python install/install.py --uninstall",
                    "files": sorted(previous.values(), key=lambda e: e["path"]),
                },
                indent=2,
            ) + "\n"
            if manifest_path.is_file() and read_text(manifest_path) == payload:
                # Nothing changed: leave the file untouched so that "a second run
                # writes nothing" is true at byte level, not just in spirit.
                print("    = %s (unchanged)" % manifest_path)
                continue
            write_text(manifest_path, payload)

    def report(self, chosen: list[str]) -> None:
        print("")
        print("mode            : %s%s" % (
            "beam" if self.beam_mode else "lsp-fallback",
            (" (Beam at %s)" % self.beam["how"]) if self.beam_mode else "",
        ))
        print("project         : %s%s" % (self.project, "" if self.lean_project else "  (not a Lean project: user scope only)"))
        print("harnesses       : %s" % (", ".join(chosen) if chosen else "(none)"))
        if self.skipped:
            print("not detected    : %s" % ", ".join(sorted(self.skipped)))
        print("prereqs         : %s" % self.prereq_line())
        if self.notes:
            print("")
            for note in self.notes:
                print("note    : %s" % note)
        for warning in self.warnings:
            print("warning : %s" % warning)
        for failure in self.failures:
            print("FAILED  : %s" % failure)

    def prereq_line(self) -> str:
        parts = []
        for probe in self.spec["mcp"]["servers"]["lean-lsp"]["prereqs"]:
            found = shutil.which(probe["command"])
            if probe["required"]:
                parts.append("%s=%s" % (probe["command"], "ok" if found else "MISSING (required)"))
            elif not found:
                parts.append("%s=missing (%s)" % (probe["command"], probe["why"]))
        return ", ".join(parts)


def _quote_for_shell(token: str) -> str:
    return '"%s"' % token if " " in token else token


def _toml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./-]+", text):
        return '"%s"' % text
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


# ─────────────────────────────────────────────────────────────────────────────
# subcommands


def cmd_install(args: argparse.Namespace) -> int:
    installer = Installer(args)
    chosen = installer.select_harnesses()
    installer.detected = chosen

    print("%s installer" % TAG)
    print("repo            : %s" % installer.repo)
    print("home            : %s" % installer.home)
    print("agents home     : %s" % installer.agents_home)
    print("dsh home        : %s" % installer.dsh_home)
    print("scope           : %s" % args.scope)
    print("dry run         : %s" % installer.dry_run)
    print("")

    for hid in chosen:
        installer.plan_harness(hid)
    installer.plan_dsh()
    installer.plan_project()

    if not installer.actions:
        print("nothing to do: no harness selected and no Lean project to configure")
        installer.report(chosen)
        return 3

    current_group = None
    ordered = sorted(installer.actions, key=lambda a: 0 if a.get("scope") == "project" else 1)
    for action in ordered:
        group = action.get("scope", "?")
        if group != current_group:
            print("[%s scope]" % group)
            current_group = group
        installer.apply(action)

    installer.write_manifests()
    installer.report(chosen)
    if installer.dry_run:
        print("")
        print("dry run: nothing was written. Re-run without --dry-run to apply.")
    elif installer.failures:
        print("")
        print("install finished with %d refused write(s); see FAILED lines above" % len(installer.failures))
        return 1
    else:
        print("")
        print("next: restart the harnesses you use (or start a new session), then verify with")
        print("      python verify/probe_mcp.py --harnesses --project .   (add --env UV_CACHE_DIR=… in a sandbox)")
        if "dsh" in chosen:
            print("      %s" % installer.dsh_bundle_command())
            print("      dsh --profile <profile> --dump-config   (confirm preset-lean appears)")
        print("uninstall: python install/install.py --uninstall")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser().resolve() if args.home else Path.home().resolve()
    project = Path(args.project).expanduser().resolve()
    removed, restored, problems, kept = [], [], [], []
    for scope, root in (("project", project), ("user", home)):
        manifest_path = root / ".lean-formalization" / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(read_text(manifest_path))
        for entry in reversed(manifest["files"]):
            path = Path(entry["path"])
            if entry.get("keep"):
                kept.append(str(path))
                continue
            if entry.get("backup") and Path(entry["backup"]).is_file():
                if not args.dry_run:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry["backup"], path)
                restored.append(str(path))
            elif entry.get("created"):
                if path.is_file():
                    if entry.get("sha256") and sha256_file(path) != entry["sha256"]:
                        # Someone edited a file we created. Deleting it would destroy
                        # their work, so uninstall says so and stops there.
                        problems.append(
                            "edited since install, left in place: %s (remove it yourself if you mean to)" % path
                        )
                        continue
                    if not args.dry_run:
                        path.unlink()
                    removed.append(str(path))
            else:
                problems.append("no backup for a modified file, left in place: %s" % path)
        if not args.dry_run:
            manifest_path.unlink()
    for line in removed:
        print("removed : %s" % line)
    for line in restored:
        print("restored: %s" % line)
    for line in problems:
        print("warning : %s" % line)
    for line in kept:
        print("kept    : %s (project config, not ours to delete)" % line)
    print("")
    print("uninstall %s: %d removed, %d restored, %d kept, %d needs a manual look"
          % ("(dry run) " if args.dry_run else "", len(removed), len(restored), len(kept), len(problems)))
    print("backups stay under <project>/.lean-formalization/backups/ and ~/.lean-formalization/backups/")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    installer = Installer(args)
    spec = installer.spec
    print("%s doctor" % TAG)
    print("home            : %s" % installer.home)
    print("project         : %s%s" % (installer.project, "" if installer.lean_project else "  (not a Lean project)"))
    print("mcp mode        : %s" % ("beam" if installer.beam_mode else "lsp-fallback"))
    if installer.beam:
        print("beam launcher   : %s" % installer.beam["how"])
    print("prereqs         : %s" % installer.prereq_line())
    print("")
    print("%-16s %-8s %-10s %-9s %-9s %s" % ("harness", "tier", "detected", "block", "skills", "mcp configured"))
    problems = 0
    for hid, h in spec["harnesses"].items():
        detected = installer.harness_detected(h)
        block_ok = skills_ok = mcp_ok = "-"
        method = h.get("mcp", {}).get("method")
        targets = [t for t in h.get("instructions", []) if t.get("method") not in ("dsh-preset", "dsh-bundle")]
        if targets:
            present = [
                t for t in targets
                if installer.expand(t["path"], t["scope"]).is_file()
                and spec["contract"]["blockBegin"] in read_text(installer.expand(t["path"], t["scope"]))
            ]
            block_ok = "%d/%d" % (len(present), len(targets))
        roots = [installer.expand(r["path"], r["scope"]) for r in h.get("skillRoots", [])]
        if roots:
            installed = [r for r in roots if (r / "lean-formalization" / "SKILL.md").is_file()]
            skills_ok = "%d/%d" % (len(installed), len(roots))
        if method in ("dsh-preset", "dsh-bundle"):
            bundle = installer.repo / "preset"
            patch_path = bundle / "cordis.patch.yml"
            beam_bundle = patch_path.is_file() and "MCP mode: beam." in read_text(patch_path)
            active_skills = ["lean-formalization", "lean-beam"] if beam_bundle else ["lean-formalization"]
            present = sum((bundle / "skills" / skill / "SKILL.md").is_file() for skill in active_skills)
            skills_ok = "%d/%d" % (present, len(active_skills))
        if method in ("file-json", "file-toml"):
            mcp_targets = h["mcp"].get("targets") or [{"path": h["mcp"].get("target")}]
            hits = 0
            for t in mcp_targets:
                p = installer.expand(t["path"], t.get("scope", "user"))
                if p.is_file() and "lean-lsp" in read_text(p):
                    hits += 1
            mcp_ok = "%d/%d" % (hits, len(mcp_targets))
        elif method in ("dsh-preset", "dsh-bundle"):
            bundle = installer.repo / "preset"
            if not (bundle / "package.json").is_file() or not (bundle / "cordis.patch.yml").is_file():
                mcp_ok = "missing"
            else:
                installed = False
                profiles = installer.dsh_home / "profiles"
                package_name = "@local/dsh-lean-preset"
                try:
                    package_name = json.loads(read_text(bundle / "package.json")).get("name") or package_name
                except (json.JSONDecodeError, OSError):
                    pass
                if profiles.is_dir():
                    for profile in profiles.iterdir():
                        pkg = profile / "package.json"
                        if not pkg.is_file():
                            continue
                        try:
                            doc = json.loads(read_text(pkg))
                            bundles = ((doc.get("dsh") or {}).get("profile") or {}).get("bundles") or []
                            if package_name in bundles:
                                installed = True
                                break
                        except (json.JSONDecodeError, OSError):
                            continue
                mcp_ok = "installed" if installed else "bundle-ready"
        if detected and block_ok.startswith("0/"):
            problems += 1
        print("%-16s %-8s %-10s %-9s %-9s %s" % (hid, h.get("tier", 2), detected, block_ok, skills_ok, mcp_ok))
    print("")
    print("note: a freshly written config only takes effect after the harness restarts "
          "(see docs/harness-matrix.md for each harness's reload rule).")
    return 1 if (args.strict and problems) else 0


# ─────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the Lean formalization assistant into the harnesses detected on this machine.",
    )
    parser.add_argument("--project", default=".", help="target Lean project root (default: current directory)")
    parser.add_argument("--scope", choices=["project", "user", "both"], default="both")
    parser.add_argument("--home", default=None, help="override the home directory (used by tests)")
    parser.add_argument("--dsh-home", default=None, help="override DSH_HOME")
    parser.add_argument("--agents-home", default=None, help="override the shared agents home (default ~/.agents)")
    parser.add_argument("--harnesses", default=None, help="comma-separated harness ids to force")
    parser.add_argument("--include-unverified", action="store_true",
                        help="also write harnesses whose config paths were not verified on this machine")
    parser.add_argument("--no-project-gate", action="store_true",
                        help="do not scaffold LeanAudit.lean / leancheck / evidence into the project")
    parser.add_argument("--no-mcp", action="store_true", help="skip every MCP server write")
    parser.add_argument("--uv-cache-dir", default=None)
    parser.add_argument("--uv-tool-dir", default=None)
    parser.add_argument("--opencode-major", default=None, choices=["1", "2"],
                        help="force the OpenCode MCP config shape instead of probing `opencode --version`")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--strict", action="store_true", help="with --doctor: exit 1 when a detected harness is unconfigured")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (SPEC_PATH.is_file()):
        print("install.py: %s is missing; run this from inside the repository" % SPEC_PATH, file=sys.stderr)
        return 2
    if args.scope in ("project", "both") and not args.uninstall and not args.doctor:
        project = Path(args.project).expanduser().resolve()
        looks_lean = (project / "lean-toolchain").is_file()
        if not looks_lean and args.scope == "project":
            print(
                "install.py: %s is not a Lean project (no lean-toolchain); "
                "use --scope user for a machine-wide install" % project,
                file=sys.stderr,
            )
            return 2
    if args.uninstall:
        return cmd_uninstall(args)
    if args.doctor:
        return cmd_doctor(args)
    return cmd_install(args)


if __name__ == "__main__":
    raise SystemExit(main())
