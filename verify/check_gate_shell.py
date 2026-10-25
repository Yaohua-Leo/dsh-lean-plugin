#!/usr/bin/env python3
"""Static + functional check of the POSIX gate's embedded Python.

`gate/leancheck.sh` cannot be executed on the authoring machine (Git Bash cannot
create its signal pipe under the sandbox), so this script checks what can be
checked without a shell:

  1. every `<<'PY' ... PY` heredoc in the script parses as Python (a syntax error
     there makes the gate exit 2 on every invocation — it happened once);
  2. the config-reading heredoc actually runs and emits the shell assignments the
     script consumes;
  3. the whitelist heredoc actually enforces the whitelist: it exits 0 for a
     whitelisted target, non-zero for an axiom outside it, and non-zero for a
     missing target.

It does NOT prove the surrounding shell logic runs — only a real bash could.

Usage: python verify/check_gate_shell.py   (exit 0 ok, 1 a check failed)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "gate" / "leancheck.sh"
HEREDOC = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.DOTALL)


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

        # 3. the whitelist checker must enforce the whitelist
        run_dir = tmpdir / "runs" / "20260101T000000Z-abcdef"
        run_dir.mkdir(parents=True)
        (run_dir / "command-axiom-audit.log").write_text(
            'LEANCHECK_JSON:{"name":"Fixture.ok","kind":"theorem","axioms":["propext"]}\n'
            + 'LEANCHECK_JSON:{"name":"Fixture.bad","kind":"theorem","axioms":["propext","Classical.choice","Quot.sound"]}\n',
            encoding="utf-8")
        (tmpdir / "runs").mkdir(exist_ok=True)

        def check(args: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, "-c", blocks[1], *args],
                                  capture_output=True, text=True, encoding="utf-8", cwd=str(tmpdir))

        good = check([str(run_dir), "Fixture", "evidence/lean", "20260101T000000Z-abcdef",
                      "propext", "Classical.choice", "Quot.sound", "--", "Fixture.ok"])
        if good.returncode != 0:
            failures.append("whitelist checker rejected a whitelisted target (exit %d): %s"
                            % (good.returncode, good.stdout.strip()[:200]))
        else:
            print("PASS whitelisted target accepted (exit 0)")

        bad = check([str(run_dir), "Fixture", "evidence/lean", "20260101T000000Z-abcdef",
                     "propext", "--", "Fixture.bad"])
        if bad.returncode == 0:
            failures.append("whitelist checker accepted an out-of-whitelist axiom")
        else:
            print("PASS whitelist violation rejected (exit %d)" % bad.returncode)

        missing = check([str(run_dir), "Fixture", "evidence/lean", "20260101T000000Z-abcdef",
                         "propext", "--", "Fixture.absent"])
        if missing.returncode == 0:
            failures.append("whitelist checker accepted a target that was never reported")
        else:
            print("PASS unreported target rejected (exit %d)" % missing.returncode)

        if not (tmpdir / "LATEST.md").is_file():
            failures.append("whitelist checker did not write LATEST.md next to the runs directory")
        else:
            print("PASS LATEST.md written at the evidence root")

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
