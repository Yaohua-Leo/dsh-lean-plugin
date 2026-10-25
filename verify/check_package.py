"""Validate ZIP bytes and regenerate both modes from an extracted portable kit."""
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO/'tools'))
from package_lean_preset import verify_zip


def main():
    archive = Path(sys.argv[1])
    manifest = verify_zip(archive)
    with tempfile.TemporaryDirectory(prefix='.lf-extract-', dir=REPO) as tmp:
        with zipfile.ZipFile(archive) as z: z.extractall(tmp)
        kit = Path(tmp)/manifest['name']
        for cmd in [['node','verify/validate_repo.mjs'], ['node','verify/check_selfcheck.mjs'],
                    ['node','verify/check_public_package.mjs'],
                    [sys.executable,'verify/check_dsh_preset.py']]:
            result = subprocess.run(cmd,cwd=kit,check=False)
            if result.returncode: return result.returncode
    print(f'PASS ZIP hashes and extracted kit portability: {len(manifest["files"])} payload files')
    return 0


if __name__ == '__main__': raise SystemExit(main())
