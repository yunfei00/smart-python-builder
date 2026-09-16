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
