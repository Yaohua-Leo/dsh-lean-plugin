#!/usr/bin/env python3
"""Static + functional check of the POSIX gate's embedded Python.

`gate/leancheck.sh` cannot be executed on the authoring machine (Git Bash cannot
create its signal pipe under the sandbox), so this script checks what can be
checked without a shell:

  1. every `<<'PY' ... PY` heredoc in the script parses as Python (a syntax error
     there makes the gate exit 2 on every invocation — it happened once);
  2. the config-reading heredoc actually runs and emits the shell assignments the
     script consumes;
  3. the whitelist heredoc actually enforces the whitelist when invoked with the
     same protocol as `gate/leancheck.sh`: 9 positionals, then the step names,
     codes, seconds, allowed axioms and targets separated by `--`; it exits 0 for
     a whitelisted target, non-zero for an axiom outside it, non-zero for a
     missing target and non-zero for a changed locked statement, and writes
     `report.json`, `report.md` and `LATEST.md`;
  4. the Python discovery block rejects a fake WindowsApps Store placeholder and
     selects the next real interpreter, or fails with the expected diagnostic
     when no real interpreter exists.

It does NOT prove the surrounding shell logic runs — only a real bash could.

Usage: python verify/check_gate_shell.py   (exit 0 ok, 1 a check failed)
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "gate" / "leancheck.sh"
HEREDOC = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.DOTALL)


DISCOVERY = re.compile(r"# >>> python-discovery\n(.*?)\n# <<< python-discovery", re.DOTALL)
WINDOWSAPPS_STUB = r"C:\Users\Leo\AppData\Local\Microsoft\WindowsApps\python3.exe"


def bash_runs_windows_script(bash: str, probe_root: Path) -> bool:
    """True when this bash can execute a script at a normal Windows path."""
    probe = probe_root / "bash-probe.sh"
    probe.write_text("#!/usr/bin/env bash\nprintf 'BASH_PROBE_OK\\n'\n",
                     encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [bash, str(probe).replace(chr(92), "/")],
            capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "BASH_PROBE_OK" in result.stdout


def find_bash_for_tests() -> str | None:
    """Find a native bash that can run Windows-path scripts.

    On Windows `shutil.which("bash")` may return C:\\Windows\\System32\\bash.exe
    (the WSL entry point) or the WindowsApps alias, both of which fail on a
    Windows temporary path. Prefer Git Bash from its normal install roots, then
    from PATH, and reject System32/WindowsApps entries. The selected binary must
    pass a small script execution probe.
    """
    if os.name != "nt":
        return shutil.which("bash")

    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / "Git")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "Programs" / "Git")

    git = shutil.which("git")
    if git:
        git_path = Path(git)
        # Typical: <Git>\cmd\git.exe or <Git>\bin\git.exe.
        roots.append(git_path.parent.parent if git_path.parent.name.lower() in ("cmd", "bin")
                     else git_path.parent)

    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "bin" / "bash.exe")
        candidates.append(root / "usr" / "bin" / "bash.exe")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry) / "bash.exe")

    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="lf-bash-probe-") as tmp:
        probe_root = Path(tmp)
        for candidate in candidates:
            key = os.path.normcase(os.path.abspath(candidate))
            if key in seen:
                continue
            seen.add(key)
            normalized = str(candidate).replace("/", "\\").lower()
            if ("\\windows\\system32\\" in normalized
                    or "\\microsoft\\windowsapps\\" in normalized):
                continue
            if not candidate.is_file():
                continue
            if bash_runs_windows_script(str(candidate), probe_root):
                return str(candidate)
    return None


def write_exe(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    os.chmod(path, 0o755)


def check_python_discovery(source: str) -> list[str]:
    """Exercise the real discovery block with fake PATH entries.

    The block is extracted from gate/leancheck.sh (not copied), so this tests the
    shipped logic: a WindowsApps placeholder must be rejected and the next real
    interpreter used; with no real interpreter the script must fail clearly.
    """
    failures: list[str] = []
    match = DISCOVERY.search(source)
    if match is None:
        return ["python discovery markers are missing from gate/leancheck.sh"]
    bash = find_bash_for_tests()
    if bash is None:
        print("SKIP interpreter discovery (no native bash that can run Windows paths)")
        return failures
    print("bash used by interpreter-discovery tests: %s" % bash)

    real_python = sys.executable.replace(chr(92), "/")
    real = "#!/bin/sh\nexec %s \"$@\"\n" % shlex.quote(real_python)
    stub = "#!/bin/sh\nprintf '%s\\n' '" + WINDOWSAPPS_STUB + "'\nexit 0\n"
    py_launcher = ("#!/bin/sh\n[ \"$1\" = \"-3\" ] || exit 2\nshift\n"
                   "exec %s \"$@\"\n" % shlex.quote(real_python))

    with tempfile.TemporaryDirectory(prefix="lf-py-detect-") as tmp:
        root = Path(tmp)
        resolver = root / "resolver.sh"
        resolver.write_text(
            "#!/usr/bin/env bash\nset -uo pipefail\n" + match.group(1)
            + "\nprintf 'CHOSEN=%s\\n' \"${PYTHON[*]}\"\n",
            encoding="utf-8", newline="\n")
        os.chmod(resolver, 0o755)
        resolver_path = str(resolver).replace(chr(92), "/")

        def make_case(name: str, files: dict[str, str]) -> Path:
            case = root / name
            case.mkdir()
            for filename, content in files.items():
                write_exe(case / filename, content)
            return case

        def run(case: Path) -> subprocess.CompletedProcess:
            env = dict(os.environ)
            env["PATH"] = str(case).replace(chr(92), "/")
            return subprocess.run([bash, resolver_path], capture_output=True,
                                  text=True, encoding="utf-8", env=env)

        def expect(label: str, ok: bool, detail: str = "") -> None:
            if ok:
                print("PASS %s" % label)
            else:
                failures.append("%s%s" % (label, (": " + detail) if detail else ""))

        stub_first = make_case("stub-first", {"python3": stub, "python": real})
        result = run(stub_first)
        expect("WindowsApps python3 skipped, later real python selected",
               result.returncode == 0 and result.stdout.strip() == "CHOSEN=python",
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:200]))

        # A candidate whose own path is inside Microsoft/WindowsApps must be
        # rejected before it is even probed (lowercase here, to exercise the
        # case-insensitive match on both separators).
        winapps = root / "microsoft" / "windowsapps"
        winapps.mkdir(parents=True)
        write_exe(winapps / "python3", "#!/bin/sh\nexit 0\n")
        env = dict(os.environ)
        env["PATH"] = str(winapps).replace(chr(92), "/")
        result = subprocess.run([bash, resolver_path], capture_output=True,
                                text=True, encoding="utf-8", env=env)
        expect("candidate located under WindowsApps is rejected by path",
               result.returncode == 2 and "WindowsApps" in result.stderr
               and "leancheck.ps1" in result.stderr,
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:300]))

        broken = make_case("broken", {"python3": "#!/bin/sh\nexit 1\n"})
        result = run(broken)
        expect("candidate that cannot run is rejected",
               result.returncode == 2 and "probe failed" in result.stderr,
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:300]))

        real_first = make_case("real-first", {"python3": real, "python": stub})
        result = run(real_first)
        expect("real python3 stays the first choice",
               result.returncode == 0 and result.stdout.strip() == "CHOSEN=python3",
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:200]))

        stub_only = make_case("stub-only", {"python3": stub})
        result = run(stub_only)
        expect("only a WindowsApps placeholder fails with placeholder guidance",
               result.returncode == 2 and not result.stdout.strip()
               and "WindowsApps" in result.stderr and "leancheck.ps1" in result.stderr,
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:300]))

        empty = make_case("empty", {})
        result = run(empty)
        expect("no interpreter fails with installation guidance",
               result.returncode == 2 and not result.stdout.strip()
               and "no usable Python 3" in result.stderr
               and "install Python 3" in result.stderr
               and "WindowsApps" not in result.stderr,
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:300]))

        py_only = make_case("py-only", {"py": py_launcher})
        result = run(py_only)
        expect("py -3 is used as the Windows fallback",
               result.returncode == 0 and result.stdout.strip() == "CHOSEN=py -3",
               "rc=%d out=%r err=%r" % (result.returncode, result.stdout.strip(),
                                        result.stderr.strip()[:200]))
    return failures


def main() -> int:
    failures: list[str] = []
    source = SCRIPT.read_text(encoding="utf-8")
    blocks = HEREDOC.findall(source)
    if len(blocks) != 2:
        failures.append("expected 2 embedded python blocks, found %d" % len(blocks))

    for index, block in enumerate(blocks, start=1):
        try:
            ast.parse(block)
            print("PASS block %d parses (%d lines)" % (index, block.count(chr(10)) + 1))
        except SyntaxError as exc:
            failures.append("block %d does not parse: %s" % (index, exc))
            print("FAIL block %d does not parse: %s" % (index, exc))

    if failures:
        for line in failures:
            print(" - %s" % line)
        return 1

    with tempfile.TemporaryDirectory(prefix="lf-gate-") as tmp:
        tmpdir = Path(tmp)
        config = tmpdir / "lean-formalization.json"
        config.write_text(json.dumps({
            "library": "Fixture",
            "targets": ["Fixture.ok", "Fixture.bad"],
            "entryModules": ["Fixture"],
            "allowedAxioms": ["propext", "Classical.choice", "Quot.sound"],
            "evidenceDir": "evidence/lean",
        }), encoding="utf-8")

        # 2. the config reader must emit the assignments the shell script consumes
        reader = subprocess.run([sys.executable, "-c", blocks[0], str(config)],
                                capture_output=True, text=True, encoding="utf-8")
        emitted = reader.stdout
        for expected in ["LIBRARY=Fixture", "TARGETS=(", "ENTRY=(Fixture)", "BUILD=(Fixture)",
                         "ALLOWED=(propext", "EVIDENCE_DIR=evidence/lean", "LAKE=lake",
                         "AUDIT_SCRIPT=LeanAudit.lean"]:
            if expected not in emitted:
                failures.append("config reader did not emit %r" % expected)
        print("PASS config reader emitted %d assignments" % len(emitted.strip().splitlines()))

        # 3. the whitelist checker must enforce the whitelist. The argument
        # protocol is the one gate/leancheck.sh uses (see its "$PYTHON" - call):
        #   RUN_DIR LIBRARY STAMP LOCK_FILE MIN_DUP SCAN_RAN DOLOCK PROJECT_ROOT NOBUILD
        #   STEP_NAMES -- STATUSES -- STEP_SECONDS -- ALLOWED -- TARGETS
        runs = tmpdir / "runs"
        runs.mkdir(exist_ok=True)
        lock_path = tmpdir / "locked-targets.json"

        def make_run(name: str, records: list[str]) -> Path:
            run_dir = runs / name
            run_dir.mkdir(parents=True)
            (run_dir / "command-axiom-audit.log").write_text(
                "\n".join(records) + "\n", encoding="utf-8")
            return run_dir

        def check(run_dir: Path, allowed: list[str], target: str, do_lock: bool,
                  lock_file: Path = lock_path) -> subprocess.CompletedProcess:
            args = [
                str(run_dir), "Fixture", "20260101T000000Z-abcdef", str(lock_file),
                "40", "0", "1" if do_lock else "0", str(tmpdir), "0",
                "build", "axiom-audit", "--", "0", "0", "--", "1", "1", "--",
                *allowed, "--", target,
            ]
            return subprocess.run([sys.executable, "-c", blocks[1], *args],
                                  capture_output=True, text=True, encoding="utf-8",
                                  cwd=str(tmpdir))

        def load_report(run_dir: Path) -> dict | None:
            report = run_dir / "report.json"
            if not report.is_file():
                return None
            try:
                return json.loads(report.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None

        whitelist = ["propext", "Classical.choice", "Quot.sound"]
        good_record = ('LEANCHECK_JSON:{"name":"Fixture.ok","kind":"theorem",'
                       '"axioms":["propext"],"type":"True"}')
        bad_record = ('LEANCHECK_JSON:{"name":"Fixture.bad","kind":"theorem",'
                      '"axioms":["propext","Classical.choice","Quot.sound"],"type":"False"}')

        good_run = make_run("good", [good_record, bad_record])
        good = check(good_run, whitelist, "Fixture.ok", do_lock=True)
        if good.returncode != 0:
            failures.append("whitelist checker rejected a whitelisted target (exit %d): %s"
                            % (good.returncode, (good.stdout + good.stderr).strip()[:200]))
        else:
            print("PASS whitelisted target accepted (exit 0)")

        good_report = load_report(good_run)
        if good_report is None:
            failures.append("whitelisted run did not write report.json")
        elif (good_report.get("ok") is not True
              or good_report.get("lockWritten") is not True
              or not str(good_report.get("lockState", "")).startswith("written")):
            failures.append("whitelisted report.json has unexpected state: %s"
                            % json.dumps({k: good_report.get(k) for k in
                                          ("ok", "lockWritten", "lockState")}))
        else:
            print("PASS report.json records a passing run and a written lock")

        if not (tmpdir / "LATEST.md").is_file():
            failures.append("whitelist checker did not write LATEST.md next to the runs directory")
        else:
            print("PASS LATEST.md written at the evidence root")
        if not (good_run / "report.md").is_file():
            failures.append("whitelisted run did not write report.md")
        else:
            print("PASS report.md written in the run directory")

        # A statement that no longer matches the lock is a change of target.
        drift_record = ('LEANCHECK_JSON:{"name":"Fixture.ok","kind":"theorem",'
                        '"axioms":["propext"],"type":"Changed"}')
        drift_run = make_run("drift", [drift_record])
        drift = check(drift_run, whitelist, "Fixture.ok", do_lock=False)
        drift_text = drift.stdout + drift.stderr
        if drift.returncode == 0:
            failures.append("whitelist checker accepted a changed locked statement")
        elif "locked statement changed" not in drift_text:
            failures.append("lock drift failed without the expected diagnostic: %s"
                            % drift_text.strip()[:200])
        else:
            print("PASS changed locked statement rejected (exit %d)" % drift.returncode)
        drift_report = load_report(drift_run)
        if drift_report is None or drift_report.get("ok") is not False:
            failures.append("lock-drift run did not record ok=false evidence")

        bad_run = make_run("bad", [good_record, bad_record])
        bad = check(bad_run, ["propext"], "Fixture.bad", do_lock=True,
                    lock_file=tmpdir / "locked-bad.json")
        bad_text = bad.stdout + bad.stderr
        if bad.returncode == 0:
            failures.append("whitelist checker accepted an out-of-whitelist axiom")
        elif "outside the whitelist" not in bad_text:
            failures.append("whitelist violation failed without the expected diagnostic: %s"
                            % bad_text.strip()[:200])
        else:
            print("PASS whitelist violation rejected (exit %d)" % bad.returncode)
        bad_report = load_report(bad_run)
        if bad_report is None or bad_report.get("ok") is not False:
            failures.append("whitelist-violation run did not record ok=false evidence")

        missing_run = make_run("missing", [good_record])
        missing = check(missing_run, ["propext"], "Fixture.absent", do_lock=True,
                        lock_file=tmpdir / "locked-missing.json")
        missing_text = missing.stdout + missing.stderr
        if missing.returncode == 0:
            failures.append("whitelist checker accepted a target that was never reported")
        elif "target not reported" not in missing_text:
            failures.append("unreported target failed without the expected diagnostic: %s"
                            % missing_text.strip()[:200])
        else:
            print("PASS unreported target rejected (exit %d)" % missing.returncode)
        missing_report = load_report(missing_run)
        if missing_report is None or missing_report.get("ok") is not False:
            failures.append("unreported-target run did not record ok=false evidence")

    failures.extend(check_python_discovery(source))

    print("")
    if failures:
        print("gate shell check: FAILED (%d)" % len(failures))
        for line in failures:
            print(" - %s" % line)
        return 1
    print("gate shell check: OK (embedded python only; the shell wrapper needs a real bash)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
