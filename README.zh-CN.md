# HALCON 视觉脚本编写技能

> **概念验证（Proof of Concept）** — 本技能正在积极开发中，后续可能会有大幅变更。

英文说明见 [README.md](README.md)。

一个用于生成、重构、运行和审阅 [MVTec](https://www.mvtec.com) [HALCON](https://www.mvtec.com/products/halcon) 视觉脚本的 [Agent Skill](https://agentskills.io)。它可以生成算子用法、参数默认值与文档均准确的 [HDevelop](https://www.mvtec.com/products/halcon/work-with-halcon/hdevelop)（`.hdev`）和 [HDevelopEVO](https://www.mvtec.com/products/halcon/work-with-halcon/hdevelopevo)（`.hscript`）程序。

本技能遵循开放的 [Agent Skills](https://agentskills.io) 标准，可与任何兼容的智能体配合使用，包括 [Claude Code](https://claude.ai/code) 和 [OpenAI Codex](https://developers.openai.com/codex)。

## 功能

- **生成完整、可执行的脚本**，同时支持 HDevelop XML（`.hdev`）和 HDevelopEVO 纯文本（`.hscript`）两种格式
- **选择合适的 HALCON 算子**，参数范围有效，默认值合理
- **构建结构化视觉流水线**，遵循经过验证的工作流：输入 → ROI → 预处理 → 检测 → 判定
- **创建可复用的 procedure**，文档默认使用英文；若用户语言与英文不同，则同时提供用户语言，并补充项目中已有的其他语言
- **运行单个 procedure 与测试**，通过 Python runner 提供显式输入、JSON 结果，以及可选的 SVG 可视化
- **无需打开 HDevelop 即可调试正在运行的 HDevelop procedure**，支持持久会话、单步执行、断点、向量检视和 iconic 预览
- **无界面运行完整程序**，可通过 `hrun` 或 `hscriptengine` 执行
- **使用已安装的 HALCON 文档** — 算子参考、解决方案指南和示例

## 前置条件

- 支持 [Agent Skills](https://agentskills.io) 的 AI 编程智能体
- 已安装 [HALCON](https://www.mvtec.com/products/halcon)（或兼容版本），并设置 `HALCONROOT` 与 `HALCONEXAMPLES` 环境变量
- 用于执行的有效 HALCON 运行时许可证
- Python runner / 调试器：与已安装运行时匹配的 Python 和 HALCON Python 绑定，以及下面列出的依赖
- 完整程序执行：所选的 `hrun` 或 `hscriptengine` 可执行文件需位于 PATH 中；若仅使用 Python procedure runner，则不需要这两者

在技能目录中安装 Python 辅助依赖：

```bash
python -m pip install -r requirements.txt
```

此命令安装的是 SVG 与调试协议依赖，不包含 HALCON 绑定或许可证。运行时配置见 [Python 配置参考](references/hdevengine_python_runner.md)。

## 安装

### 方式 A：使用 `npx skills`（多智能体）

一次性为所有受支持的智能体安装本技能（Claude Code、Cursor、Codex、Copilot、Gemini CLI 等）：

```bash
npx skills add https://github.com/bertram-eu/halcon-skill.git
```

或使用 GitHub 简写：

```bash
npx skills add bertram-eu/halcon-skill
```

将技能更新到最新版本：

```bash
npx skills update bertram-eu/halcon-skill
```

### 方式 B：手动安装（git clone）

克隆仓库，并将整个技能文件夹复制到智能体的 skills 目录中，其中包括 `scripts/`、`references/` 和 `requirements.txt`，不能只复制 `SKILL.md`。具体路径取决于所用智能体：

```bash
git clone https://github.com/bertram-eu/halcon-skill.git
```

## 使用

安装完成后，当你提出与 HALCON 相关的任务时，技能会自动激活。例如：

```
> 编写一个 HDevelop 脚本：读取图像、应用阈值，并测量所有检测区域的面积。

> 创建一个以亚像素精度进行模板匹配的 .hscript procedure。

> 调试我的条码读取脚本——它在低对比度图像上会失败。

> 将这个 HDevelop 脚本转换为 HDevelopEVO 格式。
```

技能默认输出 `.hdev`（HDevelop XML）格式。若提及 “HDevelopEVO”、“HScript” 或 “.hscript”，则会改为输出纯文本。

## 包含内容

```
halcon-skill/
├── SKILL.md          # 工作流选择与共享编写规则
├── references/       # 格式、runner、调试器、调色板、已安装资源
├── scripts/          # Python procedure runner、SVG 渲染、持久调试器
├── tests/            # 辅助集成测试与 HDevelop fixtures
└── requirements.txt  # SVG 与调试协议依赖
```

## 选择执行工具

| 需求 | 工具 | 详情 |
|---|---|---|
| `.hdev` 的默认方式：调用具名本地 procedure 或 `test_*`，得到 JSON 或 SVG | `scripts/hdev_call.py` | [Runner](references/hdevengine_python_runner.md) |
| 在不打开 HDevelop 的情况下查看中间状态 | `scripts/hdev_debug.py` | [调试器](references/hdev_debug.md) |
| 回退方案：执行已有程序的 `main()`，或在没有 Python 绑定时运行 | `hrun` | [回退说明](references/hrun.md) |
| 运行 `.hscript` | `hscriptengine` | [HScript 引擎](references/hscriptengine.md) |

例如，在仓库根目录执行：

```bash
python scripts/hdev_call.py tests/fixtures/debug.hdev --procedure debug_probe --input Value=21
```

单个 procedure 测试使用 `test_*` procedure，示例使用 `main()`。面向生产的公开 procedure 接收真实的 `Image` 并返回布尔值 `JobPass`；私有辅助过程以及测试/示例入口不受此限制。

## 限制

这是一个概念验证。已知限制：

- 执行程序和访问文档都需要本地 HALCON 安装及许可证
- 本技能依赖位于 `HALCONROOT/doc/html/` 的 HALCON HTML 算子文档——若安装不完整，算子查找可能会失败
- 生成的脚本在投入生产使用前，都应经过审阅和测试
- 远程调试使用非官方的原生协议。使用前请阅读[调试器限制与会话生命周期](references/hdev_debug.md)；无密码的 HALCON 服务器应位于受信任的主机/网络上，且不得远程暴露

## 许可证

详情见 [LICENSE](LICENSE)。
