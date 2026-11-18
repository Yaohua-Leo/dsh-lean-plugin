# DSH Lean Proof Assistant 1.1.0 — 验收与兼容性评估报告

- 评估日期：2026-11-18（Asia/Shanghai）
- 评估对象：`D:\github_inbox\dsh-lean-plugin`，commit `1f85894b330026230fc3f8f27c809d475160a395`，tag `v1.1.0`
- 包名 / 预设：`@local/dsh-lean-preset` / `lean`（「Lean证明助手」）
- 被测环境：DSH Desktop `D:\deepseekharness`，DSH `0.2.1-rc.5`，Electron `44.7.0`，内置 Node `24.21.0`
- 评估性质：**只读验收**。未安装/卸载任何东西，未修改 DSH profile/插件/配置，未读任何凭据文件，未提交 git。
- 总体结论：**部分兼容**。声明与组合层兼容 `0.2.1-rc.5`；LSP 模式在本机可正常启动并完成真实 Lean 交互；但**仓库发布版与当前已安装副本不一致**，发布版 selfcheck 存在 1 个 P0 级运行时风险；**Beam 运行时验收未完成且本机无法完成**；`verify/acceptance.py` 的必需步骤有 2 个失败（1 个仓库缺陷、1 个环境依赖）。

---

## 0. 结论摘要（TL;DR）

| 维度 | 结论 | 关键证据 |
|---|---|---|
| `engines.dsh` 版本范围 | **兼容** | `0.2.1-rc.5` 满足 `>=0.2.1-rc.2 <0.3.0`；DSH 自己的 `evaluatePluginCompatibility` 返回 `COMPATIBLE` |
| `cordis.patch.yml` 包名/服务/字段 | **兼容** | 31 个 `@deepseek-ai/*` 插件引用全部存在于 rc.5；关键服务与配置字段逐一核对通过 |
| 与 rc.5 标准预设的组合一致性 | **兼容** | 23 行 vs 标准 22 行，仅 3 个有意新增/替换行；其余共有行仅 persona 与 compaction 阈值不同（均为文档声明的有意差异） |
| LSP / `lsp-fallback` 运行时 | **可用（有前提）** | 固定 `lean-lsp-mcp==0.31.0` 启动成功，16 个工具；真实 Lean 4.35.0-rc3 项目上 outline/goal/diagnostics/search 实测通过 |
| `lean_selfcheck` fail-closed 逻辑 | **通过** | 24 次模块执行（两种模式）通过；输出 schema 通过 rc.5 校验器；API 用法与 rc.5 一致 |
| 发布版 selfcheck 的 `parameters` | **P0 风险** | 仓库为 `{}`，已安装副本为 `{ type: 'object', properties: {} }`；raw `tools.register` 原样转发给模型 provider |
| 项目验收门（Windows） | **通过** | `smoke --with-gate` 中 Lean build、axiom audit、statement lock、library scan、白名单失败、无命令证据等 22 项全部通过 |
| POSIX 验收门 | **可运行但本机默认失败** | Git Bash 下 `python3` 被 WindowsApps 占位符遮蔽，config 读取为空→`unbound variable`；换有效 `python3` 后 PASS |
| 仓库验收脚本整体 | **FAIL** | `verify/acceptance.py` 退出 1；必需步骤 smoke、gate-shell 失败 |
| Beam 模式 | **未验收（本机不可完成）** | 无 `lean-beam-mcp`、无 `~/.local/share/beam`、toolchain 无 Beam；mock 5 项通过但明确不是运行证据 |
| Beam 模式组合配置 | **静态兼容** | 生成的 beam 补丁结构合法，MCP 行/技能/字段与 rc.5 一致 |
| 已安装副本 vs 仓库 | **不一致（同版本号）** | 10 个文件全部同名同版本；按行尾归一化后 8 个完全一致，2 个语义不同（`index.js`、`cordis.patch.yml`） |

**兼容性结论：部分兼容。** 更准确地说：

1. **声明层兼容**：版本范围、bundle 清单、组合补丁、包名、服务与配置字段全部通过。
2. **运行时层存在风险**：仓库发布版的 `lean_selfcheck` 参数 schema 与本机已安装副本的热修不同；后者注释记录了 rc.5 下空 schema 导致会话在首个请求前被网关拒绝。本报告受只读约束，未启动真实 DSH 会话来复现。
3. **Beam 未验证**：不能在“未验证”前把 Beam 模式称作兼容。

---

## 1. 评估范围、方法与约束

### 1.1 范围

按任务要求覆盖：

1. 仓库声明与验收标准：`README.md`、`README.zh-CN.md`、`AGENTS.md`、`contract.md`、`BOOTSTRAP.md`、`docs/`、`package.json`、`preset/`（含 `cordis.patch.yml`）、`install/`、`verify/`、`gate/`。
2. 现有验收/测试命令：`npm test`、`verify/` 下的 Node/Python 检查脚本、`install/install.py --doctor`（仅诊断）。
3. 与当前 DSH 的兼容性：版本范围、包名/服务/字段、接口签名、已安装副本只读对比。
4. Beam 运行时验收可行性。
5. P0/P1/P2 缺口清单。

### 1.2 方法与边界

- **只读**：仓库仅新增本报告；未执行真实安装、卸载、`dsh plugin add`、profile 修改或 git 写操作。
- **未启动 DSH 会话**：因此没有“新会话加载预设并调用 `lean_selfcheck`”的端到端 Desktop 证据；这一项是本次评估最大的未知（见第 8 节）。
- **未读取密钥**：没有访问 `.credentials.yaml`、`state\dispatch-bridge\secret` 等任何凭据文件。
- **允许的子进程探测**：MCP stdio 探测、真实 Lean 项目探测、Python/Node 脚本、`git`/文件哈希/只读比较。
- **临时文件**：构建与探测产物均写 `D:\dsh-tmp`；仓库内测试产物（`evidence/`、`.smoke/`、`.uv-probe/`、`__pycache__/`）在报告完成后清理。

### 1.3 环境事实

| 项 | 值 | 来源 |
|---|---|---|
| 操作系统 | Windows（MINGW64_NT-10.0-26100） | `uname -a` |
| DSH CLI | `0.2.1-rc.5` | `D:\deepseekharness\resources\runtime\cli\bin\dsh.cmd --version` |
| DSH 运行时包 | `@deepseek-ai/dsh-desktop-runtime 0.2.1-rc.5` | asar `dsh/package.json` |
| Electron / 内置 Node | `44.7.0` / `24.21.0` | `ELECTRON_RUN_AS_NODE=1 DeepSeek Harness.exe` |
| PATH Node / npm | `24.14.0` / `11.9.0` | `node --version`、`npm --version` |
| Python / PyYAML | `3.14.3` / `6.0.3` | `python --version`、`python -c "import yaml"` |
| Lean / elan / Lake | `4.21.0`（默认）/ `4.2.1` / `5.0.0` | `elan show`、`lean --version`、`lake --version` |
| 其他已装 Lean | `4.34.0`、`4.28.0`、`4.29.0-rc6`、`4.33.0`、`4.35.0-rc2`、`4.35.0-rc3` | `elan toolchain list` |
| uvx / ripgrep | `0.10.7` / `14.1.1` | `uvx --version`、`rg --version` |
| PowerShell | `7.6.10`（pwsh）/ `5.1` | `$PSVersionTable` |
| git | `2.56.0.windows.2` | `git --version` |
| DSH 内置 `@deepseek-ai` 包数 | 307 | asar 目录枚举 |
| Desktop profile | `D:\github_inbox\deepseek-ai\dsh-home\profiles\desktop`（只读） | 运行环境变量 `DSH_PROFILE_DIR` |

---

## 2. 插件声明能力与验收标准

### 2.1 两种显式模式

`README.md` 与 `preset/README.md` 声明了两种模式，模式策略的唯一来源是 [`harnesses.json`](../harnesses.json)：

| 能力 | `lsp-fallback`（默认） | `beam` |
|---|---|---|
| 目标、诊断、导航 | lean-lsp | Lean Beam |
| 不改文件的战术试探 | `lean_multi_attempt` | `lean_run_at` / handles |
| 库检索与辅助检查 | lean-lsp | lean-lsp（必须显式 `project_root`） |
| 技能 | lean-formalization | lean-formalization + lean-beam |
| 最终验收 | 项目 gate + 独立语义复核 | 项目 gate + 独立语义复核 |

两种模式均禁用 `lean_build` 与 `lean_run_code`，构建由项目 gate（`lake --no-cache build`）负责。`harnesses.json` 的 `mcp.capabilityProfiles` 定义 required/forbidden 工具集合，`tools/build_lean_preset.py` 生成 `preset/runtime-policy.json` 与 `cordis.patch.yml`。

### 2.2 fail-closed `lean_selfcheck`

[`preset/index.js`](../preset/index.js) 注册 `lean_selfcheck`，[`preset/capabilities.js`](../preset/capabilities.js) 做纯模式判定：

- 必需工具缺失 → `missing-required`，`mcpReady=false`；
- 出现禁用工具 → `forbidden-present`，`mcpReady=false`；
- 项目 `lean-formalization.json` 的模式与预设不一致 → `mode-mismatch`；
- gate 配置缺失/非法/空 targets/锁缺失 → `gateStatus` 非 `ready`；
- 只有目录与模式完全匹配时 `mcpReady=true`；`verdict` 明确说明“工具目录不等于证明验收”。

`preset/cordis.patch.yml` 中 `mcp-lean-lsp` 设置 `failOnStartupError: true`，MCP 启动失败会拒绝插件激活，而不是静默降级。

### 2.3 项目验收门

- Windows：[`gate/leancheck.ps1`](../gate/leancheck.ps1)；POSIX：[`gate/leancheck.sh`](../gate/leancheck.sh)；
- 顺序：`lake --no-cache build` → axiom audit（`LeanAudit.lean`）→ 白名单检查 → statement lock 比对 → 库扫描（`LeanScan.lean`，检查 `sorryAx` 与重复命题）→ 证据目录；
- 空 targets、无锁、锁漂移、白名单违规、无法解析的命令都必须 fail-closed，并仍然写证据；
- 门是项目无关的，所有项目特定值来自 `lean-formalization.json`。

### 2.4 声明的重要验收边界（原文要点）

- `docs/acceptance.md`：1.1.0 的历史 Desktop 验收是在 **DSH 0.2.1-rc.2 + Lean 4.35.0** 上做的；`lean_selfcheck` 报 16 个 LSP 工具、0 个 Beam 工具；**Beam runtime acceptance is not run**。
- `docs/dsh-kit-validation.md`：发布验证在 2026-10-25 完成；`smoke --with-gate` 23 项、真实 Lean build、axiom audit、statement lock、library scan；Beam runtime acceptance **NOT RUN**。
- `README.md`：仅声明“tested on 0.2.1-rc.2”；Beam 原生二进制不包含；真实 Beam 运行验收未执行。

这些边界声明与本次观察一致；问题在于**声明范围与当前实际部署/测试状态之间的漂移**（详见第 6、7 节）。

---

## 3. 验收执行记录

> 说明：所有命令从仓库根目录运行；除特别说明外均为 2026-11-18 当次执行。`[exit: N]` 是脚本自身退出码，不是外层 shell 的。

### 3.1 命令总表

| # | 命令 | 退出码 | 结果 |
|---:|---|---:|---|
| 1 | `npm test` | 0 | 通过；`validate_repo.mjs` + 24 次 selfcheck + public package |
| 2 | `node verify/validate_repo.mjs` | 0 | `repository validation: OK` |
| 3 | `node verify/check_selfcheck.mjs` | 0 | 24 次模块执行，两种模式，schema/fail-closed 通过 |
| 4 | `node verify/check_public_package.mjs` | 0 | 根/嵌套解析、隔离技能、ESM、无安装钩子 |
| 5 | `python verify/check_gate_shell.py` | **1** | **失败 2 项**（白名单块参数协议不一致） |
| 6 | `python verify/check_dsh_preset.py` | 0 | fallback→beam→fallback、拒绝三类回归 |
| 7 | `python verify/check_beam_activation.py` | 0 | 5 个 mock 控制器测试；明确打印 `MOCK CONTROLLER TESTS ONLY` |
| 8 | `python verify/provenance_recheck.py` | 0 | 12 行哈希账本全部一致 |
| 9 | `python verify/smoke.py --with-gate --work D:\dsh-tmp\smoke-work` | **1** | 23 项中 22 项通过；`every expected file exists` 因 gemini 环境失败 |
| 10 | `python verify/acceptance.py` | **1** | 必需步骤 smoke、gate-shell 失败；其余通过 |
| 11 | `python install/install.py --doctor` | 0 | 只读诊断；DSH `installed`，其他 harness 未配置（预期） |
| 12 | `python tools/package_lean_preset.py --output D:\dsh-tmp\dist` + `python verify/check_package.py <zip>` | 0 | 82 文件 ZIP，解包 kit 可移植性通过 |
| 13 | `npm pack --ignore-scripts --pack-destination D:\dsh-tmp\npm-pack` + `node verify/check_public_package.mjs <extracted>` | 0 | 77 文件 tarball，公共包边界通过 |
| 14 | `python verify/probe_mcp.py --command "uvx lean-lsp-mcp==0.31.0" ...` | 0 | 16 工具，`serverInfo.version=0.31.0`，必需在/禁用不在 |
| 15 | `python verify/probe_mcp.py --harnesses --project .` | 0 | 16 工具（固定版本命令） |
| 16 | `python tools/probe_lean_mcp.py` | 0 | 16 工具，精确预设工具面 OK |
| 17 | `python tools/probe_lean_inner_loop.py`（Lean 4.35.0-rc3 项目） | 0 | outline / goal / diagnostics 真实成功 |
| 18 | 同上（smoke 的 Lean 4.21 夹具） | **1** | lean-lsp 报 “requires >= 4.24” |
| 19 | `python tools/probe_lean_search.py`（Lean 4.35.0-rc3 项目） | 0 | 两种 PATH 下均找到 `probeLemma`，观察 `warming` 回退索引 |
| 20 | `pwsh -File tools/beam-detect.ps1`（函数调用） | 0 | `Found=false`，无任何候选 |
| 21 | `python tools/set_lean_mode.py --mode beam ... --dry-run` | **2** | Beam 缺命令/探测文件时拒绝，不产生 receipt |
| 22 | 同上 `--mode lsp-fallback --dry-run` | 0 | `dry-run-not-verified`，不写入 |
| 23 | DSH `evaluatePluginCompatibility(root, {}, '0.2.1-rc.5')` | 0（脚本） | `COMPATIBLE` |
| 24 | POSIX gate（默认 `python3`） | **1** | `TARGETS/SAFEDIRS/EVIDENCE_DIR: unbound variable` |
| 25 | POSIX gate（有效 `python3` 垫片） | 0 | 真实 Lean 夹具上 `leancheck: PASS` |

### 3.2 `npm test`

```text
harnesses     : 10 (tier 1: 7)
skills        : lean-beam, lean-formalization
mcp servers   : lean-lsp, lean-beam
...
repository validation: OK
PASS selfcheck: 24 module executions, both modes, output schema and fail-closed errors
PASS public package: root/nested resolution, isolated skills, ESM entry, no install hooks
[exit: 0]
```

覆盖率说明：本次 `npm test` 只覆盖结构/模块逻辑/包边界，不覆盖真实 MCP、真实 DSH 会话或 provider 请求 schema。

### 3.3 `install/install.py --doctor`（只读）

```text
harness          tier     detected   block     skills    mcp configured
dsh              1        True       -         1/1       installed
claude-code      1        True       1/2       0/2       0/1
codex            1        True       0/2       0/1       0/1
opencode         1        True       0/2       1/4       0/2
gemini-cli       1        True       1/2       0/1       0/1
cursor           1        True       0/2       0/2       0/2
vscode           1        True       0/2       -         0/1
workbuddy        2        True       1/1       1/1       1/1
mistral-vibe     2        False      -         -         0/1
generic-agents-md 2        True       0/2       1/2       -
[exit: 0]
```

- `dsh ... installed`：doctor 在 `DSH_HOME\profiles\desktop\package.json` 的 `dsh.profile.bundles` 中找到 `@local/dsh-lean-preset`，与文件一致。
- 其他 harness 显示 `0/1`、`1/2` 等是“未执行安装”的预期结果，不是缺陷；本次按要求没有执行真实安装。
- doctor 不校验已安装副本的版本/内容，也不校验 bundle 组合是否能被 rc.5 加载（见 P2 建议）。

### 3.4 打包 / 解包验收

```text
PACKAGE D:\dsh-tmp\dist\dsh-lean-plugin-1.1.0.zip (82 files)
SHA256 1e1062952ce05fe633e150d8169e11c782a7043fac54318b3d0499284b9cd717
...
PASS ZIP hashes and extracted kit portability: 81 payload files
[exit: 0]
```

`npm pack` 生成 77 文件 tarball，解包后 `check_public_package.mjs` 仍通过；根包与嵌套 `preset/` 两种入口的 ESM/技能解析都已实际执行。

### 3.5 真实 LSP 探测（本次额外执行）

固定版本（与预设一致）：

```text
lean-lsp   OK   16      Lean LSP
serverInfo {'name': 'Lean LSP', 'version': '0.31.0'}
tools: lean_declaration_file, lean_diagnostic_messages, lean_file_outline,
lean_goal, lean_hammer_premise, lean_hover_info, lean_leanfinder,
lean_leansearch, lean_local_search, lean_loogle, lean_minimal_hypotheses,
lean_multi_attempt, lean_profile_proof, lean_references, lean_term_goal,
lean_verify
```

必需工具（7 个）全部出现；禁用工具（`lean_build`、`lean_run_code` 等 6 个）均未出现。`probe_mcp.py --harnesses` 与 `tools/probe_lean_mcp.py` 得到同样结果。

真实 Lean 项目（`D:\dsh-tmp\lean-probe`，`leanprover/lean4:v4.35.0-rc3`）：

```text
lean_file_outline: isError=False  (declaration probe_true, type True)
lean_goal: isError=False           {"line_context":"  trivial","goals":["⊢ True"],"status":"goals"}
lean_diagnostic_messages: isError=False  {"success":true,"items":[]}
[exit: 0]
```

`probe_lean_search.py`：

```text
[PATH without .local\bin] tools=16 isError=False ; items:[{name:probeLemma,...}], index:"warming"
[PATH with .local\bin]    tools=16 isError=False ; items:[{name:probeLemma,...}], index:"warming"
OK: file initialization and PATH-sensitive search behavior verified
[exit: 0]
```

这证明：**LSP 模式的核心交互（outline/goal/diagnostics/local search）在本机固定版本 0.31.0 下真实可用**；但它不是 DSH 会话级验收，也不覆盖 DSH 对工具 schema 的 provider 转发（见第 4.1 节）。

---

## 4. 失败与异常项分析

### 4.1 P0：发布版 `lean_selfcheck` 的空参数 schema（仓库 vs 已安装副本）

**现状**

- 仓库 [`preset/index.js:28`](../preset/index.js:28)：

  ```js
  parameters: {},
  ```

- 当前 Desktop profile 实际加载的已安装副本（`D:\github_inbox\deepseek-ai\dsh-home\local-packages\lean-preset\index.js`，版本同为 1.1.0）已经改成：

  ```js
  parameters: { type: 'object', properties: {} },
  ```

  并且带有一段本地注释，明确记录：raw `ctx.tools.register()` 会把 `parameters` 原样转发为 provider 的 function schema；空 `{}` 被网关以 `'' is not valid under any of the schemas listed in the 'anyOf' keyword` 拒绝，导致会话在第一步之前就因 `invalid_request_error` 结束。

**rc.5 代码路径核对**

- `@deepseek-ai/dsh-tools@0.2.1-rc.5` 的 `register(definition)` 只校验 `output`，**不校验、也不归一化 `parameters`**；
- `schemaOf(definition)` 原样返回 `parameters`；
- `@deepseek-ai/dsh-llm-deepseek@0.2.1-rc.5`（`deepseek-official` 使用的 Messages 适配器）把工具映射为 `input_schema: tool.parameters`，即空对象会原样上线；
- 内置无参工具（如 `get_goal`、`job_list`、`schedule_list`）都走 `defineTool({ parameters: {} })`，由 `dsh-tools` 编译成 `{type:'object',properties:{}}` 后再注册；本插件绕过 `defineTool`，因此**没有这层归一化**。

**影响**

`lean_selfcheck` 会随工具目录出现在每个模型的请求里；如果 provider 拒绝该 schema，会话在首个 assistant step 之前就失败。严重度按 P0 处理。

**证据强度与未知**

- 强：仓库与已安装副本的差异、rc.5 的 raw 转发路径、内置工具的统一做法、已安装副本的现场注释。
- 未知：本次按只读约束没有启动真实 DSH 会话，也没有向 provider 发请求，因此**没有本次现场复现**。这不改变“发布版与已验证热修版不一致”的事实。

**建议**

1. 将 `parameters` 改为 `{ type: 'object', properties: {} }`（或等价 raw JSON Schema），并加注释说明 raw register 语义；
2. 在 `verify/check_selfcheck.mjs` 增加断言：captured `parameters` 必须是对象根 schema（`type === 'object'`），防止回归；
3. 在 rc.5 + `deepseek-official/deepseek-flash` 上做一次真实 Desktop 会话验收（调用 `lean_selfcheck`），记录工具数与请求结果；
4. 发布 1.1.1 并让 Desktop 重新安装仓库版本（或明确把已安装副本的热修回流后重新链接）。

### 4.2 P1：`verify/check_gate_shell.py` 与生产 gate 的参数协议不一致

**现象**

```text
PASS block 1 parses (26 lines)
PASS block 2 parses (196 lines)
PASS config reader emitted 13 assignments
PASS whitelist violation rejected (exit 1)
PASS unreported target rejected (exit 1)

gate shell check: FAILED (2)
 - whitelist checker rejected a whitelisted target (exit 1):
 - whitelist checker did not write LATEST.md next to the runs directory
[exit: 1]
```

**根因（已复现并证明）**

- 生产脚本 [`gate/leancheck.sh:150`](../gate/leancheck.sh:150) 的调用协议是：

  ```text
  9 个位置参数（RUN_DIR LIBRARY STAMP LOCK_FILE MIN_DUP SCAN_RAN DOLOCK PROJECT_ROOT NOBUILD）
  + STEP_NAMES -- STATUSES -- STEP_SECONDS -- ALLOWED -- TARGETS
  ```

- 测试 [`verify/check_gate_shell.py:92`](../verify/check_gate_shell.py:92) 只传了 9 个参数（且把 `propext/Classical.choice/Quot.sound` 当作第 5–7 个位置参数），没有传 4 个 `--` 分隔的五组数据；
- 于是块内 `rest.index('--')` 抛 `ValueError`，退出 1，`LATEST.md`/`report.json` 未写。

**手工验证**：用同一块、按 shell 的真实参数顺序调用，退出 0，`LATEST.md`、`report.json`、`locked-targets.json` 均生成。→ **gate 逻辑本身可用，测试调用已过期**。

**影响**：`verify/acceptance.py` 的必需步骤失败，发布检查链变红；也会掩盖真正的 gate 回归。

**建议**：把测试改成真实协议（9 位置参数 + 五组 `--` 分隔），或改为在 POSIX shell 中直接跑 `leancheck.sh`（CI 的 Linux 跑）；断言 `LATEST.md` 与 `report.json`。把该脚本纳入 `npm test` 或 CI。

### 4.3 P2：`smoke.py` 对 gemini 的硬编码期望（环境相关失败）

**现象**

```text
FAIL every expected file exists — FixtureProj\GEMINI.md, home\.gemini\settings.json
[23 checks, 1 failed]
```

**根因**

- 本机没有 `gemini` 可执行文件（`which gemini` 失败，PATH 里的 `/d/gemini` 不存在）；但真实 home 下有 `~/.gemini` 符号链接，所以 doctor 通过路径检测把 `gemini-cli` 判为 detected。
- `smoke.py` 用 `--home <fixture>` 固定了 fixture home；fixture 下的 `~/.gemini` 不存在、PATH 里也没有 `gemini`，安装器正确地没有写 GEMINI.md / `.gemini/settings.json`；
- 但 [`verify/smoke.py:139-160`](../verify/smoke.py:139) 无条件把这些文件列入“必须存在”。

**影响**：环境相关误报；真实的 gate 22 项全部通过，但测试整体失败，削弱“23 项全过”的可信度。

**建议**：按检测到的 harness 计算期望文件（或在 fixture PATH 中注入假 `gemini`），把该检查拆成 per-harness；在没有 gemini CLI 时明确 skip 而不是 fail。

### 4.4 P2：POSIX gate 在 Git Bash 下的 `python3` 选择

**现象**（`bash scripts/leancheck.sh`，默认 PATH）：

```text
scripts/leancheck.sh: line 90: TARGETS: unbound variable
scripts/leancheck.sh: line 99: SAFEDIRS: unbound variable
scripts/leancheck.sh: line 111: EVIDENCE_DIR: unbound variable
[exit: 1]
```

**根因**：Git Bash 下 `command -v python3` 命中 `C:\Users\Leo\AppData\Local\Microsoft\WindowsApps\python3`（Store 占位符），它返回 0 且无输出；脚本优先选 `python3` 而不验证解释器，config 读取块输出为空，`set -u` 触发 unbound。用有效 `python3` 垫片后同一 gate 在 Lean 夹具上 `leancheck: PASS`。

**影响**：Windows Git Bash 用户按脚本注释的“python fallback”使用时，POSIX gate 直接失败；Linux/macOS 正常。这也解释了为什么 `check_gate_shell.py` 只做 static 检查。

**建议**：对候选解释器做一次 `-c 'import json'` 走通校验，或优先 `python` 再 `python3`，或在 Git Bash 下显式拒绝并提示用 PowerShell gate；更新脚本注释。

### 4.5 其它验收观察

- `verify/acceptance.py` 报 `FAILED required steps: smoke, gate-shell`；其余必需步骤（validate-repo、provenance、probe-lean-lsp）通过。证据目录生成在 `evidence/20261118T100752Z-2594ca/`（本次按约束已清理）。
- `acceptance.py` 的 `probe-lean-lsp` 步骤使用未固定版本的 `uvx lean-lsp-mcp`，本次解析到 **0.33.0**，得到 **20** 个工具；而预设固定 **0.31.0 / 16** 个工具。步骤注释却写 “the exact command the lsp-fallback configuration records”。这是验收脚本的漂移（P2），不是 MCP 故障。
- 在 smoke 的 Lean 4.21 夹具上运行 `probe_lean_inner_loop.py` 得到：

  ```text
  Failed to start Lean language server: Project toolchain is Lean 4.21;
  leanclient.aio requires >= 4.24.
  ```

  说明 LSP 模式对项目 Lean 版本有最低要求，而 README/docs 未声明（P1）。

---

## 5. Beam 运行时验收专项

### 5.1 本次实际尝试

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 启动器探测 | `pwsh . ./tools/beam-detect.ps1; Get-BeamLauncher` | `Found=false`，`Candidates=[]` |
| PATH | `command -v lean-beam-mcp` | 不存在 |
| 用户目录 | `~/.local/bin/lean-beam-mcp.exe`、`~/.local/share/beam` | 不存在 |
| elan toolchain | 各 toolchain `bin/lean-beam-mcp.exe` | 没有任何一个包含 |
| 项目 launcher | `tools/beam-mcp.ps1` / `tools/beam.ps1` | 无 |
| 控制器回归 | `python verify/check_beam_activation.py` | 5 项 mock 通过；脚本自己打印 `MOCK CONTROLLER TESTS ONLY: no Beam runtime acceptance` |
| 切换 fail-closed | `set_lean_mode.py --mode beam --dry-run` | 退出 2，拒绝，无 receipt |
| 构建前置 | `cmake`、Visual Studio | `cmake` 不存在；无 VS 安装；有 clang 23.1.1、Windows SDK include 10.0.26100.0 |
| Beam 源码 | `D:\beam-source` 或本地 clone | 不存在 |

### 5.2 结论

**Beam 运行时验收在本机无法完成。** 卡点按顺序：

1. 没有固定提交 `753f32ffb74aeb21e390fdc1267aa1dc1dd83a53` 的 `lean-beam-mcp` 二进制（插件明确不附带）；
2. 要构建需要：完整 cmake、Windows SDK/VS 工具链、一份**完整的独立 Lean 安装副本**（upstream `TOOLCHAIN_BUNDLING.md` 要求），以及网络 clone；当前 `cmake`/VS 缺失，Lean SDK 也未准备；
3. 即便有二进制，还需要一个目标 Lean 项目（与 Beam 工具链匹配）来跑 `lean_sync`；仓库不是 Lean 项目，本机没有现成可用的目标项目；
4. 本次是只读验收，安装/构建 Beam 本身也违反约束。

`mock` 测试、静态配置生成、成功 MCP tool list **都不是** Beam runtime 证据；这一点仓库文档的表述是正确的。

**解除阻塞需要**（供后续任务参考）：

- 按 `docs/dsh-kit.md` 的固定提交构建或获取 `lean-beam-mcp`；
- 准备一个真实 Lean 项目（版本与 Beam 工具链一致），运行 `tools/set-mode.ps1 -Beam -Project ... -ProbeFile ... -BeamCommand ...`，保存 `beam-probe.json`；
- 在 Beam 会话中调用 `beam_version`、`lean_sync`、`lean_run_at`、`lean_drop_workspace`，记录退出码与诊断；
- 把结果写入 `docs/acceptance.md`；在完成之前，Beam 模式应继续标注为“未验收/实验”。

---

## 6. 兼容性评估（DSH 0.2.1-rc.5）

### 6.1 版本范围

声明（[`package.json:60`](../package.json:60)）：

```json
"engines": {
  "node": ">=22.16.0",
  "dsh": ">=0.2.1-rc.2 <0.3.0"
}
```

核对结果：

| 版本 | 普通 semver | DSH 实际判定（`includePrerelease: true`） |
|---|---:|---:|
| `0.2.1-rc.1` | false | false |
| `0.2.1-rc.2` | true | true |
| **`0.2.1-rc.5`（当前）** | **true** | **true** |
| `0.2.1` | true | true |
| `0.3.0-rc.1` | false | **true** |
| `0.3.0` | false | false |

- DSH 自身的 `evaluatePluginCompatibility(root package.json, {}, '0.2.1-rc.5')` 返回 **`COMPATIBLE`**（无未满足 requirements）；
- 已安装的嵌套 `preset/package.json` 没有 `engines.dsh`，其判定同样为 `COMPATIBLE`（无约束）；
- 注意：DSH 的判定使用 `includePrerelease: true`，因此 `<0.3.0` 会接受 `0.3.0-rc.1`；如果希望严格排除 0.3.x prerelease，建议写成 `<0.3.0-0`。当前 rc.5 不受影响，但这是未来的边界风险（P2）。

### 6.2 组合补丁引用的包 / 服务 / 字段

对 `preset/cordis.patch.yml` 做静态提取，共引用 **32 个插件名**（31 个 `@deepseek-ai/*` + `@local/dsh-lean-preset`；另有 2 个 `cordis:group`）。核对结果：

- 31 个 `@deepseek-ai/*` **全部存在**于 rc.5 的 `node_modules`，版本均为 `0.2.1-rc.5`；3 个子路径（`dsh-tool-subagent-control/list-agents`、`dsh-plugin-manager/tools`、`dsh-plugin-market/tools`）的 exports 都存在；
- `@local/dsh-lean-preset` 不在 asar 中（预期，本地 link）；在真实 profile 中通过 `node_modules/@local/dsh-lean-preset` 链接解析成功，`skills/lean-formalization/SKILL.md` 存在；
- `cordis:group` 是内置名称，标准预设同样使用。

关键接口/字段核对（全部为 rc.5 实际代码或 README）：

| 插件/服务 | 插件用法 | rc.5 证据 |
|---|---|---|
| `@deepseek-ai/dsh-agent-preset` | `config.id/name/description/order/plugins` | README 字段表与标准预设一致 |
| `@deepseek-ai/dsh-mcp-client` | `serverName`、`transport: stdio`、`command`、`args`、`env`、`toolCallTimeoutMs`、`failOnStartupError` | README 配置表；`failOnStartupError` 在 `lib/index.js` 生效 |
| `@deepseek-ai/dsh-skill-filesystem` | `includeDefaultRoots: false`、`customSkillDirs` | 源码 `Config` 中存在这两个字段；`ctx.skills` 依赖成立 |
| `@deepseek-ai/dsh-skill` | 私有 `skills` 注册表 | README：provider/consumer 都通过 `ctx.skills` |
| `cordis-plugin-loader` | `isolate: { skills: true }`（group） | 类型定义 `isolate?: Dict<true \| string>`；标准组合也使用 group/isolate |
| `@deepseek-ai/dsh-tools` | `ctx.tools.register`、`ctx.tools.schemas(agent)` | `schemas(scope)` 存在；register 接受 `name/description/parameters/output/execute` |
| `ctx.get('workingDirectory')` | `.ensure(agent, signal)` | 内置插件使用完全相同的签名 |
| `ctx.get('fs')` | `.resolve(path,{cwd,signal})`、`.readText(target,signal)`、`.stat(target,signal)` | `dsh-fs-local` 实现与 README 调用流程一致 |
| `exec.agent` / `exec.signal` | execute 第二个参数 | 内置工具（auto-review、worktree、agent-team 等）使用 |
| output schema | `{type:'object', additionalProperties:false, properties, required}` | `assertSupportedJsonSchema` 实测通过；`validateJsonSchemaValue` 对两种模式的样例输出 0 violations |

**与 rc.5 标准预设逐行对比**：

- 标准预设：22 行；本插件：23 行；
- 本插件新增/替换：`lean-skills`（group，替代标准的 `skill-filesystem` + `tool-skill`）、`lean-selfcheck`、`mcp-lean-lsp`；
- 其余共有行中：`persona`（预期承载 Lean 合同）、`compaction` 的 `tool-result-pruner` 阈值（16384/8192/2048 vs 标准 8192/4096/1024，文档说明为 Lean 诊断保留）不同；其余 18 行配置完全一致；
- 行顺序与标准保持一致，新增 MCP 行位于 `delegation` 之后、`tool-ask-user` 之前，不影响加载。

### 6.3 运行时接口核对（代码级）

- `verify/check_selfcheck.mjs` 的 24 次执行覆盖：正常两种模式、缺必需工具、出现禁用工具、模式不匹配、非法 config、fs 缺失、锁缺失等；全部通过；
- 本次额外用 rc.5 的 `assertSupportedJsonSchema` 校验插件 output schema：通过；用 `validateJsonSchemaValue` 校验两种模式的真实返回值：0 violations；
- `exec.agent`/`exec.signal`、`workingDirectory.ensure`、`fs.resolve/readText/stat` 的签名与 rc.5 内置用法一致；
- **唯一实质性 API 层问题是 `parameters: {}`**：raw register 不归一化，provider 收到空 schema。

### 6.4 已安装副本 vs 本仓库（只读比较）

安装形态：`profiles/desktop/package.json` 中

```text
"@local/dsh-lean-preset": "link:../../local-packages/lean-preset"
```

profile 的 `dsh.profile.bundles` 包含该包；`node_modules/@local/dsh-lean-preset` 是指向 `local-packages/lean-preset` 的链接。没有对 lean 预设的额外 profile patch 覆盖。

文件级对比（仓库 `preset/` vs 已安装目录）：

| 文件 | 字节差异 | 归一化后语义 |
|---|---|---|
| `index.js` | 有 | **不同（1 个 hunk：`parameters` 热修 + 注释）** |
| `cordis.patch.yml` | 有 | **不同（3 个 hunk：上游 URL 注释、技能路径写法、UV 镜像/超时环境变量）** |
| `package.json` | 仅行尾/末尾换行 | 相同 |
| `runtime-policy.json` | 仅行尾 | 相同（JSON 语义相等） |
| `README.md` | 仅行尾 | 相同 |
| `capabilities.js`、`icon.svg`、`locale/*.json` | 无 | 相同 |
| `skills/lean-formalization/SKILL.md` | 仅 CRLF | 相同 |

- **版本相同（都是 1.1.0），内容不同**；已安装副本的 `index.js` 是修复版，`cordis.patch.yml` 多了本地网络环境的 `UV_DEFAULT_INDEX` / `UV_HTTP_TIMEOUT`；
- 已安装的 `cordis.patch.yml` 注释仍指向 `lean-formalization`，说明它来自更早的本地构建，而不是当前公开仓库；
- 已安装副本的 10 个文件集合与仓库 `preset/` 完全同名同结构；`skills/lean-formalization/SKILL.md` 内容一致（仅 CRLF）；
- 技能路径解析：在真实 profile 中执行 `createRequire(profile/package.json).resolve('@local/dsh-lean-preset')` → `...\lean-preset\index.js`，`dirname + /skills` 存在且 SKILL.md 存在；用仓库根包模拟安装布局（临时 `node_modules/@local/dsh-lean-preset`）也得到 `...\preset\skills`，SKILL.md 存在。**两种安装形态的路径表达式都成立**。

### 6.5 兼容性结论

| 层次 | 结论 |
|---|---|
| 版本声明 | **兼容** |
| bundle 清单 / 组合补丁 / 包名 / 服务 / 配置字段 | **兼容** |
| LSP 运行时工具面 | **兼容**（固定 0.31.0，16 工具；真实 Lean 4.35.0-rc3 项目实测通过） |
| `lean_selfcheck` 运行时 | **风险**（`parameters` 空 schema；已安装副本有热修，仓库未回流） |
| Beam 运行时 | **未验收**（本机无法完成） |
| 已安装副本与仓库 | **不一致**（同版本号，2 个语义差异） |

**总体：部分兼容。** 对当前 Desktop（已安装热修副本）而言，LSP 模式很可能是可用的；但对“从本仓库 1.1.0 重新安装”的新环境而言，P0 schema 风险、未做 rc.5 Desktop 验收、以及 Beam 未验证，使“完全兼容”不成立。

---

## 7. 缺口与未完成工作（按优先级）

### P0

#### P0-1 回流 `parameters` 显式 schema 并重新做 rc.5 Desktop 验收

- **现状**：仓库 `preset/index.js` 使用 `parameters: {}`；已安装副本使用 `{type:'object',properties:{}}`，并记录了 rc.5 网关拒绝空 schema 的现场错误。仓库版本号仍为 1.1.0。
- **为什么值得做**：`lean_selfcheck` 随工具目录出现在每个模型请求中；一旦 provider 拒绝，整个会话在第一步之前失败。这不是“自检失败”，而是会话不可用。
- **建议做法**：
  1. 修改 `preset/index.js` 为显式对象 schema；
  2. 在 `verify/check_selfcheck.mjs` 增加 schema 形状断言；
  3. 在 DSH 0.2.1-rc.5 + `deepseek-official/deepseek-flash` 上新建 Lean 会话，实际调用一次 `lean_selfcheck`，记录输出与工具数；
  4. 发布 1.1.1，并把验收记录写入 `docs/acceptance.md`。
- **验收标准**：新会话首个请求成功；`lean_selfcheck` 返回 `mcpStatus=ready`；工具目录包含 `lean_selfcheck` 且请求无 `invalid_request_error`。

### P1

#### P1-1 发布版在 rc.5 上没有端到端 Desktop 验收

- **现状**：README/docs 只声明在 `0.2.1-rc.2` 上做过 Desktop 验收；当前运行的是 `0.2.1-rc.5`，且安装的是本地热修副本。`docs/acceptance.md` 的历史记录不能代表当前发布版。
- **为什么值得做**：rc.5 的 provider/工具 schema 路径已经发生变化；没有新会话验收就无法声称“支持 rc.5”。
- **建议做法**：增加一个可重复的 rc.5 验收清单（新会话 → `lean_selfcheck` → `lean_goal`/`lean_diagnostic_messages`/`lean_verify` → 记录工具数与输出），把结果写入 `docs/acceptance.md`；在 README 的 tested 版本中写明 rc.5。
- **验收标准**：报告包含日期、DSH/Lean 版本、真实命令/工具输出、失败项；不接受“CLI dump-config 通过”作为替代。

#### P1-2 Beam 运行时验收未完成，且本机不可完成

- **现状**：无 Beam 二进制/源码；`beam-detect` 返回 `Found=false`；无 cmake/VS；无目标 Lean 项目；`check_beam_activation.py` 明确是 mock；`set-mode` 在 Beam 缺参时 fail-closed。
- **为什么值得做**：Beam 是插件声明的第二种模式；没有 `lean_sync` 实测，无法声称项目兼容或证明 Beam 工作流可用。
- **建议做法**：按固定提交构建/获取 `lean-beam-mcp`；准备匹配工具链的 Lean 项目；运行 `set-mode.ps1 -Beam` 的真实 sync 探测并保存 `beam-probe.json`；在 `docs/acceptance.md` 单列 Beam 状态。在此之前 UI/文档继续标注“未验收”。
- **验收标准**：`beam_version` 的 source commit 匹配；`lean_sync` 返回版本/路径/诊断结构且无错误；`lean_run_at`/`lean_drop_workspace` 成功；失败时 rollback 生效。

#### P1-3 `check_gate_shell.py` 参数协议过期，验收阶梯红灯

- **现状**：9 个参数 vs gate 需要的 9 + 五组；已复现 ValueError；手工按真实协议调用退出 0。
- **为什么值得做**：它是 `acceptance.py` 的必需步骤；现在任何人运行 `acceptance.py` 都会看到 FAIL，真实的 gate 回归会被噪声掩盖。
- **建议做法**：修正测试调用参数（按 `gate/leancheck.sh:150` 的协议），断言 `LATEST.md` 与 `report.json`；或改为在 Linux CI 直接跑 `leancheck.sh`。
- **验收标准**：`python verify/check_gate_shell.py` 退出 0；`acceptance.py` 的 gate-shell 步骤为 0。

#### P1-4 已安装副本与仓库漂移，热修未回流

- **现状**：同版本 1.1.0，`index.js` 与 `cordis.patch.yml` 语义不同；已安装副本有 schema 修复和 UV 镜像/超时；仓库没有。
- **为什么值得做**：重新安装或升级会丢热修；版本号相同却行为不同，违反可复现/可审计；别人无法从仓库重建当前运行态。
- **建议做法**：把 schema 修复回流（必须）；把 UV 镜像/超时做成文档化的可选 env 或安装后配置；发布 1.1.1；在 `install.py --doctor` 或验收脚本中比较已安装副本与仓库的版本/内容指纹。
- **验收标准**：`doctor` 能报告“installed version / content hash / matches repo”；重新安装后 `lean_selfcheck` 仍正常。

#### P1-5 Lean LSP 的最低 Lean 版本未声明

- **现状**：`lean-lsp-mcp==0.31.0` 要求项目 Lean `>= 4.24`；本机默认 Lean 4.21 的 smoke 夹具上 `lean_file_outline/lean_goal/lean_diagnostic_messages` 全部返回 “Project toolchain is Lean 4.21; leanclient.aio requires >= 4.24”。README/docs 只写 Lean/elan。
- **为什么值得做**：用户按 README 在旧 Lean 项目上使用，MCP 会启动失败或工具不可用；这会被误认为插件故障。
- **建议做法**：在 README/`docs/dsh-kit.md`/troubleshooting 写明 `lean-lsp-mcp 0.31.0` 的最低 Lean 版本（实测 >=4.24），并给出升级 `lean-toolchain` 的方法；验收脚本增加一个受支持版本的 LSP smoke（类似本次的 4.35.0-rc3 探测）。
- **验收标准**：文档写明版本要求；CI/验收覆盖一个 >=4.24 的真实项目。

### P2

#### P2-1 `smoke.py` 的 gemini 硬编码期望

- **现状**：无 gemini CLI、fixture home 无 `~/.gemini` 时，安装器正确跳过 gemini，但 smoke 无条件要求 `GEMINI.md` / `.gemini/settings.json`，导致 23 项中 1 项失败。
- **为什么值得做**：环境相关失败会掩盖真正回归；用户会以为安装器坏了。
- **建议做法**：从 detected harness 计算期望文件；或在 fixture PATH 注入假 `gemini`；对未检测到的 harness 明确 skip。
- **验收标准**：干净机器上有/无 gemini 都能得到与检测结果一致的 PASS/SKIP。

#### P2-2 `acceptance.py` 的 LSP probe 未固定版本/禁用列表

- **现状**：步骤注释说 “the exact command the lsp-fallback configuration records”，实际执行 `uvx lean-lsp-mcp`（本次解析 0.33.0，20 工具），而预设固定 `==0.31.0`（16 工具）并禁用 6 个工具。
- **为什么值得做**：验收通过并不代表预设的真实工具面通过；上游版本漂移会让问题被掩盖。
- **建议做法**：从 `harnesses.json` 读取 command/disabledTools 生成 probe 参数；断言 serverInfo 版本与 16 个工具；与 `tools/probe_lean_mcp.py` 统一。
- **验收标准**：probe 日志显示 `0.31.0` 和 16 工具。

#### P2-3 `engines.dsh` 的 prerelease 边界

- **现状**：DSH 使用 `semver.satisfies(..., {includePrerelease:true})`，因此 `>=0.2.1-rc.2 <0.3.0` 会接受 `0.3.0-rc.1`。
- **为什么值得做**：0.3.x 可能包含 breaking change；范围声明过宽会放过未来 prerelease。
- **建议做法**：改为 `<0.3.0-0`，或按 minor 精确声明，并在 README 说明 tested 版本。
- **验收标准**：DSH 兼容判定对 rc.5 仍为通过，对 0.3.0-rc.1 为不满足。

#### P2-4 文档/安装入口不一致 + legacy 死代码

- **现状**：README 让安装“仓库根目录”；[`harnesses.json:259`](../harnesses.json:259) 和 BOOTSTRAP 写 `add <repo>/preset`；[`install/install.py:546`](../install/install.py:546) 的 `render_dsh_composition` 不再被调用，`dsh/preset/*` 仅被校验脚本使用。
- **为什么值得做**：两种安装都可用但语义不同（根包有 `engines.dsh`，嵌套没有）；死代码/旧模板会误导维护者与用户。
- **建议做法**：统一文档入口；删除或标注 `dsh/preset/` 与 `render_dsh_composition` 为 legacy；给嵌套 `preset/package.json` 也加 `engines.dsh`（或明确只支持根安装）。
- **验收标准**：README/BOOTSTRAP/harnesses.json 三处命令一致；`validate_repo` 不再依赖未使用模板。

#### P2-5 POSIX gate 的解释器选择

- **现状**：Git Bash 下 `python3` 命中 WindowsApps 占位符，脚本不校验就使用，导致 `unbound variable`；有效解释器下 gate PASS。
- **为什么值得做**：Windows 开发者用 Git Bash 时按脚本注释使用 POSIX gate 会直接失败；错误信息（unbound）也不指向真实原因。
- **建议做法**：候选解释器做 `-c 'import json'` 校验；Windows 上优先 `python`/`py` 并给出清晰错误；或在 MSYS 下提示使用 `leancheck.ps1`。
- **验收标准**：Git Bash 默认 PATH 下给出可操作的错误（而不是 unbound），有效解释器下 PASS。

#### P2-6 `tools/probe_lean_mcp.py` 无 CLI 参数，默认 20s 超时

- **现状**：该脚本没有 argparse，`--help` 会被当作运行；超时只能通过环境变量；冷启动/慢网下容易误报（本次首次运行 20s 超时）。
- **为什么值得做**：与 `verify/probe_mcp.py` 功能重叠但体验差；诊断时容易把“网络慢”误判为“服务坏”。
- **建议做法**：加 `--timeout`、`--package`、`--json`；或直接复用 `verify/probe_mcp.py`。
- **验收标准**：`--help` 正常；冷缓存下可配置超时。

#### P2-7 网络/PyPI 镜像问题未文档化

- **现状**：已安装副本专门加了 `UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple` 和 `UV_HTTP_TIMEOUT=30`，注释说明 pypi 直连/代理超时会让 DSH MCP 启动报 “initial connection or tool synchronization failed”；仓库没有这段，也没有文档。
- **为什么值得做**：在受限网络下，LSP 模式会 fail-closed 但用户不知道该改什么；这是“启动失败”的常见原因。
- **建议做法**：在 `docs/troubleshooting.md` 增加诊断/覆盖示例；评估是否默认提供镜像（需权衡供应链/可用性），或让用户在 profile patch 中覆盖。
- **验收标准**：文档给出可复制的 env 覆盖；probe 能在受限网络下稳定启动。

#### P2-8 没有 CI

- **现状**：仓库没有 `.github/workflows`；所有检查靠人工运行；`check_gate_shell.py` 的过期和 `smoke.py` 的环境假设都没有被自动发现。
- **为什么值得做**：这些正是 1.1.0 发布后才会暴露的问题；CI 能在每次变更时跑 `npm test`、`check_dsh_preset`、`check_beam_activation`、`check_gate_shell`、以及在 Linux 上跑 POSIX gate 的最小夹具。
- **建议做法**：加 GitHub Actions：Node/Python 矩阵；`npm test` + `check_dsh_preset` + `check_beam_activation` + `check_gate_shell`；smoke 在安装 Lean 的 job 中跑；gate-shell 在 Linux 上直接跑 `leancheck.sh`。
- **验收标准**：PR 上这些 job 为 required；失败可定位到脚本。

---

## 8. 未观察 / unknown 清单

按 `contract.md` 的要求，以下项目本次**没有观察到**，不能标记为 passed：

1. **真实 DSH Desktop 新会话**（加载预设、调用 `lean_selfcheck`、provider 请求）——受“只读、不改 profile、不启动会写入 dsh-home 的会话”约束，未执行。
2. **从 GitHub URL 安装**（`dsh plugin add github:...#v1.1.0`）——未执行；只做了本地包边界/解析验证。
3. **Beam 运行时**——无二进制；未执行。
4. **POSIX gate 在真实 Linux/macOS 上**——只在 Git Bash 上用有效 `python3` 垫片验证过；原生 Linux 未测。
5. **其他 harness 的真实安装**（Claude Code/Codex/OpenCode/Gemini/Cursor/VS Code）——只跑了 `--doctor`，未写入任何配置。
6. **数学证明验收 / 独立语义复核**——不在本次范围；gate 只在 smoke 的玩具定理上验证流程，不代表任何真实数学结论。
7. **密钥/凭据**——未读取、未输出。
8. **rc.5 上发布版 `parameters` 故障的现场复现**——未启动会话/未发 provider 请求；结论基于代码路径与已安装副本注释，属于高置信推断。

---

## 附录 A — 关键命令与输出摘录

### A.1 `npm test`

```text
harnesses     : 10 (tier 1: 7)
skills        : lean-beam, lean-formalization
mcp servers   : lean-lsp, lean-beam
note          : workbuddy is tier 2 ...
repository validation: OK
PASS selfcheck: 24 module executions, both modes, output schema and fail-closed errors
PASS public package: root/nested resolution, isolated skills, ESM entry, no install hooks
```

### A.2 固定版本 MCP 探测

```text
lean-lsp   OK   16    Lean LSP
serverInfo {'name': 'Lean LSP', 'version': '0.31.0'}
```

### A.3 真实 Lean 4.35.0-rc3 内环

```text
lean_file_outline: isError=False ... total_declarations
lean_goal: isError=False ... "goals": ["⊢ True"]
lean_diagnostic_messages: isError=False ... "success": true, "items": []
```

### A.4 Beam 探测

```json
{"Found": false, "Command": null, "Kind": null, "Detail": null, "Candidates": []}
```

### A.5 版本兼容

```text
dsh-lean-plugin/package.json -> COMPATIBLE (no unmet requirements)
lean-preset/package.json     -> COMPATIBLE (no unmet requirements)
```

### A.6 已安装副本 vs 仓库

```text
index.js            byte-equal=False   semantic: 1 hunk (parameters hotfix)
cordis.patch.yml    byte-equal=False   semantic: 3 hunks
package.json        semantic-equal=True (line endings)
runtime-policy.json semantic-equal=True (line endings)
capabilities.js / icon.svg / locale/*.json  byte-equal=True
skills/lean-formalization/SKILL.md  normalized-equal=True (CRLF only)
```

---

## 附录 B — `cordis.patch.yml` 引用的 `@deepseek-ai/*` 包（31 个，rc.5 全部存在）

```text
dsh-agent-preset, dsh-persona, dsh-agent-instructions, dsh-time-context,
dsh-tool-bash, dsh-tool-pwsh, dsh-tool-fs, dsh-tool-fs-search,
dsh-tool-jobs, dsh-tool-schedule, dsh-skill, dsh-skill-filesystem,
dsh-tool-skill, dsh-command-goal, dsh-tool-goal, dsh-plan-mode,
dsh-compaction-basic, dsh-command-compact, dsh-compaction-tool-result-pruner,
dsh-tool-subagent-control, dsh-tool-subagent-control/list-agents,
dsh-tool-subagent, dsh-workflow-ptc, dsh-tool-workflow, dsh-mcp-client,
dsh-tool-ask-user, dsh-tool-todo, dsh-tool-web, dsh-tool-present,
dsh-plugin-manager/tools, dsh-plugin-market/tools
```

另：`cordis:group`（内置）、`@local/dsh-lean-preset`（本地包，不在 asar 内，profile 链接解析成功）。

---

## 附录 C — 清理与复现说明

- 本次新增的唯一仓库文件是本报告；测试产生的 `evidence/`、`.smoke/`、`.uv-probe/`、`__pycache__/` 已清理。
- `D:\dsh-tmp` 下的构建/探测临时目录（ZIP、tarball、uv cache、Lean 探测项目等）已清理。
- 关键复现命令（需要在允许写入的环境执行）：

  ```bash
  npm test
  python verify/check_gate_shell.py          # 预期当前失败，见 P1-3
  python verify/check_dsh_preset.py
  python verify/check_beam_activation.py     # 仅 mock
  python verify/provenance_recheck.py
  python verify/smoke.py --with-gate --work D:/dsh-tmp/smoke-work
  python install/install.py --doctor
  python verify/probe_mcp.py --command "uvx lean-lsp-mcp==0.31.0" \
    --env LEAN_LOG_LEVEL=NONE \
    --env "LEAN_MCP_DISABLED_TOOLS=lean_build,lean_run_code,lean_get_widgets,lean_get_widget_source,lean_completions,lean_code_actions" \
    --expect lean_goal --expect lean_diagnostic_messages --expect lean_local_search \
    --expect lean_multi_attempt --expect lean_verify --timeout 300
  python verify/acceptance.py                # 当前预期 FAIL（见第 4 节）
  ```

- 环境相关注意：
  - uv 缓存/工具目录在受限环境请用 `UV_CACHE_DIR` / `UV_TOOL_DIR` 指向可写目录；
  - Git Bash 的 `python3` 可能是 WindowsApps 占位符，必要时用有效解释器或直接使用 PowerShell gate；
  - lean-lsp 需要 Lean `>= 4.24` 的项目工具链。

---

*报告结束。所有未观察项均按 `unknown` 处理；没有把 mock、配置生成或工具目录当作 Beam 运行或数学证明验收的证据。*

---

## 修复记录（2026-11-18）

> 本节记录上一轮报告 P0-1 的修复与验证；第 7 节 P0-1 的“现状”以本节为准。

### 修复范围

只修复 **P0-1：`lean_selfcheck` 的 `parameters` 空 schema**。没有搬入已安装副本中的 UV 镜像/超时等其它本地差异，也没有修改 DSH profile、已安装副本或 `D:\deepseekharness`。

### 修改的文件

| 文件 | 改动 | 说明 |
|---|---|---|
| [`preset/index.js`](../preset/index.js) | `parameters: {}` → `parameters: { type: 'object', properties: {} }`，并加注释说明 raw `ctx.tools.register()` 不会做 `parameterSchemaSpecToJsonSchema` 归一化 | 与只读参考的本机已安装副本一致；这是本次唯一的功能修复 |
| [`verify/check_selfcheck.mjs`](../verify/check_selfcheck.mjs) | 在 `apply(ctx)` 后新增 3 条断言：`parameters.type === 'object'`、`properties` 是对象、不是数组 | 防止未来生成/复制/编辑把它改回 `{}` |
| `docs/acceptance-report-2026-11-18.md` | 本节 | 记录修复前/后基线、DSH 离线验证与未做项 |

`preset/index.js` 的 SHA-256：

| 时点 | SHA-256 |
|---|---|
| 修复前（`git show HEAD:preset/index.js`） | `3431b8f9a2d2608b5fefbecbf79a37bc740291f1041d40f0f43c82800bde9925` |
| 修复并重新生成后 | `84a57f563c8f33dc1d3f8412f9bd513917a015e2c20b36d2e70bb231238f4f70` |

### 生成 / 复制 / 校验链路核查

- **生成器不生成 `index.js`**：`tools/build_lean_preset.py` 只写 `preset/cordis.patch.yml`、`preset/runtime-policy.json` 和 `preset.persona.expected.txt`（persona 期望文件，已被 `.gitignore` 忽略）；`tools/package_lean_preset.py` 只是复制 `preset/` 树；`dsh/preset/agent.cordis.yml.tmpl` 不包含 selfcheck 的 `parameters`。全仓库检索确认只有 `preset/index.js` 定义该字段。
- **重新生成后 schema 保留**：运行 `npm run build:preset` 后，`preset/index.js` 的 SHA-256 仍为 `84a57f56…`，`grep` 仍为显式 schema；生成器重写了 `runtime-policy.json`（内容相同，但为 CRLF），已按仓库 LF 约定恢复，最终 `git diff` 中没有该文件。
- **打包链路**：重新执行 `tools/package_lean_preset.py` + `verify/check_package.py`，ZIP（82 payload 文件）通过哈希/解包/可移植性检查；解包后的 `preset/index.js` 含显式 schema。
- **Provenance 账本**：`skills/PROVENANCE.md` 的 12 行哈希只覆盖 vendored `lean-beam` 内容与两份 license；`preset/index.js` 是自有代码，不在账本中，因此无需新增/更新哈希行。`verify/provenance_recheck.py` 为 `ledger rows: 12, mismatches: 0`，`node verify/validate_repo.mjs` 仍为 OK。
- **临时产物**：`preset.persona.expected.txt` 等生成物已删除；`evidence/`、`.smoke/`、`.uv-probe/`、`__pycache__/` 与 `D:\dsh-tmp\p0-fix` 在记录完成后清理。

### 修复前后命令结果

| 命令 | 修复前 | 修复后 |
|---|---|---|
| `npm test` | 0（24 次 selfcheck 执行） | 0（24 次 + 新增 3 条 schema 断言） |
| `python verify/check_dsh_preset.py` | 0（两模式 + 三类回归拒绝） | 0（同上） |
| `python verify/provenance_recheck.py` | 0（12 行，0 mismatch） | 0（12 行，0 mismatch） |
| `python verify/acceptance.py` | **1**；失败 required：`smoke`（gemini 环境）、`gate-shell`（测试参数过期） | **1**；同样的两个已知失败，`validate-repo`/`provenance`/`probe-lean-lsp`/`doctor` 均 0 |
| `node verify/check_selfcheck.mjs`（负向验证：临时副本中把 schema 改回 `{}`） | — | **1**，断言按预期失败：`parameters.type` actual `undefined`, expected `'object'` |
| `tools/package_lean_preset.py` + `verify/check_package.py` | （上一轮已通过） | 0，ZIP 内含显式 schema |
| `install/install.py --doctor` | 0（DSH `installed`） | 未重复运行（本次未改安装面） |

修复前的 `acceptance.py` 失败与上一轮报告一致，不是本次改动引入；`smoke` 的 gemini 与 `gate-shell` 的参数协议问题仍是 P1/P2 缺口，本次没有削弱或绕过任何断言。

### DSH 0.2.1-rc.5 离线验证（不是端到端会话验证）

使用 `ELECTRON_RUN_AS_NODE=1` 调用 DSH 自带包（`@deepseek-ai/dsh-tools`、`@deepseek-ai/dsh-app-boot`）对同一插件的 `parameters` 做对照；临时脚本位于 `D:\dsh-tmp\p0-fix`，只读加载仓库与已安装副本，不写 DSH 目录。

| 检查 | 修复前 `{}` | 修复后 `{ type: 'object', properties: {} }` |
|---|---|---|
| `dsh-tools.assertObjectJsonSchema(parameters)` | **REJECT**：`schema.type must be "object" (structured output is object-rooted)` | **ACCEPT** |
| `dsh-tools.assertSupportedJsonSchema(parameters)` | ACCEPT（说明原来的 output 校验不会拦住这个错误） | ACCEPT |
| `dsh-tools.parameterSchemaSpecToJsonSchema({})`（`defineTool` 对无参工具的规范化结果） | `{"type":"object","properties":{}}` | 与修复值完全一致（`same shape ... true`） |
| provider wire 形态（`dsh-llm-deepseek` 映射 `input_schema: tool.parameters`） | `input_schema: {}` | `input_schema: {"type":"object","properties":{}}` |
| 与已安装参考副本比较 | 不同 | **相同** |
| `dsh-app-boot.evaluatePluginCompatibility(repo, {}, '0.2.1-rc.5')` | `COMPATIBLE` | `COMPATIBLE` |

**边界**：以上是 DSH 代码路径的离线验证，证明“修复后的形状 = DSH 自己对无参工具生成的规范形状”，且 DSH 的对象根 schema 校验器接受它、拒绝旧值。它**不是**真实会话端到端验证：要确认 provider 请求不再报错，必须把仓库版本安装进 profile 并新建会话（会写入 dsh-home、需要 live provider），本次按只读约束未做。P0-1 的代码级原因已修复，但“真实会话确认”仍归入 P1-1 的后续验收。

### 修复结论

- P0-1 的**代码/生成/打包/校验链路已修复**：仓库源码、重建产物、ZIP 与 DSH 离线 schema 校验均为显式对象 schema；新增断言能在旧值上失败。
- 已安装副本无需改动（它本来就有该热修）；UV 镜像/超时等其它差异未搬入。
- **未完成**：真实 DSH 会话端到端确认（需要安装/新会话，超出只读约束）；`acceptance.py` 仍按已知的 smoke/gate-shell 问题报 FAIL，本次如实保留。

*修复记录结束。*

---

## 修复记录（第二轮，2026-11-18）

> 本节记录 `verify/smoke.py` 的 gemini 环境误报与 `verify/check_gate_shell.py` 的参数协议修复；产品代码（`preset/`）本轮未改动。

### 1. `verify/smoke.py`：按实际检测到的 harness 计算期望文件

**修复前**：期望文件是硬编码的 union，无条件包含 `GEMINI.md` 与 `home/.gemini/settings.json`；本机没有 `gemini` 可执行文件（fixture home 也没有 `~/.gemini`），安装器正确跳过 gemini，但测试仍要求这两个文件 → 23 项中 1 项失败。

**修复后**：

- 从安装器自己的报告行 `harnesses : ...` 读取它实际配置的 harness；报告行缺失时显式 FAIL，而不是当作“没有 surface 要检查”。
- 新增 `expected_install_files()`：按 [`harnesses.json`](../harnesses.json) 的 instructions / skillRoots / MCP `file-json`/`file-toml` targets 计算所选 harness 的期望文件；gate scaffold 文件（`lean-formalization.json`、`LeanAudit.lean`、`LeanScan.lean`、`scripts/leancheck.ps1`、manifest）与 harness 无关，始终检查。
- 新增 `Checker.skip()`：未检测到的 tier-1 harness 输出 `SKIP harness gemini-cli surfaces — not detected in the fixture; its files are not required`，SKIP 单独计数，不当作 PASS，也不当作 FAIL。
- 顺带把 `home/.codex/config.toml` 的 TOML 解析改为仅在该文件存在时执行，避免在未检测到 Codex 的机器上因文件不存在而抛异常；这不是削弱检查，而是让“未检测到的 harness 不产生要求”。
- 本机 fixture 实际选中：`dsh, claude-code, codex, opencode, cursor, vscode`；`gemini-cli` 明确 SKIP；动态期望文件 39 个（原硬编码 19 个，覆盖面反而扩大）。

**结果**：`smoke --with-gate` 从 **23 checks / 1 failed** 变为 **25 checks / 0 failed / 1 skipped**，退出 0。

### 2. `verify/check_gate_shell.py`：判断与修复

**判断：测试过期，不是 gate 回归。** 依据：

- [`gate/leancheck.sh:150`](../gate/leancheck.sh:150) 是生产调用点，协议为 9 个位置参数 + `STEP_NAMES -- STATUSES -- STEP_SECONDS -- ALLOWED -- TARGETS` 五组；
- [`gate/leancheck.ps1`](../gate/leancheck.ps1) 没有内嵌 Python，是独立的 PowerShell 实现；
- `install/install.py` 只是把 `gate/leancheck.ps1` / `leancheck.sh` 原样复制到项目（见 [`install/install.py:642`](../install/install.py:642)），不存在另一种调用协议；
- 文档（`docs/`、README、AGENTS）没有定义过测试里那种 9 参数简写；
- git 历史只有一个发布提交（`1f85894`），无法用 diff 追溯；但生产 gate 在 `smoke --with-gate` 的真实 Lean 构建/审计中通过，POSIX gate 用有效 `python3` 在夹具上也 `leancheck: PASS`，且旧测试的 config-reader 块本身通过——失败只发生在测试给白名单块少传了五组数据时。

**修复**：按 gate 的真实协议调用同一个内嵌 Python 块，并新增/保留断言：

- 白名单内目标退出 0；
- `report.json` 存在且 `ok: true`、`lockWritten: true`、`lockState` 以 `written` 开头；
- `report.md` 与 `LATEST.md` 均已写出；
- 白名单外公理退出 1，且输出包含 `outside the whitelist`；
- 未上报目标退出 1，且输出包含 `target not reported`；
- 新增“锁定的命题被改写”场景：退出 1，且输出包含 `locked statement changed`，同时 `report.json` 记录 `ok:false`。

**结果**：从 **2 项失败 / 退出 1** 变为 **10 项 PASS / 退出 0**。

### 3. 可选 POSIX gate 解释器问题：本轮不改

`verify/acceptance.py` 在本机不运行 `gate/leancheck.sh`（它跑 `check_gate_shell.py` 的静态块，smoke 跑 PowerShell gate），所以该问题不是 acceptance 通过的必要条件。按任务约定，本轮保持 `gate/leancheck.sh` 不动；上一轮报告 P2-5 的“WindowsApps `python3` 占位符导致 unbound variable”仍然存在，作为独立缺口留待后续（建议：候选解释器做 `python3 -c "import json"` 校验，或优先 `python`）。

### 4. 修复前后测试结果

| 命令 | 修复前 | 修复后 |
|---|---|---|
| `npm test` | 0 | 0 |
| `python verify/check_dsh_preset.py` | 0 | 0 |
| `python verify/provenance_recheck.py` | 0（12 行，0 mismatch） | 0（12 行，0 mismatch） |
| `python verify/smoke.py --with-gate --work <tmp>` | **1**：23 checks，1 failed（gemini 文件） | **0**：25 checks，0 failed，1 skipped（gemini-cli） |
| `python verify/check_gate_shell.py` | **1**：2 项失败（参数协议过期） | **0**：10 项 PASS |
| `python verify/acceptance.py` | **1**：FAILED required steps: smoke、gate-shell | **0**：PASS；所有 10 个步骤 exit 0 |

修复后 `acceptance.py` 步骤：`validate-repo 0`、`smoke 0`、`gate-shell 0`、`provenance-recheck 0`、`probe-lean-lsp 0`、`doctor 0`、`install-for-harness-probe 0`、`claude-mcp-list 0`、`codex-mcp-list 0`、`opencode-mcp-list 0`；证据目录 `evidence/20261118T110313Z-868fd8/`（清理前）。

### 5. 未改变/未完成项

- Beam 运行时仍是 mock-only（`check_beam_activation.py`），本轮未做真实 Beam。
- DSH 真实会话端到端验收未做（只读约束），P0-1 的 live 确认仍归 P1-1。
- `acceptance.py` 的 `probe-lean-lsp` 仍使用未固定版本的 `uvx lean-lsp-mcp`（本次通过，但版本漂移仍是 P2-2）。
- 未修改 `gate/` 产品脚本、`preset/` 产品代码、DSH profile/已安装副本；未读凭据。
- 仓库内临时产物（`evidence/`、`.smoke/`、`.uv-probe/`、`__pycache__/`）与 `D:\dsh-tmp\fix2` 已清理。

*第二轮修复记录结束。*

---

## 修复记录（第三轮，2026-11-18）

> 本节记录 P2-5：`gate/leancheck.sh` 在 Git Bash 下把 `%LOCALAPPDATA%\Microsoft\WindowsApps` 的 Store 别名当作可用 `python3`。只改解释器发现与对应测试；`leancheck.ps1` 没有 Python 发现逻辑，未改。

### 1. 修复内容（`gate/leancheck.sh`）

- 不再只信 `command -v`：每个候选实际执行
  `-c 'import sys; print(sys.executable) if sys.version_info.major == 3 else sys.exit(1)'`；
  探测失败、空输出、非 Python 3 都被拒绝。
- 两条路径都检查 `Microsoft\WindowsApps`（大小写不敏感、兼容 `/` 与 `\`）：
  1. `command -v` 解析到的命令路径；
  2. 成功探测后 `sys.executable` 的真实路径。
- 候选顺序：`python3` → `python` → `py -3`（Windows 回退）；真实 `python3` 仍优先。
- 找不到可用解释器时退出 2，并区分：
  - 检测到 WindowsApps 占位符：列出解析到的路径，说明安装真实 Python 3/把真实解释器放在 PATH 前面；
  - 完全没有解释器：说明安装 Python 3；
  - 两者都提示 Windows 上可改用 `pwsh -File scripts/leancheck.ps1`。
- 更新了顶部注释与 `--help` 的 `sed` 行范围（注释变长后仍输出完整 Usage）。
- 解释器命令用 Bash 数组 `"${PYTHON[@]}"` 调用，兼容 `py -3` 这种两词命令；三处调用点已同步。

### 2. 测试（`verify/check_gate_shell.py`）

在原有 10 项 gate-shell 覆盖之上，新增从 `gate/leancheck.sh` 的 `# >>> python-discovery` 标记中**提取真实探测块**（不是复制逻辑）的 7 项测试：

1. PATH 中 `python3` 是返回 WindowsApps 路径的假 Store 存根、`python` 是真实解释器 → 跳过存根，选择 `python`；
2. 候选本身位于 `microsoft/windowsapps` 目录（小写，验证大小写/分隔符）→ 在探测前按路径拒绝；
3. 候选无法运行（exit 1）→ 拒绝并报 `probe failed`；
4. 真实 `python3` + 后面的存根 `python` → 仍优先 `python3`；
5. 只有 WindowsApps 存根 → 退出 2，错误含 `WindowsApps` 与 `leancheck.ps1` 指引；
6. PATH 完全没有解释器 → 退出 2，错误含 `no usable Python 3` / `install Python 3`，且不误报 WindowsApps；
7. 只有 `py` 启动器 → 选择 `py -3`。

若测试环境没有可用的原生 bash，该组测试打印 SKIP（本机与 Linux CI 均有 bash，不跳过）；其余 gate-shell 断言未削弱。

**bash 选择补修（同日）**：Windows 上 `shutil.which("bash")` 可能返回 `C:\Windows\System32\bash.exe`（WSL 入口，无法执行 Windows 临时路径），也可能返回 WindowsApps 的 `bash.exe` 别名。测试改为在 Windows 上优先使用 Git Bash（`ProgramFiles`/`ProgramFiles(x86)`/`%LOCALAPPDATA%\Programs\Git` 的 `bin\bash.exe`、`usr\bin\bash.exe`，以及 PATH 中的 Git Bash），明确排除 `System32\bash.exe`、`WindowsApps\bash.exe`，并用“执行一个位于 Windows 路径的脚本”探测确认可用后才选用。默认 `python`/PowerShell PATH（System32 优先）下 17 项全绿，选中的是 `C:\Program Files\Git\bin\bash.exe`；补修后 `acceptance.py` 复跑仍 PASS（`evidence/20261118T115317Z-be8b82`）。

### 3. 修复前后结果

| 命令 | 修复前（基线） | 修复后 |
|---|---|---|
| `python verify/check_gate_shell.py` | **0**（10 项 PASS，但未覆盖解释器发现） | **0**（17 项 PASS） |
| 默认 Python / PowerShell PATH（System32 优先）下 `check_gate_shell.py` | — | **0**（17 项 PASS；自动选用 `C:\Program Files\Git\bin\bash.exe`，跳过 WSL/WindowsApps） |
| 旧发现逻辑演示 | `command -v python3` 选中 WindowsApps；`python3 -c "import sys; print(sys.executable)"` 返回空、rc=49 | 实际探测后拒绝，回退到真实 `python` |
| `bash gate/leancheck.sh`（只有 WindowsApps 的 PATH） | — | 退出 2，明确打印 `Microsoft\WindowsApps (Store placeholder)` 与处理建议 |
| `bash gate/leancheck.sh`（本机默认 PATH） | — | 跳过占位符，使用真实 `python`；到达 config 检查（空 targets 时退出 2） |
| 完整 POSIX gate（Lean 4.21 夹具 + 真实 python3 垫片） | — | `build` / `axiom-audit` / `library-scan` 全部 0，`leancheck: PASS` |
| `npm test` | 0 | 0 |
| `python verify/check_dsh_preset.py` | 0 | 0 |
| `python verify/provenance_recheck.py` | 0（12 行） | 0（12 行） |
| `python verify/smoke.py --with-gate` | 0（25 checks，1 skipped） | 0（25 checks，1 skipped） |
| `python verify/acceptance.py` | 0（第二轮已通过） | **0**（PASS；所有步骤 exit 0，见下方说明） |

**acceptance 运行说明**：本轮第一次 `acceptance.py` 在 `probe-lean-lsp` 步骤因 uv 冷缓存下载超过 300s 超时而失败（`evidence/20261118T113631Z-ec8884`）；按同一命令预热 `.uv-probe` 缓存后，重跑 `acceptance.py` **PASS**（`evidence/20261118T114447Z-f0f34d`）。这是网络/缓存时序问题，不是本次 gate 改动导致；未修改 acceptance 断言或超时来“绕过”。

### 4. 未改 / 未完成

- `gate/leancheck.ps1` 没有解释器发现逻辑（grep 无 `python` 调用），不需要对齐。
- 未改 `preset/`、`verify/smoke.py`、`verify/check_selfcheck.mjs`、DSH profile、已安装副本；未读凭据。
- 仓库临时产物（`evidence/`、`.smoke/`、`.uv-probe/`、`__pycache__/`）与 `D:\dsh-tmp\fix3`、`D:\dsh-tmp\fix4` 已清理（本记录写完后执行）。

*第三轮修复记录结束。*
