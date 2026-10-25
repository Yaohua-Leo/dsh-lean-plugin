# Provenance ledger

Every byte in this repository is either owned by this repository, or vendored from
an upstream project under its own license. This file records which is which, so a
later update can be checked instead of guessed.

Pinned upstream state at the time this repository was published:

| Upstream | Commit | License |
|---|---|---|
| `https://github.com/leanprover/lean-beam.git` | `753f32ffb74aeb21e390fdc1267aa1dc1dd83a53` | Apache-2.0 |
| `https://github.com/leanprover/skills.git` | `7d3da0282e7b724b07620e45cf212f2e05e19334` | Apache-2.0 |

## Owned here

- `contract.md` — the always-on rules (this repository's own text).
- `skills/lean-formalization/SKILL.md` — the four-layer workflow and the
  Beam ↔ lean-lsp routing table.
- `harnesses.json`, `install/`, `verify/`, `gate/`, `dsh/preset/agent.cordis.yml.tmpl`,
  `docs/`, `BOOTSTRAP.md`, the READMEs.

## Vendored from `leanprover/lean-beam` (Apache-2.0, verbatim)

File contents are byte-identical to the upstream commit above, with LF line
endings (the upstream blob hashes were taken from the GitHub API).

| File | sha256 |
|---|---|
| `licenses/lean-beam-LICENSE` | `7ef159fd8db5a7a9e8051aac48997353f26d744e25f730a0594a806c126d2114` |
| `skills/lean-beam/SKILL.md` | `af8cb7eddc47a919f940d4ae04055147e678b07e6e7de10ac6f0e5bcec089b54` |
| `skills/lean-beam/agents/openai.yaml` | `4cb3bea4b92973aa22318036d1ae686fe6b14f6fe30aaeaa18930b0867a35827` |
| `skills/lean-beam/references/anti-patterns.md` | `b1e6ba9a0b544f8b19350cbd572b2b487439559e96b5b5a3290c1c3e624b559d` |
| `skills/lean-beam/references/commit-speculative.md` | `e7deeb641a94b5b8bfae365812667e011dd9c5412a1a6ba34b4bff3d88b912b0` |
| `skills/lean-beam/references/feedback.md` | `d0ad62b721ef514966583add10295446ef5df8f53d67823dbee357b82b666462` |
| `skills/lean-beam/references/lean-run-at-semantics.md` | `379e17f9378df57a8b38c84904d7c8d2de748aa88c61867f4f4340b0dd2a5aa2` |
| `skills/lean-beam/references/mcts-search.md` | `e1c4897c2777d4dd65457cac12e62094519b0060a21699d667bfaa80564ae213` |
| `skills/lean-beam/references/setup-and-recovery.md` | `f5601bc44332758e5d2c36fb282d87508722c255df2647cdf5527c35cc50b8a3` |
| `skills/lean-beam/references/trust-and-validation.md` | `74ec5a17bbb00250eb85375a6872cb99452e86e3ae59995e7fc79cf4492d6fbf` |
| `skills/lean-beam/references/workflow-details.md` | `f7731c81e3d4fd3daea66b4757e9b177694aeeea425992e3465de7a0f1c24a43` |

`verify/validate_repo.mjs` fails if any of these files stops matching its recorded
hash, so a silent edit to vendored content cannot pass validation.

## Not vendored here: the nine `leanprover/skills` skills

`lean-bisect`, `lean-mwe`, `lean-pr`, `lean-proof`, `lean-setup`, `mathlib-build`,
`mathlib-pr`, `mathlib-review` and `nightly-testing` are **not** copied into this
repository. Installing them is delegated to upstream's own per-harness installers
(`claude plugin marketplace add ...`, `gemini skills install ...`, Codex
`$skill-installer`, or a pinned clone plus copy as the offline fallback). See
`BOOTSTRAP.md` step 5 for the exact commands.

That decision is deliberate: a second copy here would drift from upstream, and
upstream already publishes one installer per harness. This repository carries only
what upstream does not: the contract, the routing skill, the adapter table and the
acceptance gate.

The upstream commit recorded above is the state the pinned-clone fallback checks
out. `lean-setup` declares `name: lean4-setup` in its frontmatter while its
directory is `lean-setup`; that divergence is upstream's and is left alone.

## Updating

1. Resolve the new upstream commit (`git ls-remote`, or the GitHub API).
2. Re-copy the vendored files with LF endings.
3. Recompute the hashes above and update this file in the same commit.
4. Run `node verify/validate_repo.mjs` and `python verify/smoke.py`.

## DSH license notice

The standard preset composition is adapted from DeepSeek Harness. Its license
was copied from commit `22ddee3792402c3e70ec5f86a63c3e3e895a2f60`.

| File | SHA-256 |
|---|---|
| `licenses/deepseek-harness-LICENSE` | `ebb4f09972aee8608be255debaf78451a68e95c290f55c240dec2ecfa16ea6be` |
