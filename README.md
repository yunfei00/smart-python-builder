# Smart Python Builder

面向可信内部用户的 Windows Python EXE 构建工具。

## 本地运行

需要 Windows、Python 3.11+ 和 uv。

```powershell
python analyze.py path\to\project
python build.py path\to\project --entry main.py
python build.py app.py --mode onedir
.\run_phase2_tests.ps1
```

自动分析依赖的优先级：`pyproject.toml` 中的明确 dependencies（包括空列表）、
`requirements.txt`、AST import 推导。多个入口必须使用 `--entry` 选择。
每次构建创建独立 workspace、环境、日志和输出；原始项目元数据保留不变。

## 构建计划与经验

`builder.models.BuildPlan` 是构建决策的统一数据结构，可通过 `to_json()` 导出。
`builder.experience.ExperienceEngine` 按结构化 BuildProfile 匹配初始经验，
涵盖 requests、numpy、pandas、openpyxl、PySide6、PyQt6、tkinter、OpenCV、
Pillow、pyserial、PyYAML。GUI 类型自动识别，也可以明确指定。

每个计划包含入口、依赖来源、模式、隐藏导入、资源、额外参数和决策依据。
计划在构建前进行校验，并保存为 workspace 中的 `plan.json`。
默认 onefile 输出 EXE；onedir 输出包含 EXE 和依赖的目录。

## 验证

```powershell
uv run --with pytest python -m pytest tests -q --basetemp .pytest-local-check
```

Windows 构建验收记录位于 docs，记录 Build ID、实际产物和运行行为。
具体阶段与验收标准见 [实施计划](docs/IMPLEMENTATION_PLAN.md)。

## Web 界面

```powershell
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000，上传 .py 或 ZIP，选择入口并生成应用。
后台复用 SmartBuilder；支持实时状态和日志、EXE 下载及 onedir ZIP 下载。

## AI 诊断与受控修复

配置 `BUILDER_AI_API_KEY`、`BUILDER_AI_MODEL`，可选
`BUILDER_AI_BASE_URL`（默认 `https://api.openai.com/v1`）启用兼容接口。
未配置时普通构建不调用外部 AI；测试使用 FakeAIProvider。
实现参考 https://developers.openai.com/api/docs/guides/structured-outputs。

AI 只能返回 RepairPlan JSON，所有字段与修改由 Builder 验证。
允许添加/移除依赖、隐藏导入、收集包、项目内资源和受控参数；不接受命令、
脚本或 runtime hook。每个任务最多两次 AI 修复，最终无法解决进入
NEEDS_MANUAL_REVIEW，完整过程保存在 attempts.json。

构建成功默认表示产物已生成。内部集成可提供 `artifact_validator` 回调，
将实际 EXE 的运行错误纳入同一修复流程；此回调由运维代码提供，不能由 AI 指定。
真实 Windows 修复验证：`uv run python tests/windows_ai_acceptance.py`。

## 飞书通知

配置 `BUILDER_FEISHU_WEBHOOK` 启用通知；`BUILDER_BASE_URL` 设置详情页地址。
首次失败立即发送事件，AI 修复结束发送成功/最终失败、原始错误、诊断、修改与尝试记录。
每次网络请求超时 5 秒，通知失败仅记录异常类型，不改变构建结果。
未配置 Webhook 时不发送；FakeNotifier 用于本地验收。

## 经验学习与审批

修复成功自动生成 CANDIDATE，保存在 workspace/experiences.sqlite3。
设置 `BUILDER_ADMIN_TOKEN` 后访问 `/admin`，输入管理员凭证查看、编辑批准或拒绝。
没有配置凭证时审批 API 不开放。只有 APPROVED 经验进入 ExperienceEngine。
默认匹配项目 Python 源码指纹、导入集合及依赖声明，避免把修复广泛应用到无关项目。
跨不同目录的相同源码项目可复用批准经验。审批后不可原地再次修改；需要新的候选。

`uv run python tests/windows_learning_acceptance.py` 验证真实 EXE 故障、修复、
HTTP 批准、第二项目首次成功且不再次调用 AI 的完整闭环。

## V1 运维与安全

本工具定位为 trusted/internal Windows Builder。请参阅
[部署与安全边界](docs/OPERATIONS.md) 了解低权限运行、超时、并发、保留期、
恢复、凭证配置，以及未来隔离 Worker 扩展点。
最终 Windows 验收：`uv run python tests/windows_v1_acceptance.py`。
