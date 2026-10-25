"""Build a portable DSH kit from an explicit source allowlist; defaults to LSP."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from lean_capabilities import REPO, read_spec

TOP = ['AGENTS.md','BOOTSTRAP.md','CLAUDE.md','GEMINI.md','README.md','README.zh-CN.md',
       'LICENSE','NOTICE','contract.md','harnesses.json','package.json','.gitignore','.npmignore','.gitattributes']
TREES = ['gate','install','verify','dsh','skills','preset','docs','licenses']
TOOL_FILES = ['build_lean_preset.py','validate_lean_preset.py','lean_capabilities.py',
              'lean_mcp_probe_common.py','probe_beam_project.py','set_lean_mode.py','set-mode.ps1',
              'beam-detect.ps1','probe_lean_mcp.py','probe_lean_search.py','probe_lean_inner_loop.py',
              'package_lean_preset.py']


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_zip(archive):
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or any('..' in Path(n).parts or n.startswith(('/', '\\')) for n in names):
            raise ValueError('unsafe or duplicate ZIP member')
        manifest_name = next(n for n in names if n.endswith('/MANIFEST.json'))
        prefix = manifest_name[:-len('MANIFEST.json')]
        manifest = json.loads(z.read(manifest_name))
        expected = {prefix + name for name in manifest['files']} | {manifest_name}
        if set(names) != expected:
            raise ValueError('ZIP inventory differs from manifest')
        for name, digest in manifest['files'].items():
            if hashlib.sha256(z.read(prefix + name)).hexdigest() != digest:
                raise ValueError('ZIP hash mismatch: ' + name)
        return manifest


def package(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((REPO/'preset/package.json').read_text())['version']
    name = f'dsh-lean-plugin-{version}'
    with tempfile.TemporaryDirectory(prefix='.lf-package-', dir=output) as tmp:
        kit = Path(tmp) / name
        kit.mkdir()
        for entry in TOP: shutil.copy2(REPO / entry, kit / entry)
        for tree in TREES:
            shutil.copytree(REPO/tree, kit/tree, ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
        (kit/'tools').mkdir()
        for entry in TOOL_FILES: shutil.copy2(REPO/'tools'/entry, kit/'tools'/entry)
        shutil.copy2(REPO/'docs/dsh-kit.md', kit/'QUICKSTART.zh-CN.md')
        subprocess.run([sys.executable, str(kit/'tools/build_lean_preset.py'), str(kit), str(kit/'preset')], check=True)
        subprocess.run([sys.executable, str(kit/'tools/validate_lean_preset.py'), str(kit/'preset/cordis.patch.yml'),
                        str(kit/'preset.persona.expected.txt'), str(Path(tmp)/'persona.actual.txt')], check=True)
        (kit/'preset.persona.expected.txt').unlink()
        # Importing the scripts above may create bytecode; bytecode is not shipped.
        for path in sorted(kit.rglob('__pycache__'), reverse=True):
            if not path.resolve().is_relative_to(kit.resolve()): raise ValueError('cache outside kit')
            shutil.rmtree(path)
        spec = read_spec()
        manifest = {'schemaVersion':1, 'name':name, 'generatedUtc':datetime.now(timezone.utc).isoformat(),
                    'defaultMode':'lsp-fallback','beamRuntimeBundled':False,
                    'beamRuntimeAcceptance':'not-run',
                    'beamSourceCommit':spec['skills']['beam']['commit'],
                    'leanLspPackage':spec['mcp']['servers']['lean-lsp']['command'][1],
                    'files':{p.relative_to(kit).as_posix():sha(p) for p in sorted(kit.rglob('*')) if p.is_file()}}
        (kit/'MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n',encoding='utf-8')
        archive = output / (name + '.zip')
        candidate = Path(tmp) / archive.name
        with zipfile.ZipFile(candidate, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(kit.rglob('*')):
                if path.is_file(): z.write(path, name+'/'+path.relative_to(kit).as_posix())
        verify_zip(candidate)
        candidate.replace(archive)
        checksum = archive.with_suffix('.zip.sha256')
        checksum.write_text(f'{sha(archive)}  {archive.name}\n', encoding='ascii')
        print(f'PACKAGE {archive} ({len(manifest["files"])+1} files)')
        print(f'SHA256 {sha(archive)}')
        return archive


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=REPO/'dist')
    args = p.parse_args()
    package(args.output)
