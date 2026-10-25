# Public release validation

Release: 1.1.0. Checked on 2026-10-25, Windows, DSH 0.2.1-rc.2, Lean 4.35.0.

| Command | Exit | Observed result |
|---|---:|---|
| `node verify/validate_repo.mjs` | 0 | Structure, mode policy, vendored hashes and generated assets |
| `npm test` | 0 | Above plus 24 selfcheck cases and root/nested package resolution |
| `python verify/check_dsh_preset.py` | 0 | Both mode transitions and rejection of skill/startup leakage |
| `python verify/check_beam_activation.py` | 0 | Five mocked controller tests, including write-failure rollback |
| `python verify/smoke.py --with-gate` | 0 | 23 checks; real Lean build, axiom audit, statement lock and library scan |
| `python install/install.py --doctor` | 0 | Diagnostic run; unrelated unconfigured harnesses remain reported |
| `dsh plugin --profile lean-public-check add . --ignore-scripts --offline` | 0 | Root bundle installed in a temporary isolated DSH home |
| `dsh --profile lean-public-check --dump-config` | 0 | Lean preset, private skill group, selfcheck and LSP row composed |
| `npm pack --ignore-scripts` | 0 | Prebuilt package with no installation lifecycle hooks |
| `node verify/check_public_package.mjs <extracted-tgz-root>` | 0 | Actual tarball module and selected skills resolve correctly |
| `python tools/package_lean_preset.py` | 0 | Source ZIP and SHA-256 manifest |
| `python verify/check_package.py dist/dsh-lean-plugin-1.1.0.zip` | 0 | ZIP hashes and clean extraction; both modes regenerate |

The first smoke run found an outdated assertion that expected skills to resolve
beside a subdirectory manifest. It was updated for runtime-module anchoring, with
both entry points covered by actual module/resource resolution tests; the full
smoke rerun passed all 23 checks. The initial sandboxed profile installation hit
Windows EPERM while creating a pnpm store link; a task-local store and an allowed
unsandboxed retry completed the same local installation.

The private Desktop preset run is summarized in [acceptance](acceptance.md).
The public root wrapper has been installed and composed by the DSH CLI; this is
not a second Desktop model run. The package scan found no private session files,
backup trees, environment files or high-confidence credentials in the archive.

Beam runtime acceptance is **NOT RUN**. Controller mocks, package validation and
successful LSP queries do not prove Beam runtime compatibility or certify a
mathematical theorem. Independent semantic review remains separate.
