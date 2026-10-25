# BOOTSTRAP — set yourself up as this repository's Lean formalization assistant

You are an agent. A user gave you this repository's URL and asked you to become
the Lean 4 formalization assistant it describes. This file is the whole procedure;
follow it in order and report at the end.

**Goal state:** on this machine, the user's harnesses (whatever they are) carry the
Lean formalization contract, the `lean-formalization` + `lean-beam` skills, the
Lean MCP servers, and — if the current directory is a Lean project — a working
acceptance gate (`LeanAudit.lean` + `leancheck`).

**This repository's URL** (substitute the real one if the user gave a fork):

```
https://github.com/Yaohua-Leo/lean-formalization
```

---

## Rules you must not break while installing

1. Write only to: the repositories listed in `harnesses.json` for the harnesses you
   detected, the target Lean project directory, and this repository's own checkout.
   Do not touch the git global config, the registry, or system package managers.
2. Never overwrite a file without a backup. `install/install.py` does this for you —
   do not hand-edit config files in a way that bypasses it.
3. Never install a system package (ripgrep, uv, elan, Beam) silently. Report the
   missing prerequisite and the command the user should run.
4. Never claim a step succeeded because "there was no error". Assert the artifact:
   a file's contents, a probe's tool list, an exit code.
5. Anything you did not observe is `unknown`. Say so.

---

## Step 1 — get the content

Try these in order; the first one that works is fine. Record which one you used.

```bash
# 1. git clone (add the TLS backend override only if plain clone fails on Windows)
git clone --depth 1 https://github.com/Yaohua-Leo/lean-formalization.git ~/.lean-formalization/repo
git -c http.sslBackend=openssl clone --depth 1 https://github.com/Yaohua-Leo/lean-formalization.git ~/.lean-formalization/repo

# 2. the GitHub CLI, which uses its own authenticated transport
gh repo clone Yaohua-Leo/lean-formalization ~/.lean-formalization/repo
gh api repos/Yaohua-Leo/lean-formalization/tarball/main > lf.tar.gz   # then unpack

# 3. plain HTTP
curl -L -o lf.tar.gz https://codeload.github.com/Yaohua-Leo/lean-formalization/tar.gz/refs/heads/main
```

If every one of these fails, say which failed with which error and stop — do not
invent the contents of the repository from memory.

Verify you have the real thing: `harnesses.json` parses as JSON, `contract.md`
contains "Non-negotiables", and `install/install.py` exists.

---

## Step 2 — look before you write

Run the installer in dry-run mode first and read the plan it prints:

```bash
python install/install.py --project "$(pwd)" --scope both --dry-run
# or: pwsh -File install/install.ps1 --dry-run      /      sh install/install.sh --dry-run
```

The plan tells you, before anything is written:

- which harnesses were detected (tier 1 = the config paths were checked against the
  harness or its documentation on the authoring machine, and the per-harness status
  column in `docs/harness-matrix.md` says what was actually run; tier-2 harnesses are
  opt-in via `--include-unverified`);
- which MCP mode was chosen (`beam` when a `lean-beam-mcp` launcher or a project
  `tools/beam-mcp.ps1` is present, otherwise `lsp-fallback`);
- which prerequisite is missing (`uvx` is required for the Lean LSP server;
  `rg` is recommended for `lean_local_search`);
- every file it intends to write.

If the plan writes somewhere you did not expect, stop and ask the user.

---

## Step 3 — install

```bash
python install/install.py --project "$(pwd)" --scope both
```

What it does, and nothing else:

| Surface | What is written |
|---|---|
| Instruction files | the delimited block from `contract.md`, between `<!-- lean-formalization:begin v1 -->` and `<!-- lean-formalization:end -->`, in each detected harness's instruction file (project and/or user scope) |
| Skills | `skills/lean-formalization` and `skills/lean-beam` into each detected harness's skill roots |
| MCP | the Lean MCP servers into each detected harness's MCP configuration, in that harness's own format |
| DSH | a bundle source under this checkout's `preset/`; install it into a named profile with `dsh plugin --profile <name> add <repo>/preset` (the installer never writes the retired `$DSH_HOME/.agent-presets/` path) |
| Lean project | `lean-formalization.json`, and (unless `--no-project-gate`) `LeanAudit.lean`, `scripts/leancheck.ps1`, `scripts/leancheck.sh`, `evidence/lean/README.md` |

It is idempotent (a second run writes nothing) and reversible
(`--uninstall` restores every backup it took and deletes only what it created).

If the target is not a Lean project, `--scope project` is refused; use
`--scope user` for a machine-wide install instead.

**Flags worth knowing**

- `--no-project-gate` — do not scaffold the acceptance gate.
- `--include-unverified` — also configure tier-2 harnesses (their config paths were
  not verified on the authoring machine; say so in your report).
- `--uv-cache-dir` / `--uv-tool-dir` — needed when the default `uv` cache is not
  writable by the process that will launch the MCP server (common in sandboxes).
- `--opencode-major 1|2` — force the OpenCode MCP config shape when
  `opencode --version` cannot be read. OpenCode 1.x names servers directly under
  `mcp` and requires `enabled`; 2.x uses `mcp.servers`. Each major rejects the
  other's shape, so a wrong guess makes the harness refuse to start.
- `--doctor` — report the current state of every harness without writing anything.

---

## Step 4 — the nine upstream skills

This repository deliberately does not vendor the nine skills published by
`leanprover/skills` (Apache-2.0). Install them with upstream's own mechanism for
the harness you use — all of these are upstream's documented commands:

```bash
# Claude Code
claude plugin marketplace add https://github.com/leanprover/skills.git
claude plugin install lean@leanprover

# Gemini CLI
gemini skills install https://github.com/leanprover/skills --path skills

# Codex CLI (inside a Codex session)
$skill-installer install https://github.com/leanprover/skills/tree/main/skills/*

# Anything that just reads a skills directory — pinned offline fallback
git -c http.sslBackend=openssl clone https://github.com/leanprover/skills.git /tmp/lean-skills
git -C /tmp/lean-skills checkout 7d3da0282e7b724b07620e45cf212f2e05e19334
cp -r /tmp/lean-skills/skills/* <that harness's skill root>/
```

If the network is unavailable, report which harness is missing these nine skills
rather than copying an unverified version from somewhere else.

---

## Step 5 — verify, with a probe, not with optimism

The installer's own smoke test, run from the repository checkout:

```bash
node verify/validate_repo.mjs       # repository structure, skill frontmatter, vendored hashes
python verify/smoke.py --with-gate  # install → assert → idempotence → uninstall, and a real Lean build
python install/install.py --doctor --project "$(pwd)"
```

For DSH, install the bundle into every profile that should expose the preset:

```bash
dsh plugin --profile <name> add ./preset
dsh --profile <name> --dump-config   # confirm `preset-lean` / the bundle row
```

Then assert that the MCP servers actually start. This launches the command this
repository records for each server (re-derived from `harnesses.json` and live
detection — it does not read any harness's config file) and lists its tools over
stdio:

```bash
python verify/probe_mcp.py --harnesses --project "$(pwd)"
```

Expected: exit 0, `lean-lsp` reports its tools, and no disabled tool name appears
in the list. In `beam` mode also expect `lean-beam` to answer. Inside a sandbox
that blocks `uv`'s cache, add `--env UV_CACHE_DIR=… --env UV_TOOL_DIR=…`.

`--doctor` is a report, not a proof: it shows detection and file presence.
**A file being present is not the same as a harness having loaded it.** To show
that, ask the harness itself — `claude mcp list`, `CODEX_HOME=… codex mcp list`,
`opencode mcp list` — and remember that only a new session proves a harness
actually picked the configuration up.

If the Lean project already has `LeanAudit.lean` or `scripts/leancheck.*`, the
installer leaves those files alone and says so. Do not "fix" them: the project's
own gate may assert more than this scaffold does.

---

## Step 6 — report

Tell the user, in their language:

1. Which harnesses were configured, and which were skipped (not installed, or
   tier-2 and not requested).
2. **Which harnesses need a restart** or a new session before the tools appear, and
   how to check that they appeared.
3. The chosen MCP mode and why (`beam` vs `lsp-fallback`), and what to do to get
   Beam (`https://github.com/leanprover/lean-beam`, then re-run the installer).
4. Missing prerequisites (`uvx`, `rg`, `elan`) with the install command.
5. The acceptance gate: the project's `lean-formalization.json` starts with an
   empty `targets` list. The gate refuses to report success until it is filled.
   Offer to fill it, but do not invent target names.
6. How to roll back: `python install/install.py --uninstall` (backs up under
   `<project>/.lean-formalization/backups/` and `~/.lean-formalization/backups/`).
7. Anything you did not verify, labelled `unknown`.

---

## Appendix A — reload rules per harness

| Harness | How the new configuration takes effect |
|---|---|
| DSH (DeepSeek Harness) | after `dsh plugin --profile <name> add ./preset`, start a **new session** for that profile; the session composition is fixed at start |
| Claude Code | restart the CLI (or start a new session) |
| Codex CLI | restart after `~/.codex/config.toml` changes |
| OpenCode | restart; V2 resolves MCP servers at startup |
| Gemini CLI | restart after `~/.gemini/settings.json` changes |
| Cursor | reload the window |
| VS Code / Copilot | reload the window |

## Appendix B — if python is missing

`install/install.ps1` and `install/install.sh` are launchers; both need a Python 3.11+
interpreter. Without one, do the installation by hand from `harnesses.json`:

1. copy `contract.md`'s body into the harness's instruction file inside the
   `<!-- lean-formalization:begin v1 -->` … `<!-- lean-formalization:end -->` block;
2. copy `skills/lean-formalization` and `skills/lean-beam` into the harness's skill
   root;
3. add the MCP servers to the harness's own config file — the exact shapes and
   paths, with their provenance, are in `docs/harness-matrix.md`.

Then tell the user that the installer path was unavailable, so no manifest exists
and no automatic uninstall is possible.

## Appendix C — what "done" means

Done means: the plan from step 2 was executed, the probes in step 5 returned exit
0 with the expected tool names, and step 6 was reported with the unverified items
labelled as such. A green-looking report with no probe output is not done.
