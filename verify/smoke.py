#!/usr/bin/env python3
"""Deterministic self-test for this repository.

Runs the installer into throwaway directories — never the real home or a real
project — and asserts the properties the repository claims:

  1. install writes the contract block, the owned skills, the MCP entries and the
     gate scaffold, and every JSON/TOML file it touched still parses;
  2. a second install writes nothing (idempotence);
  3. user text outside the delimited block survives a re-install;
  4. uninstall removes what it created, restores what it changed, and leaves the
     project's own config alone;
  5. with --with-gate, the scaffolded gate script really runs: it refuses an empty
     target list, and passes on a project whose axioms are inside the whitelist.

Usage:
    python verify/smoke.py [--work DIR] [--with-gate] [--json]

Exit codes: 0 all checks passed, 1 a check failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BLOCK_BEGIN = "<!-- lean-formalization:begin v1 -->"
BLOCK_END = "<!-- lean-formalization:end -->"


class Checker:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print("%-4s %s%s" % ("PASS" if ok else "FAIL", name, ("  — " + detail) if detail else ""))
        return bool(ok)

    def skip(self, name: str, detail: str = "") -> None:
        """A surface that does not apply here is skipped, never silently passed."""
        self.results.append({"check": name, "ok": True, "skipped": True, "detail": detail})
        print("%-4s %s%s" % ("SKIP", name, ("  — " + detail) if detail else ""))

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r["ok"])

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.get("skipped"))


def child_env(home: Path | None = None) -> dict:
    """Environment for installer children.

    With `home`, the DSH variables are pinned to the fixture: whether the DSH row
    is detected must be decided by the fixture, not by whoever happens to run the
    test (the authoring machine exports DSH_HOME globally, which once made this
    suite pass while a clean shell failed two checks).
    """
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if home is not None:
        env["DSH_HOME"] = str(home / "dsh-home")
        env["DSH_AGENTS_HOME"] = str(home / ".agents")
    return env


def run_installer(*args: str, cwd: Path | None = None, home: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "install" / "install.py"), *args],
        cwd=str(cwd or REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=child_env(home),
    )


def selected_harnesses(installer_output: str) -> list[str] | None:
    """The installer's own report of what it configured.

    Returns None when the report line is missing, so the caller can fail instead
    of treating an unparsable run as "no surfaces to check".
    """
    match = re.search(r"^harnesses\s*:\s*(.+)$", installer_output, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip()
    if value in ("", "(none)"):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def expand_surface(raw: str, project: Path, home: Path, dsh_home: Path,
                   agents_home: Path, scope: str) -> Path:
    """Mirror install/install.py's expand() for a harness surface path."""
    text = str(raw)
    text = text.replace("<project>", str(project))
    text = text.replace("<repo>", str(REPO))
    text = text.replace("<DSH_HOME>", str(dsh_home))
    text = text.replace("<DSH_AGENTS_HOME or ~/.agents>", str(agents_home))
    text = text.replace("<DSH_AGENTS_HOME>", str(agents_home))
    if text.startswith("~/"):
        text = str(home) + text[1:]
    text = os.path.expandvars(text)
    path = Path(text)
    if not path.is_absolute():
        path = (project if scope == "project" else home) / path
    return path


def expected_install_files(spec: dict, chosen: list[str], project: Path, home: Path,
                           dsh_home: Path, agents_home: Path) -> list[Path]:
    """Files the installer promises for exactly the harnesses it reported.

    Derived from harnesses.json (the single source of truth) instead of a
    hard-coded union, so a harness that is not detected contributes no
    requirements. Gate-scaffold files are harness-independent.
    """
    expected: set[Path] = {
        project / "lean-formalization.json",
        project / "LeanAudit.lean",
        project / "LeanScan.lean",
        project / "scripts" / "leancheck.ps1",
        project / ".lean-formalization" / "manifest.json",
    }
    owned_skills = spec.get("skills", {}).get("owned", [])
    for hid in chosen:
        harness = spec.get("harnesses", {}).get(hid)
        if harness is None:
            continue
        for target in harness.get("instructions", []):
            if target.get("method") in ("dsh-preset", "dsh-bundle"):
                continue
            if target.get("scope") not in ("project", "user") or not target.get("path"):
                continue
            expected.add(expand_surface(target["path"], project, home, dsh_home,
                                        agents_home, target["scope"]))
        for root in harness.get("skillRoots", []):
            if root.get("scope") not in ("project", "user") or not root.get("path"):
                continue
            base = expand_surface(root["path"], project, home, dsh_home, agents_home, root["scope"])
            for skill in owned_skills:
                expected.add(base / skill / "SKILL.md")
        mcp = harness.get("mcp", {})
        if mcp.get("method") not in ("file-json", "file-toml"):
            continue
        targets = mcp.get("targets") or [{"scope": "project", "path": mcp.get("target")}]
        for target in targets:
            scope = target.get("scope", "project")
            if scope not in ("project", "user") or not target.get("path"):
                continue
            path = expand_surface(target["path"], project, home, dsh_home, agents_home, scope)
            if mcp.get("method") == "file-json" and (
                path.suffix == ".jsonc" or (not path.exists() and path.with_suffix(".jsonc").exists())
            ):
                continue  # the installer refuses to edit a JSONC config
            expected.add(path)
    return sorted(expected, key=str)


def make_fixture(root: Path) -> Path:
    project = root / "FixtureProj"
    (project / "FixtureProj").mkdir(parents=True, exist_ok=True)
    # Use a toolchain already installed on the host. CI can pin an explicit
    # version with LEAN_SMOKE_TOOLCHAIN; local smoke must not reach the network
    # merely to download an arbitrary fixture version.
    toolchain = os.environ.get("LEAN_SMOKE_TOOLCHAIN", "").strip()
    if not toolchain:
        try:
            probe = subprocess.run(["elan", "show"], capture_output=True, text=True,
                                   timeout=30, encoding="utf-8", errors="replace")
            match = re.search(r"active toolchain\s*-+\s*\n([^\s]+)", probe.stdout or "")
            toolchain = match.group(1) if match else "leanprover/lean4:v4.21.0"
        except (OSError, subprocess.SubprocessError):
            toolchain = "leanprover/lean4:v4.21.0"
    (project / "lean-toolchain").write_text(toolchain + "\n", encoding="utf-8")
    (project / "lakefile.toml").write_text(
        'name = "fixture-package"\ndefaultTargets = ["FixtureProj"]\n\n[[lean_lib]]\nname = "FixtureProj"\n',
        encoding="utf-8",
    )
    (project / "FixtureProj.lean").write_text("import FixtureProj.Basic\n", encoding="utf-8")
    (project / "FixtureProj" / "Basic.lean").write_text(
        "namespace FixtureProj\n\n"
        "theorem trivial_eq (a b : Nat) : a + b = b + a := Nat.add_comm a b\n\n"
        "theorem uses_classical (p : Prop) : p ∨ ¬p := Classical.em p\n\n"
        "end FixtureProj\n",
        encoding="utf-8",
    )
    # A pre-existing instruction file with the user's own prose around the block.
    (project / "AGENTS.md").write_text(
        "# FixtureProj\n\nMy own project notes that must survive.\n", encoding="utf-8"
    )
    return project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smoke.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", default=None, help="scratch root (default: <repo>/.smoke)")
    parser.add_argument("--with-gate", action="store_true", help="also build and run the scaffolded gate")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    args = parser.parse_args(argv)

    work = Path(args.work).resolve() if args.work else REPO / ".smoke"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    home = work / "home"
    home.mkdir()
    # The DSH detect rule is `env: DSH_HOME` or `paths: ~/.dsh`; the fixture must
    # satisfy it itself (child_env pins the env, this satisfies the path).
    (home / ".dsh").mkdir()
    project = make_fixture(work)
    checker = Checker()

    dsh_home = home / "dsh-home"
    agents_home = home / ".agents"
    common = ["--project", str(project), "--home", str(home),
              "--dsh-home", str(dsh_home), "--agents-home", str(agents_home)]
    spec = json.loads((REPO / "harnesses.json").read_text(encoding="utf-8"))

    # ── 1. install ──────────────────────────────────────────────────────────
    first = run_installer(*common, "--scope", "both", home=home)
    checker.check("install exits 0", first.returncode == 0, first.stdout.strip().splitlines()[-1] if first.stdout else "")

    # The fixture home is pinned, so harness detection here is the installer's
    # own answer (commands on PATH plus marker paths under the fixture home).
    # Surfaces are required only for the harnesses it actually configured.
    chosen = selected_harnesses(first.stdout)
    checker.check("installer reported the harnesses it configured", chosen is not None,
                  "missing 'harnesses : ...' report line" if chosen is None else "")
    chosen = chosen or []
    for hid, harness in spec.get("harnesses", {}).items():
        if harness.get("tier") == 1 and hid not in chosen:
            checker.skip("harness %s surfaces" % hid,
                         "not detected in the fixture; its files are not required")

    expected_files = expected_install_files(spec, chosen, project, home, dsh_home, agents_home)
    missing = [str(p.relative_to(work)) for p in expected_files if not p.is_file()]
    checker.check("every expected file exists for the detected harnesses", not missing,
                  ", ".join(missing))

    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    checker.check("contract block present exactly once",
                  agents.count(BLOCK_BEGIN) == 1 and agents.count(BLOCK_END) == 1)
    checker.check("user prose outside the block survives",
                  "My own project notes that must survive." in agents)
    checker.check("contract carries the non-negotiables",
                  "Non-negotiables" in agents and "never the acceptance authority" in agents.split("Non-negotiables")[1])

    # every config file we touched must still parse
    parse_failures = []
    for path in [home / ".gemini" / "settings.json", home / ".cursor" / "mcp.json",
                 home / ".config" / "opencode" / "opencode.json", project / ".mcp.json",
                 project / ".vscode" / "mcp.json", project / "lean-formalization.json",
                 project / ".lean-formalization" / "manifest.json"]:
        if not path.is_file():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            parse_failures.append("%s: %s" % (path.name, exc))
    codex_config = home / ".codex" / "config.toml"
    if codex_config.is_file():
        try:
            toml = tomllib.loads(codex_config.read_text(encoding="utf-8"))
            if "lean-lsp" not in toml.get("mcp_servers", {}):
                parse_failures.append("codex config.toml has no [mcp_servers.lean-lsp]")
        except tomllib.TOMLDecodeError as exc:
            parse_failures.append("codex config.toml: %s" % exc)
    checker.check("every config file still parses", not parse_failures, "; ".join(parse_failures))

    # OpenCode 1.x and 2.x take different (mutually rejected) MCP config shapes, so
    # the written shape must match the installed major.
    opencode_json = home / ".config" / "opencode" / "opencode.json"
    if opencode_json.is_file():
        doc = json.loads(opencode_json.read_text(encoding="utf-8"))
        mcp = doc.get("mcp", {})
        major = None
        if shutil.which("opencode"):
            try:
                probe = subprocess.run(["opencode", "--version"], capture_output=True, text=True,
                                       timeout=30, encoding="utf-8", errors="replace")
                match = re.search(r"(\d+)\.", (probe.stdout or "") + (probe.stderr or ""))
                major = match.group(1) if match else None
            except (OSError, subprocess.SubprocessError):
                major = None
        if major == "1":
            good = "lean-lsp" in mcp and "servers" not in mcp
        elif major == "2":
            good = "lean-lsp" in mcp.get("servers", {})
        else:
            good = "lean-lsp" in mcp or "lean-lsp" in mcp.get("servers", {})
        checker.check("opencode config shape matches the installed major (%s)" % (major or "undetected"),
                      good, json.dumps(mcp)[:120])

    # Current DSH installs the preset as a profile bundle.  The installer must
    # not recreate the retired `$DSH_HOME/.agent-presets/lean/` tree; it reports
    # the profile command and leaves profile selection to the user.
    bundle = REPO / "preset"
    manifest = json.loads((bundle / "package.json").read_text(encoding="utf-8"))
    checker.check(
        "DSH bundle manifest is installable",
        manifest.get("main") == "index.js"
        and manifest.get("dsh", {}).get("bundle", {}).get("patch") == "./cordis.patch.yml"
        and manifest.get("exports", {}).get("./package.json") == "./package.json"
        and "skills/**" in manifest.get("files", [])
        and (bundle / "cordis.patch.yml").is_file()
        and (bundle / "skills" / "lean-formalization" / "SKILL.md").is_file()
        and "id: preset-lean" in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        and "name: '@deepseek-ai/dsh-agent-preset'" in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        and "id: mcp-lean-lsp" in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        # Runtime-module anchoring works for both the public root package and
        # a linked preset/ subdirectory; check_public_package exercises both.
        and "createRequire(baseUrl).resolve('@local/dsh-lean-preset')" in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        and "failOnStartupError: true" in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        and "failOnStartupError: false" not in (bundle / "cordis.patch.yml").read_text(encoding="utf-8")
        and "dsh plugin --profile <profile> add" in first.stdout,
    )
    legacy = home / "dsh-home" / ".agent-presets" / "lean"
    checker.check("DSH installer does not write the retired preset path", not legacy.exists())
    project_cfg = json.loads((project / "lean-formalization.json").read_text(encoding="utf-8"))
    checker.check("library scan uses the Lean library name, not the package name",
                  project_cfg.get("library") == "FixtureProj"
                  and project_cfg.get("ownModulePrefixes") == ["FixtureProj"]
                  and project_cfg.get("scanScript") == "LeanScan.lean")

    # ── 2. idempotence ──────────────────────────────────────────────────────
    manifests = [project / ".lean-formalization" / "manifest.json",
                 home / ".lean-formalization" / "manifest.json"]
    before = {p: (p.read_bytes() if p.is_file() else None) for p in manifests}
    second = run_installer(*common, "--scope", "both", home=home)
    writes = [l for l in second.stdout.splitlines() if l.startswith("    +") or l.startswith("    ~")]
    checker.check("second install writes nothing", second.returncode == 0 and not writes,
                  "; ".join(writes[:3]))
    # Bytes, not just the "+/~" lines: the manifests used to be rewritten every run.
    changed = [p.name for p in manifests
               if (p.read_bytes() if p.is_file() else None) != before[p]]
    checker.check("second install leaves every file byte-identical", not changed,
                  ", ".join(changed))

    # ── 3. uninstall ────────────────────────────────────────────────────────
    # The user edits a file the installer created; uninstall must not delete it.
    edited = project / "CLAUDE.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nmy own addition\n", encoding="utf-8")

    uninstall = run_installer("--project", str(project), "--home", str(home), "--uninstall", home=home)
    leftover = [str(p.relative_to(work)) for p in
                [project / ".mcp.json", project / "LeanAudit.lean",
                 project / ".github" / "copilot-instructions.md",
                 home / ".codex" / "config.toml", home / ".cursor" / "mcp.json"]
                if p.exists()]
    checker.check("uninstall removes what it created", uninstall.returncode == 0 and not leftover,
                  ", ".join(leftover))
    # AGENTS.md pre-existed, so uninstall must restore it without our block.
    restored = (project / "AGENTS.md").read_text(encoding="utf-8") if (project / "AGENTS.md").is_file() else ""
    checker.check("uninstall restores a pre-existing file without the block",
                  "My own project notes that must survive." in restored and BLOCK_BEGIN not in restored)
    checker.check("uninstall leaves the project config alone",
                  (project / "lean-formalization.json").is_file())
    checker.check("a file the user edited is left in place, not deleted",
                  edited.is_file() and "edited since install" in uninstall.stdout)

    # ── 4. optionally: the scaffolded gate really runs ──────────────────────
    if args.with_gate:
        gate = run_installer(*common, "--scope", "project", home=home)
        if gate.returncode != 0:
            checker.check("re-install for the gate check", False, gate.stderr.strip()[:200])
        else:
            empty = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1")],
                cwd=str(project), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            checker.check("gate refuses an empty target list (exit 2)", empty.returncode == 2,
                          empty.stdout.strip().splitlines()[-1] if empty.stdout else "")
            cfg_path = project / "lean-formalization.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["targets"] = ["FixtureProj.trivial_eq", "FixtureProj.uses_classical"]
            cfg["entryModules"] = ["FixtureProj"]
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            lock = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1"), "-Lock"],
                cwd=str(project), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            lock_path = project / "locked-targets.json"
            checker.check(
                "gate writes a reviewed statement lock",
                lock.returncode == 0 and lock_path.is_file(),
                lock.stdout.strip().splitlines()[-1] if lock.stdout else "",
            )
            good = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1")],
                cwd=str(project), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            checker.check("gate passes a whitelisted project (exit 0)", good.returncode == 0,
                          good.stdout.strip().splitlines()[-1] if good.stdout else "")
            scan_runs = sorted((project / "evidence" / "lean" / "runs").glob("*"))
            scan_report = json.loads((scan_runs[-1] / "report.json").read_text(encoding="utf-8"))
            checker.check("gate actually scans library declarations",
                          scan_report.get("scanRan") is True and scan_report.get("scannedDeclarations", 0) >= 2)
            basic = project / "FixtureProj" / "Basic.lean"
            original = basic.read_text(encoding="utf-8")
            basic.write_text(original + "\nnamespace FixtureProj\ntheorem unused_hole : True := by sorry\nend FixtureProj\n", encoding="utf-8")
            hollow = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1")],
                cwd=str(project), capture_output=True, text=True, encoding="utf-8", errors="replace")
            checker.check("library scan rejects a sorry outside the audited targets",
                          hollow.returncode == 1 and "FixtureProj.unused_hole" in hollow.stdout)
            basic.write_text(original, encoding="utf-8")
            bad = json.loads(cfg_path.read_text(encoding="utf-8"))
            bad["allowedAxioms"] = []
            (project / "lean-formalization.json").write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
            strict = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1")],
                cwd=str(project), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            checker.check("gate fails a whitelist violation (exit 1)", strict.returncode == 1,
                          " ".join(strict.stdout.strip().splitlines()[-1:]))

            # A step whose command cannot be resolved used to terminate the gate
            # before any evidence was written, leaving an empty run directory and a
            # stale LATEST.md. The gate must still produce a full failure record.
            nolake = json.loads(cfg_path.read_text(encoding="utf-8"))
            nolake["lakeCommand"] = "definitely-not-a-real-command"
            cfg_path.write_text(json.dumps(nolake, indent=2) + "\n", encoding="utf-8")
            unres = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(project / "scripts" / "leancheck.ps1"), "-NoBuild"],
                cwd=str(project), capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=child_env(home),
            )
            runs = sorted((project / "evidence" / "lean" / "runs").glob("*"), key=lambda p: p.name)
            newest = runs[-1] if runs else None
            evidence_ok = bool(newest) and (newest / "command-axiom-audit.log").is_file() \
                and (newest / "report.json").is_file()
            if evidence_ok:
                record = json.loads((newest / "report.json").read_text(encoding="utf-8"))
                evidence_ok = record.get("ok") is False
            checker.check("gate with an unresolvable command still writes evidence",
                          unres.returncode == 1 and evidence_ok,
                          "exit %d, newest run %s" % (unres.returncode, newest.name if newest else "none"))

    if args.json:
        print(json.dumps({"work": str(work), "results": checker.results,
                          "failed": checker.failed, "skipped": checker.skipped}, indent=2))
    print("")
    print("smoke: %d checks, %d failed, %d skipped" % (
        len(checker.results), checker.failed, checker.skipped))
    print("scratch tree left at %s" % work)
    return 1 if checker.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
