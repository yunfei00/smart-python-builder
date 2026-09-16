# Smart Python Builder — V1 实施与验收计划

## 项目目标

让非 Python 开发人员上传单个 `.py` 文件或 Python 项目文件夹，系统自动分析项目和依赖，使用 uv 创建独立构建环境，通过 PyInstaller 生成 Windows 可执行程序；构建失败时由 AI 自动诊断和受控重试，并通过飞书通知管理员；AI 成功修复后形成经验候选，经管理员确认后进入正式打包经验库。

## V1 技术基线

- 目标平台：Windows 10 / 11 / Windows Server
- Web：FastAPI + Jinja2
- 环境与依赖：uv
- Windows 打包：PyInstaller
- AI：结构化诊断与 Repair Plan，最多自动修复 2 次
- 通知：飞书
- 输入：单个 `.py` 或 Python 项目文件夹
- 隔离：每个 Build Task 独立 workspace、`pyproject.toml`、`.venv`、build、dist

## 阶段状态规则

阶段状态只使用：`TODO → IN_PROGRESS → VERIFYING → CLOSED`。

每个阶段必须完成开发、验证和验收后才能标记 `CLOSED`；未关闭当前阶段，不进入下一阶段。Phase 8 关闭后，V1 标记 `COMPLETE`，新增需求进入 V1.1/V2。

## Phase 1 — 基础构建引擎

**状态：IN_PROGRESS**

目标：先不做 Web、AI、飞书，跑通 `Python → uv → 独立环境 → PyInstaller → Windows EXE`。

实现：Build Task、独立 workspace、UVEnvironmentManager、PyInstallerBuilder、BuildResult、完整构建日志。

验证用例：
1. 纯标准库/Tkinter 程序；
2. requests + pandas/openpyxl 第三方依赖程序；
3. PySide6 GUI 程序。

验收：三个 Case 全部构建成功；任务间 `.venv` 隔离；不依赖服务器全局第三方包；EXE 可正常启动；失败任务不影响其他任务；日志完整。

## Phase 2 — 项目分析与依赖识别

**状态：TODO**

目标：支持单 `.py` 和项目文件夹，自动分析依赖和入口。

实现：AST import 扫描；区分标准库、项目内部模块和第三方模块；Package Mapping（如 `cv2→opencv-python`、`PIL→Pillow`、`yaml→PyYAML`、`serial→pyserial`）；入口识别；依赖优先级为已有 `pyproject.toml` → `requirements.txt` → AST 推导。

验证：至少覆盖标准库、requests、pandas/openpyxl、OpenCV、PySide6 多文件项目，确认内部模块不会被误装为 PyPI 包。

## Phase 3 — 构建经验库

**状态：TODO**

目标：在 AI 介入前建立确定性的打包经验系统。

首批覆盖：requests、numpy、pandas、openpyxl、PySide6、PyQt6、tkinter、opencv-python、Pillow、pyserial、PyYAML。

经验内容包括：import→package、GUI/Console、hidden-import、collect-all、add-data、PyInstaller 参数、Known Error、Repair Action。

验收：项目分析 + 经验匹配能够生成明确的 Build Plan，并用 Phase 2 测试项目重新验证。

## Phase 4 — Web 使用界面

**状态：TODO**

目标：非开发人员通过浏览器完成上传、构建、下载。

实现：上传单 `.py` / 项目文件夹；展示入口、程序类型、依赖、构建状态和日志；成功后下载 EXE，复杂项目可下载程序 ZIP。

验收：找不懂 Python 的人员，仅告知“上传 Python 文件并生成 EXE”，不得要求其使用 pip、venv、uv、PyInstaller 或命令行，能够独立完成上传→等待→下载→运行。

## Phase 5 — AI 自动诊断与修复

**状态：TODO**

目标：首次构建失败后 AI 自动诊断并生成结构化 Repair Plan，最多自动修复 2 次。

AI 输入包括项目结构、代码分析、依赖、经验库、Build Plan、构建日志和错误信息；输出必须是结构化数据，由 Builder 校验后执行，AI 不直接执行任意命令。

验证：人为制造缺少依赖、hidden import、资源文件缺失、package mapping 错误、PyInstaller 参数问题等失败；同时验证无法解决时进入 `NEEDS_MANUAL_REVIEW`，不会无限重试。

## Phase 6 — 飞书通知

**状态：TODO**

目标：管理员无需持续查看 Web 页面。

实现独立 NotificationService / FeishuNotifier，至少包含：首次 Build Failed、AI Repair Success、AI Repair Failed。首次失败立即通知；AI 修复结束后发送原因、修改过程、重试结果和经验候选摘要。通知失败不能使 Build Task 本身失败。

验收：分别人为触发普通失败、AI 修复成功、AI 最终失败，管理员均收到对应消息。

## Phase 7 — 经验沉淀与管理员审核

**状态：TODO**

目标：AI 修复成功后生成 Experience Candidate，不直接污染正式经验库。

经验状态：`CANDIDATE / APPROVED / REJECTED`。管理员可批准、拒绝或修改后批准；只有 APPROVED 经验参与后续正式 Build Plan。

核心验收：构造新错误→第一次失败→AI 修复成功→产生 Candidate→管理员批准→第二个同类项目直接命中经验并首次构建成功，不再调用 AI。

## Phase 8 — 稳定性、安全与最终验收

**状态：TODO**

实现：文件类型/大小限制、ZIP 安全解压和路径穿越防护、构建超时、AI 重试限制、磁盘/并发限制、日志管理、异常恢复、低权限 Build Worker、过期 workspace/artifact 自动清理。不可信用户场景需要更强 Windows 构建隔离。

最终 Test Matrix 至少覆盖：标准库 CLI、Tkinter、requests、pandas、openpyxl、numpy、OpenCV、Pillow、PySide6、PyQt6、pyserial、多文件项目、图片资源、JSON 配置、requirements、pyproject、普通失败、AI 修复成功、AI 修复失败、经验库命中，共 20 类场景。

全部通过后：`Phase 8 = CLOSED`，`Smart Python Builder V1 = COMPLETE`。

## 时间计划

预计工作量：10–14 个有效开发日，计划周期约 3 周。

- 2026-09-20：核心 Builder（Phase 1–2）目标可用；
- 2026-09-27：经验库 + Web + AI + 飞书主要闭环目标可用；
- 2026-10-04：经验审核 + 稳定性最终验收，V1 目标完成；
- 2026-10-11：缓冲截止日期。

## 当前执行点

当前只执行 **Phase 1**。Phase 1 验收并 `CLOSED` 后，才启动 Phase 2。