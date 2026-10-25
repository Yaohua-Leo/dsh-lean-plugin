# DSH Lean 证明助手插件

在 DSH 中新增「Lean证明助手」预设，组合 Lean MCP 工具、隔离的工作流技能、
模式自检和项目验收脚本。插件标识保留为 `@local/dsh-lean-preset`，预设 ID 为 `lean`。

## 安装

在 **DSH Desktop → 插件管理** 中添加：

```text
github:Yaohua-Leo/dsh-lean-plugin#v1.1.0
```

独立 CLI profile 可使用：

```powershell
dsh plugin --profile lean-demo add github:Yaohua-Leo/dsh-lean-plugin#v1.1.0
```

也可以克隆后添加仓库根目录：`dsh plugin --profile lean-demo add ./dsh-lean-plugin`。
根目录已经提供 DSH bundle 入口；生成的 JavaScript 与配置直接入库，安装时无需执行构建。
Release 附带可安装 `.tgz`、完整源码套餐 `.zip` 和校验文件。

安装后重启 DSH，在真实 Lean 项目目录新建「Lean证明助手」会话，首先调用
`lean_selfcheck`。Desktop profile 由桌面端管理，不能用 CLI dump-config 代替验收。

依赖：DSH（声明支持 `>=0.2.1-rc.2 <0.3.0`，实测为 0.2.1-rc.2）、Lean/elan、
ripgrep、uvx。预设从 `~/.local/bin`（Windows 为 `%USERPROFILE%\.local\bin\uvx.exe`）
启动固定的 `lean-lsp-mcp==0.31.0`。生成与切换脚本需要 Python 3.11+、PyYAML 6.x。

## 两种模式

| 能力 | 默认 LSP 模式 | Beam 模式 |
|---|---|---|
| 目标、诊断、导航 | lean-lsp | Lean Beam |
| 战术试探 | lean_multi_attempt | lean_run_at / handles |
| 库检索与辅助预检查 | lean-lsp | lean-lsp |
| 技能 | lean-formalization | 再增加 lean-beam |
| 最终验收 | 项目 gate 与独立语义复核 | 项目 gate 与独立语义复核 |

`harnesses.json` 是策略唯一来源。自检会比对会话工具、预设模式和项目模式；
后端缺失或模式不一致时停止工作，不在证明中途静默切换。

完整步骤见[项目配置与切换指南](docs/dsh-kit.md)。切换 Beam 前必须用固定版本运行时
实际同步目标项目中的 Lean 文件，通过后才更新配置，并保留备份和失败回滚。
切换模式请使用本地仓库副本并重新加载本地 bundle。

**插件不包含 Beam 原生二进制，真实 Beam 运行验收尚未进行。** 模拟测试及配置生成
不算 Beam 实测。`lean_selfcheck` 和 LSP 辅助审计也不代表数学证明验收完成。

## 验证与开发

```powershell
python -m pip install 'PyYAML>=6,<7'
npm run build:preset
npm test
python verify/check_dsh_preset.py
python verify/check_beam_activation.py
python verify/smoke.py --with-gate
python install/install.py --doctor
npm pack --ignore-scripts
```

详见[实测记录](docs/dsh-kit-validation.md)及[验收边界](docs/acceptance.md)。
自有代码使用 MIT 许可证；Lean Beam 技能使用 Apache-2.0，版本与文件哈希见
[来源清单](skills/PROVENANCE.md)。本项目来自 lean-formalization，属于独立插件。
