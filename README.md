# DSH Lean Proof Assistant

[中文说明](README.zh-CN.md)

A DSH plugin that adds the **Lean证明助手 / Lean Proof Assistant** preset, live
Lean MCP tools, an isolated workflow skill and a fail-closed `lean_selfcheck`.
The package is `@local/dsh-lean-preset`; the preset ID is `lean`.

## Install

In DSH Desktop, open Plugin Manager and add:

```text
github:Yaohua-Leo/dsh-lean-plugin#v1.1.0
```

For a separate CLI profile:

```sh
dsh plugin --profile lean-demo add github:Yaohua-Leo/dsh-lean-plugin#v1.1.0
```

A local checkout also works: `dsh plugin --profile lean-demo add ./dsh-lean-plugin`.
Install the **repository root**. It contains the DSH bundle manifest; no npm
registry publication or install-time build script is required. Release assets
include a ready-to-install `.tgz` and the full source kit `.zip` with checksums.

Restart DSH and start a new **Lean Proof Assistant** session in your Lean project.
Call `lean_selfcheck` before proof work. The Desktop-managed profile must be
managed from Desktop, not through CLI `--dump-config`.

Prerequisites: DSH (`>=0.2.1-rc.2 <0.3.0`; tested on 0.2.1-rc.2), Lean/elan,
ripgrep and uvx. The preset resolves uvx from `~/.local/bin` (Windows:
`%USERPROFILE%\.local\bin\uvx.exe`) and starts `lean-lsp-mcp==0.31.0`.
Python 3.11+ and PyYAML 6.x are needed for authoring/mode-switch scripts.

## Two explicit modes

| Capability | `lsp-fallback` (default) | `beam` |
|---|---|---|
| Goals, diagnostics, navigation | lean-lsp | Lean Beam |
| Speculative tactic probes | lean_multi_attempt | lean_run_at / handles |
| Library search and advisory checks | lean-lsp | lean-lsp |
| Skills | lean-formalization | lean-formalization + lean-beam |
| Final proof acceptance | project gate + independent review | project gate + independent review |

The mode policy lives in `harnesses.json`. `lean_selfcheck` checks the generated
policy against the session's tool catalog and the project's declared mode.
A missing server or mode mismatch blocks work; there is no silent fallback.

For project gate setup and mode switching, see the [setup guide](docs/dsh-kit.md).
Beam activation requires an actual successful project sync with the pinned
runtime before the switcher updates the bundle. Backups and rollback are built in.
Beam native binaries are **not included**. Real Beam runtime acceptance is
**not performed**; generated configurations and mock tests are not proof of it.
Use a local checkout for mode changes, then reload the local bundle.

## Development and verification

```sh
python -m pip install 'PyYAML>=6,<7'
npm run build:preset
npm test
python verify/check_dsh_preset.py
python verify/check_beam_activation.py
python verify/smoke.py --with-gate
python install/install.py --doctor
npm pack --ignore-scripts
```

See [validation results](docs/dsh-kit-validation.md) and
[acceptance boundaries](docs/acceptance.md). Selfcheck is not proof acceptance.
The gate builds the actual Lean project, audits axioms, checks locked statements
and scans library declarations; independent semantic review is still required.

`preset/` contains the runtime. `skills/` contains canonical skill sources;
only skills selected for the active mode are copied into `preset/skills/`.
`tools/` owns generation and guarded switching, `gate/` owns deterministic
acceptance, and `verify/` checks packaging and regression behavior.

## License and provenance

Owned code is MIT licensed. The vendored Lean Beam skill is Apache-2.0;
see [NOTICE](NOTICE), [licenses](licenses/lean-beam-LICENSE) and the
[hash ledger](skills/PROVENANCE.md). This plugin is derived from
[lean-formalization](https://github.com/Yaohua-Leo/lean-formalization).
It is an independent plugin and is not an official DeepSeek or Lean release.
