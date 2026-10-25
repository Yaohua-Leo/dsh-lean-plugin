"""Stage and validate a preset mode for a NEW session, with rollback backups."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from lean_capabilities import REPO, read_spec
from probe_beam_project import probe


def switch(root, mode, project, probe_file=None, beam_command=None, dry_run=False):
    root = Path(root).resolve(strict=True)
    bundle = root / "preset"
    source = root if (root / "harnesses.json").is_file() else root / "repo"
    config_path = Path(project).resolve(strict=True) / "lean-formalization.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    if not isinstance(config, dict) or not isinstance(config.get("targets"), list) or not config.get("library"):
        raise ValueError("project gate config missing/invalid; scaffold and review targets first")
    if mode == "beam" and (not probe_file or not beam_command):
        raise ValueError("Beam mode needs --beam-command and --probe-file for this project")
    if bundle.is_symlink() or bundle.resolve().parent != root:
        raise ValueError("refusing a preset directory outside the kit root")
    if dry_run:
        return {"status": "dry-run-not-verified", "mode": mode, "bundle": str(bundle), "projectConfig": str(config_path)}
    receipt = None
    if mode == "beam":
        receipt = probe(config_path.parent, probe_file, beam_command, spec=read_spec(source))
        beam_command = receipt["beamCommand"]
    with tempfile.TemporaryDirectory(prefix=".lf-mode-", dir=root) as tmp:
        staged = Path(tmp) / "preset"
        shutil.copytree(bundle, staged)
        cmd = [sys.executable, str(REPO / "tools/build_lean_preset.py"), str(source), str(staged)]
        if mode == "beam":
            cmd += ["--beam", "--beam-command", beam_command]
        subprocess.run(cmd, check=True)
        subprocess.run([sys.executable, str(REPO / "tools/validate_lean_preset.py"),
                        str(staged / "cordis.patch.yml"), str(staged.parent / "preset.persona.expected.txt"),
                        str(staged.parent / "persona.actual.txt")], check=True)
        if config_path.read_bytes() != original:
            raise ValueError("project config changed during staging")
        backup = root / "mode-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup.mkdir(parents=True)
        shutil.copytree(bundle, backup / "preset")
        (backup / "lean-formalization.json").write_bytes(original)
        (backup / "restore.json").write_text(json.dumps({"projectConfig": str(config_path), "preset": str(bundle)}, indent=2), encoding="utf-8")
        controls = {name: (root / name).read_bytes() if (root / name).exists() else None for name in ("mode.txt", "beam-command.txt")}
        for name, data in controls.items():
            if data is not None:
                (backup / name).write_bytes(data)
        previous = Path(tmp) / "previous"
        bundle.rename(previous)
        try:
            staged.rename(bundle)
            config["mode"] = mode
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (root / "mode.txt").write_text(mode + "\n", encoding="utf-8")
            if receipt:
                (backup / "beam-probe.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
                (root / "beam-command.txt").write_text(beam_command + "\n", encoding="utf-8")
            elif (root / "beam-command.txt").exists():
                (root / "beam-command.txt").unlink()
        except Exception:
            config_path.write_bytes(original)
            if bundle.exists():
                bundle.rename(Path(tmp) / "failed")
            previous.rename(bundle)
            for name, data in controls.items():
                if data is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    (root / name).write_bytes(data)
            raise
    return {"status": "staged-for-new-session", "mode": mode, "backup": str(backup),
            "proofAcceptance": "unknown", "desktopAcceptance": "unknown"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=REPO)
    p.add_argument("--mode", choices=["beam", "lsp-fallback"], required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--probe-file")
    p.add_argument("--beam-command")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        print(json.dumps(switch(args.root, args.mode, args.project, args.probe_file, args.beam_command, args.dry_run), indent=2))
        return 0
    except Exception as error:
        print(f"REFUSED ({type(error).__name__}): mode switch did not complete. No activation receipt was produced.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
