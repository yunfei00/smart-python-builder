# Smart Python Builder 1.0.0

Smart Python Builder 将 Python 文件或项目打包成可运行的 Windows 应用。
面向可信内部用户：使用者通过网页上传、选择入口、生成并下载 EXE 或 ZIP，
不需要自行操作依赖安装和打包命令。

## 支持范围

- 单个 `.py` 文件，或包含多文件项目的 `.zip`。
- 控制台程序；Tkinter、PySide6、PyQt6 图形程序。
- 初始构建经验覆盖 requests、numpy、pandas、openpyxl、OpenCV、Pillow、
  pyserial、PyYAML 及上述 GUI 库。
- 自动分析入口与依赖，自动包含项目中的常用图片、JSON、CSV、YAML、UI 资源。
- 单文件 EXE，或保留依赖文件的完整应用 ZIP。
- 可选 AI 受控修复、飞书通知、管理员批准后复用构建经验。

## Windows 环境与首次安装

构建端需要 Windows、64 位 Python 3.11+、uv，以及可写的项目目录和包缓存。
本次发布在Windows 11、uv 管理的 Python 3.13.12、uv 0.11.2 下验证；其他 Python/Windows
组合未逐一测试。安装依赖时需要访问配置的包仓库。每次构建检查至少 1 GiB
空闲磁盘，较大的 Qt/数据处理项目及多次构建需要更多空间。

1. 从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/)
   安装 Python，确保新开的 PowerShell 能执行 `python --version`。
2. 安装 uv。在支持 WinGet 的 PowerShell 中执行：

   ```powershell
   winget install --id=astral-sh.uv -e
   ```

   其他方法见 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)。
   安装后重新打开 PowerShell，确认 `uv --version` 可用。
3. 下载本仓库或克隆后，在项目根目录执行：

   ```powershell
   git clone https://github.com/yunfei00/smart-python-builder.git
   cd smart-python-builder
   uv sync --locked
   uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
   ```

   如果已经下载或克隆过仓库，从 `uv sync --locked` 开始即可。
   保持该终端运行，在浏览器打开 [本地 Web 页面](http://127.0.0.1:8000)。
   在终端按 Ctrl+C 停止服务。默认使用单个服务进程，不要增加 uvicorn workers。

## 上传、生成与下载

1. 点击“选择文件”，选择 `.py` 或 `.zip`，再点击“分析程序”。
   多文件项目请将源码、依赖声明及资源文件放入同一个 ZIP；无需上传 `.venv`。
   单 `.py` 上传只包含该文件；如果还有 helpers、图片或配置，请改用 ZIP。
2. 检查检测到的依赖、应用类型和入口。存在多个入口时必须明确选择，系统不会猜测。
   可展开“查看构建计划”查看详细决策。
3. 选择“单个可执行文件”或“完整应用文件夹 ZIP”，点击“生成 Windows 应用”。
4. 页面显示任务 ID、Build ID、状态及日志。成功后点击“下载应用”。
5. EXE 可直接启动；ZIP 必须完整解压后运行其中的 EXE，不要只移动 EXE 而丢弃依赖。
   目标程序的业务数据、网络或硬件要求仍由原程序决定。

每次构建使用独立环境和 workspace。Web 数据默认保存在 `web-data/`。
依赖优先级：`pyproject.toml` 的明确 dependencies（包括空列表）→
`requirements.txt` → AST import 推导。V1 的 requirements 支持普通 PyPI 依赖声明，
不支持递归 `-r`、自定义索引、VCS 或本地路径依赖。动态导入不能完全依靠 AST 识别。

## 配置 AI（可选）

未配置时不调用外部 AI，也不会自动启用 FakeAIProvider。生产配置读取环境变量：

| 变量 | 用途 |
|---|---|
| `BUILDER_AI_API_KEY` | 兼容接口的 API Key |
| `BUILDER_AI_BASE_URL` | API 基础地址，默认 `https://api.openai.com/v1`，不含 `/chat/completions` |
| `BUILDER_AI_MODEL` | 服务商支持的模型名称，无硬编码默认模型 |

在启动服务的同一个 PowerShell 中设置，例如：

```powershell
$env:BUILDER_AI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'API Key' -AsSecureString)).Password
$env:BUILDER_AI_BASE_URL = 'https://api.openai.com/v1'
$env:BUILDER_AI_MODEL = Read-Host 'Model'
```

然后启动或重启 Web 服务。设置只对当前终端及其子进程生效；服务部署应通过
Windows 服务账号的环境变量配置。不要将真实凭证写入源码、示例、日志或 Git。

AI 只能返回结构化 RepairPlan JSON，由 Builder 验证后执行。允许受控依赖、
隐藏导入、收集包、项目内资源及白名单参数修改，不允许 AI 执行任意 shell、
脚本或 runtime hook。最多两次 AI 修复，未解决进入 NEEDS_MANUAL_REVIEW。
诊断会将项目结构、依赖、构建计划和有长度限制的日志发送到配置的 AI 服务。
接口实现参考 [结构化输出文档](https://developers.openai.com/api/docs/guides/structured-outputs)。

## 配置飞书（可选）

在飞书群创建自定义机器人，取得 Webhook，然后在启动服务前设置：

```powershell
$env:BUILDER_FEISHU_WEBHOOK = [System.Net.NetworkCredential]::new('', (Read-Host 'Feishu Webhook' -AsSecureString)).Password
$env:BUILDER_BASE_URL = 'http://127.0.0.1:8000'
```

`BUILDER_BASE_URL` 应替换为通知接收者实际能访问的内部服务地址。
支持首次构建失败、AI 修复成功、AI 最终失败三类通知。网络请求超时为 5 秒，
发送失败只记录异常类型，不改变构建结果。未配置 Webhook 时禁用发送，
不会自动使用 FakeNotifier。当前只实现普通文本 Webhook，不含签名 secret 配置。

## 经验库与管理员审批

初始 BuildProfile 生成统一 BuildPlan，记录依赖来源、GUI 类型、打包模式、
资源和隐藏导入等决策。AI 修复成功后产生 CANDIDATE，不直接应用到其他项目。
只有 APPROVED 经验会参与后续计划；REJECTED 和未审批候选不生效。
匹配条件保守：Python 源码指纹、导入集合及依赖声明必须一致。

1. 在服务终端设置管理员凭证并重启服务：

   ```powershell
   $env:BUILDER_ADMIN_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Admin token' -AsSecureString)).Password
   ```

2. 打开 [管理员页面](http://127.0.0.1:8000/admin)，输入该凭证并加载经验。
3. 查看失败计划、错误、AI 判断、修复计划、成功计划和适用条件。
4. 可编辑修复 JSON 后批准，或拒绝；编辑内容仍受 Builder 校验。

Web 经验保存在 `web-data/workspace/experiences.sqlite3`；CLI 默认为
`workspace/experiences.sqlite3`。两者使用各自数据目录。审批后不可原地重复修改。
候选引用的原项目若已超过保留期被删除，不能继续验证并批准该候选。

## 安全与已知限制

V1 定位为 **trusted/internal Windows Builder**。上传的 Python、安装包构建后端
以及 PyInstaller hook 可能以 worker 身份执行代码；独立环境不是安全沙箱。
请用低权限专用 Windows 用户运行，仅接收可信项目，默认保持 loopback 监听。
不要直接公开到互联网。独立低权限账号和真实 AI/飞书账号未在本次离线验收中联调。

已实现文件类型/大小与 ZIP 路径校验、构建超时和进程树终止、磁盘检查、
单 worker/有限队列、最多两次 AI 修复、通知隔离、任务恢复及保留期清理。
默认终态 workspace/产物和过期上传保留七天；`BUILDER_RETENTION_DAYS` 可调整。
CLI workspace 的清理需由运维调用维护函数；Web 在启动及每小时自动维护。
没有虚拟机隔离、硬 CPU/内存配额、分布式队列或用户登录系统。
更完整说明见 [运维与安全边界](docs/OPERATIONS.md)。

Web/CLI 构建成功表示已生成非空产物，并不自动运行任意用户上传程序。
发布验收会实际运行固定测试 EXE；内部集成可通过 `artifact_validator` 回调
将程序运行失败纳入修复。该回调只能由运维代码提供，不能由 AI 指定。

## 命令行与验证

```powershell
uv run python analyze.py path\to\project
uv run python build.py path\to\project --entry main.py
uv run python build.py app.py --mode onedir
uv run pytest tests -q --basetemp .pytest-tmp-check
uv run python tests/windows_v1_acceptance.py
```

[发布检查清单](docs/RELEASE_CHECKLIST_V1.md) 记录最终矩阵、Build ID、产物与运行结果。
[实施计划](docs/IMPLEMENTATION_PLAN.md) 中 Phase 1–8 均为 CLOSED；V1 = COMPLETE。
FakeAIProvider/FakeNotifier 仅用于显式注入的测试；真实外部服务需自行配置并联调。
