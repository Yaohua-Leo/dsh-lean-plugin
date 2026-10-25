"""Exercise mode transitions and reject the two unsafe preset regressions."""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(script, *args):
    return subprocess.run([sys.executable, str(REPO / script), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    with tempfile.TemporaryDirectory(prefix=".lf-preset-", dir=REPO) as work:
        bundle = Path(work) / "preset"
        bundle.mkdir()
        patch = bundle / "cordis.patch.yml"
        expected = bundle.parent / "preset.persona.expected.txt"
        def validate():
            return run("tools/validate_lean_preset.py", patch, expected, bundle.parent / "persona.txt")
        for mode in ([], ["--beam"], []):
            built = run("tools/build_lean_preset.py", REPO, bundle, *mode)
            assert built.returncode == 0, built.stdout + built.stderr
            checked = validate()
            assert checked.returncode == 0, checked.stdout + checked.stderr
        print("PASS fallback -> beam -> fallback; stale Beam skill removed")
        good = patch.read_text(encoding="utf-8")
        patch.write_text(good.replace("failOnStartupError: true", "failOnStartupError: false"), encoding="utf-8")
        assert validate().returncode == 1, "startup fail-open regression was accepted"
        patch.write_text(good, encoding="utf-8")
        patch.write_text(good.replace("includeDefaultRoots: false", "includeDefaultRoots: true"), encoding="utf-8")
        assert validate().returncode == 1, "default-root skill leakage was accepted"
        patch.write_text(good, encoding="utf-8")
        patch.write_text(good.replace("skills: true", "skills: false"), encoding="utf-8")
        assert validate().returncode == 1, "inherited skill-registry leakage was accepted"
        patch.write_text(good, encoding="utf-8")
        (bundle / "skills" / "lean-beam").mkdir()
        assert validate().returncode == 1, "fallback Beam skill leak was accepted"
        print("PASS validator rejects fail-open MCP and fallback Beam skill leakage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
