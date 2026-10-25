# DSH Lean 插件 1.1.0

解压 `dsh-lean-plugin-1.1.0.zip` 后进入同名目录。可安装的 DSH bundle 是仓库根目录，也保留
`preset/` 子目录安装入口，包名保持 `@local/dsh-lean-preset`，界面预设保持「Lean证明助手」。
这是预设、技能、探测器和验收脚本的组合包；Lean、mathlib、uv、DSH 和 Beam
原生运行时需要单独准备。默认模式为 `lsp-fallback`。

## 能力分工

| 能力 | `lsp-fallback` | `beam` |
|---|---|---|
| 目标、诊断、导航 | lean-lsp | Lean Beam |
| 不改文件的战术试探 | `lean_multi_attempt` | `lean_run_at` / handles |
| 本地及远程库检索 | lean-lsp | lean-lsp |
| 公理、依赖和性能预检查 | lean-lsp（仅辅助） | lean-lsp（仅辅助） |
| 写入证明源码 | DSH 文件编辑工具 | DSH 文件编辑工具 |
| 最终验收 | 项目 leancheck + 独立语义复核 | 项目 leancheck + 独立语义复核 |
| 暴露的技能 | lean-formalization | lean-formalization + lean-beam |

模式策略的唯一来源为 `harnesses.json`。`preset/runtime-policy.json` 是生成副本，
`lean_selfcheck` 用它核对当前会话工具和项目模式。Beam 模式关闭 LSP 的目标、诊断、
导航和 `lean_multi_attempt`，保留搜索与辅助分析。两种模式均关闭 LSP 的
`lean_build` 和 `lean_run_code`；完整构建由项目 gate 负责。

## 先使用 LSP 模式

准备 Python 3.11+、PyYAML 6.x、Node.js、Lean/elan、ripgrep 和 uv/uvx。
生成的预设从 `%USERPROFILE%\.local\bin\uvx.exe` 启动
`lean-lsp-mcp==0.31.0`；首次启动需要可用的包缓存或网络。
先在待工作的 Lean 项目安装 gate（已有 gate 时保留并检查原有配置）：

```powershell
python install/install.py --project E:\my-project --scope project --harnesses dsh --no-mcp
```

检查项目的 `lean-formalization.json`：库名、目标、入口模块、公理白名单和扫描范围
必须对应真实项目。空目标列表不会通过验收。随后显式选用 fallback：

```powershell
pwsh -NoProfile -File tools/set-mode.ps1 -Fallback -Project E:\my-project
```

脚本在临时目录生成并验证 bundle，备份原 bundle 和项目配置，然后更新两者的模式。
备份保留在 `mode-backups/<时间>/`，`restore.json` 记录原路径。仅切换 `mode`，
保留目标和其他配置；不会自动生成或重写题目锁。

在 **DSH Desktop** 的插件管理中添加解压后的仓库根目录本地 bundle。
已有同名插件时使用其本地更新/重载流程。重启 Desktop 并新建「Lean证明助手」会话，
工作目录设为上面的 Lean 项目。不要沿用旧会话的工具状态。
Desktop 管理的 profile 不能用 CLI `--dump-config` 代替 UI 验收。
普通 CLI profile 可用 `dsh plugin --profile <名称> add <解压目录>` 安装。

首个请求可以直接使用：

> 调用 lean_selfcheck，确认 presetMode 与 gateMode 都是 lsp-fallback、
> mcpReady=true、leanBeamTools=0。加载 lean-formalization 技能。
> 用绝对 file_path 在已有目标文件上调用 lean_goal、lean_diagnostic_messages，再做一次 lean_verify。
> 报告真实结果，不修改题意，不把自检当作证明验收。

最终按项目 gate 的说明检查题意、锁定目标并运行 `scripts/leancheck.ps1`。
自检的 `gateStatus=ready` 只表示配置和锁文件可读取；不表示 gate 已执行或通过。

## 启用 Beam 模式

运行时和随包技能绑定到同一个上游提交：
`753f32ffb74aeb21e390fdc1267aa1dc1dd83a53`。
包内没有 Beam 原生二进制，必须准备能服务目标项目 Lean 工具链的固定版本。
Windows 原生构建接口与 SDK 要求见该提交的
[TOOLCHAIN_BUNDLING.md](https://github.com/leanprover/lean-beam/blob/753f32ffb74aeb21e390fdc1267aa1dc1dd83a53/docs/TOOLCHAIN_BUNDLING.md)。

参考构建步骤如下，路径需替换为实际 SDK 与**完整的独立 Lean 安装副本**；
运行这些步骤前应按上游文档准备完整 clang/Windows SDK。此步骤未在本次套餐制作中执行。

```powershell
git clone https://github.com/leanprover/lean-beam.git E:\beam-source
git -C E:\beam-source checkout --detach 753f32ffb74aeb21e390fdc1267aa1dc1dd83a53
Set-Location E:\beam-source
cmake -DLEAN_PREFIX="E:/lean-sdk" -P scripts/build-toolchain.cmake
cmake -DLEAN_PREFIX="E:/lean-sdk" -DPREFIX="E:/lean-sdk" -P scripts/install-toolchain.cmake
```

回到套餐目录，退出旧 Lean 会话后，对项目中的一个真实 `.lean` 文件做启用探测：

```powershell
pwsh -NoProfile -File tools/set-mode.ps1 -Beam `
  -Project E:\my-project -ProbeFile MyLib\Basic.lean `
  -BeamCommand E:\lean-sdk\bin\lean-beam-mcp.exe
```

脚本依次检查 MCP 握手、必需工具、`beam_version` 的源码提交与运行状态，
再实际调用该项目文件的 `lean_sync`，验证文档版本、路径、工作区、诊断结构及输入哈希，
最后释放工作区。任何失败都阻止切换。成功记录位于对应备份目录的 `beam-probe.json`。
它只证明这个项目、这个文件的同步兼容性；诊断、最终 gate、独立复核和 Desktop 验收
各有独立状态。

重新加载 bundle、新建会话后，先 `lean_selfcheck`，再 `beam_version`、`lean_sync`。
Beam MCP 自己管理会话，不要另启 CLI `serve`。每次源码编辑后重新 sync/update，
只使用返回的版本和有效句柄。执行最终构建前 drop workspace 并等待清理。
LSP 本地检索须显式传入 `project_root`，两台服务不共享隐式项目状态。

遇到 Beam 不兼容时停止该会话，用前述 `-Fallback -Project ...` 命令显式切回，
再启动新会话。`-DryRun` 仅展示计划，不运行探测，也不声明准备就绪。

## 核验套餐

ZIP 旁的 `.zip.sha256` 校验整体文件，包内 `MANIFEST.json` 列出每个文件的 SHA-256。
仅生成或结构验证 Beam 配置不算实际运行。使用以下检查重放套餐的代码验证：

```powershell
node verify/validate_repo.mjs
node verify/check_selfcheck.mjs
python verify/check_dsh_preset.py
python verify/check_beam_activation.py
python verify/smoke.py --with-gate
python install/install.py --doctor
```

`check_beam_activation.py` 使用模拟传输验证控制器与回滚；它不能验证真实 Beam。
`smoke.py --with-gate` 使用真实 Lean 验证安装与 gate，与 Beam 运行验收分开记录。
本次制作的实测记录见 `docs/dsh-kit-validation.md`。
