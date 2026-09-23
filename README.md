# Smart Python Builder 1.3.0

Smart Python Builder 将 Python 文件或项目打包成可运行的 Windows 应用。
面向可信内部用户：使用者通过网页上传、选择入口、生成并下载 EXE 或 ZIP，
不需要自行操作依赖安装和打包命令。

## 支持范围

- 单个 `.py` 文件、包含多文件项目的 `.zip`，或直接导入公开 GitHub 仓库。
- 控制台程序；Tkinter、PySide6、PyQt6 图形程序。
- 初始构建经验覆盖 requests、numpy、pandas、openpyxl、OpenCV、Pillow、
  pyserial、PyYAML 及上述 GUI 库。
- 自动分析入口与依赖，自动包含项目中的常用图片、JSON、CSV、YAML、UI 资源。
- 单文件 EXE，或保留依赖文件的完整应用 ZIP。
- 可选 AI 受控修复、飞书通知、管理员批准后复用构建经验。
- 用户名优先账号体系：邮箱选填，FREE/TEST 套餐、构建额度、个人工作台与账号密码管理。
- 管理员可创建/停用用户、切换套餐、设置或重置额度、重置用户密码，并支持用户名/套餐/账号状态筛选。
- 管理后台提供运营概览：总构建量、今日构建量、成功率、AI 修复次数、磁盘占用和队列状态。
- 用户可提交“用户心声”；管理员可在后台查看、筛选、标记处理状态，并可选同步发送飞书通知。
- READY 项目可继续构建；运行中任务可取消，终态项目可删除并清理关联文件。

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

1. 点击“选择文件”，选择 `.py` 或 `.zip`，再点击“分析并继续”。
   多文件项目请将源码、依赖声明及资源文件放入同一个 ZIP；无需上传 `.venv`。
   单 `.py` 上传只包含该文件；如果还有 helpers、图片或配置，请改用 ZIP。
2. 检查检测到的依赖、应用类型和入口。存在多个入口时必须明确选择，系统不会猜测。
   可展开“查看构建计划”查看详细决策。
3. 选择“单个可执行文件”或“完整应用文件夹 ZIP”，点击“生成 Windows 应用”。未登录用户可先完成项目分析，开始构建时需登录或注册；登录后会继续原 READY 项目，无需重新上传。
4. 页面显示任务 ID、Build ID、状态及日志。成功后点击“下载应用”。
5. EXE 可直接启动；ZIP 必须完整解压后运行其中的 EXE，不要只移动 EXE 而丢弃依赖。
   目标程序的业务数据、网络或硬件要求仍由原程序决定。

每次构建使用独立环境和 workspace。Web 数据默认保存在 `web-data/`。
依赖优先级：`pyproject.toml` 的明确 dependencies（包括空列表）→
`requirements.txt` → AST import 推导。`pyproject.toml` 支持普通 PyPI 依赖以及经过校验的
`name @ git+https://github.com/owner/repo.git[@ref]` 公共 GitHub VCS 依赖。requirements.txt
仍只支持普通 PyPI 声明，不支持递归 `-r`、自定义索引、VCS 或本地路径依赖。动态导入不能完全依靠 AST 识别。

源码已导入、且在 `[project.optional-dependencies]` 中声明的依赖也会加入构建，保留版本约束；
测试文件的导入不触发可选依赖安装。包内入口（如 `src/port_bridge/__main__.py`）按模块运行，保留相对导入上下文。

## 用户账号、额度与项目管理

普通用户使用 **用户名 + 密码** 注册，邮箱为选填；如果填写邮箱，之后既可以使用用户名，也可以使用邮箱登录。
用户名长度 2–32 个字符，支持中文、英文字母、数字、下划线和中划线，英文字母大小写不敏感。
旧版仅邮箱账号会在首次启动 v1.2.1 时自动迁移：保留原用户 ID、密码哈希、套餐、额度、停用状态与 Session 关联，
并从原邮箱前缀生成唯一用户名；原邮箱登录继续兼容。无邮箱账号在数据库中保存为真正的 NULL。

- **家庭免费模式（默认）**：新注册用户默认获得 10000 次 FREE 构建额度；管理员可在系统设置中修改该额度，并可一键把现有所有 FREE 用户的剩余额度补到当前配置值。
- **商业模式（预留）**：新注册用户使用基础 FREE 3 次规则；当前不包含支付、订单或充值功能。
- **TEST**：内部无限构建账号，不受 FREE 次数限制。
- 用户工作台显示自己的项目、状态与额度；READY 项目可以继续，运行中任务可以取消，终态项目可以删除。
- 用户可在账号设置中修改密码；修改成功后旧 Session 失效，并为当前浏览器创建新 Session。
- 管理员在 `/admin/users` 可创建用户、设置剩余额度、重置额度、FREE/TEST 切换、停用/启用账号及重置用户密码。
- 管理员重置用户密码后，该用户原有登录 Session 全部失效。

## 管理员初始化与登录

首次启动前，在同一个 PowerShell 中设置自己的管理员密码：

```powershell
$env:BUILDER_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Admin password' -AsSecureString)).Password
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

打开 [管理员登录](http://127.0.0.1:8000/admin/login)，输入密码后默认进入运营概览；也可进入经验管理、用户管理、用户心声或系统设置。
没有初始密码时页面提示尚未初始化；没有默认账号/密码。密码仅在第一次初始化时读取，
以随机盐 scrypt 哈希保存。后续改变环境变量不会覆盖已有密码；初始化后可从启动环境移除。
点击“退出登录”立即撤销当前会话；会话八小时过期。

## 系统设置、AI 与飞书

登录后打开 [系统设置](http://127.0.0.1:8000/admin/settings)：

- **Builder 服务**：Builder 访问地址填写其他设备能访问的 URL，用于任务与审批链接，保存后后续通知立即生效（环境变量覆盖优先）。支持 HTTP/HTTPS，去空白与末尾斜杠；禁止查询、片段、URL 凭证和 `0.0.0.0`/`::`。本机 localhost/127 地址允许保存，但页面显示黄色提醒。
  Allowed Hosts 填客户端访问的主机名/IP，可用逗号分隔；用户构建数据保留天数默认 30，可快速选择 1 个月、2 个月、6 个月或 1 年。
  Allowed Hosts 保存后需要重启；数据保留时间修改后立即用于后续自动清理和手动清理。
- **AI 服务**：选择 OpenAI compatible，填 API 基础地址（不含 `/chat/completions`）、模型，
  点击“更换 API Key”输入密钥。可先“测试 AI 连接”，再启用修复并保存。
  测试发送最小 Chat Completions 请求，15 秒超时；诊断请求 60 秒超时。
- **飞书通知**：点击“更换 Webhook”填写群自定义机器人的地址，可先“发送测试消息”，
  再启用通知并保存。可单独控制“用户反馈也发送飞书通知”。测试消息包含 Smart Python Builder、飞书通知测试成功和 UTC 时间。
  发送超时 5 秒，通知失败不改变构建或反馈保存结果；暂不支持机器人签名 secret。

密钥与 Webhook 只显示“已配置：********”；留空或提交遮罩会保留旧值。
测试使用当前表单和已保存密钥，不自动保存；AI/飞书服务保存后用于下一次新构建。
Builder 访问地址在每次生成通知链接时重新读取，正在运行的构建后续通知也会使用新地址。
AI/飞书从与后台相同的 SettingsStore 读取，生产没有可选的 Fake Provider。

配置统一保存在工作目录的 `web-data/settings.sqlite3`，Web 与默认 CLI 共用这份配置。
**显式环境变量 > 后台保存值 > 默认值**。页面列出被环境变量覆盖的字段；若要后台管理，
移除相应环境变量后重启。保留以下部署兼容变量：

| 变量 | 用途 |
|---|---|
| `BUILDER_ALLOWED_HOSTS` | 主机名/IP 逗号分隔，支持 `*`，去空白/空项，拒绝全空 |
| `BUILDER_RETENTION_DAYS` | 1–3650 天 |
| `BUILDER_SERVICE_MODE` | `family_free`（默认）或 `commercial` |
| `BUILDER_FAMILY_FREE_QUOTA` | 家庭免费模式默认 FREE 额度，默认 10000 |
| `BUILDER_AI_ENABLED` | `true` / `false` |
| `BUILDER_AI_PROVIDER` | `openai-compatible` |
| `BUILDER_AI_API_KEY` | AI 密钥 |
| `BUILDER_AI_BASE_URL` | 默认 `https://api.openai.com/v1` |
| `BUILDER_AI_MODEL` | 服务商模型，无默认模型 |
| `BUILDER_FEISHU_ENABLED` | `true` / `false` |
| `BUILDER_FEISHU_WEBHOOK` | 飞书机器人地址 |
| `BUILDER_BASE_URL` | 覆盖后台 Builder 访问地址；默认 `http://127.0.0.1:8000` |
| `BUILDER_COOKIE_SECURE` | HTTPS 部署设 `true`，局域网 HTTP 默认 `false` |
| `BUILDER_ADMIN_TOKEN` | 原有自动化 Bearer API 兼容；普通管理员无需填写 |

旧部署只设 AI Key + Model 或 Webhook、且没有保存对应 Enabled 开关时，会兼容启用该服务。
一旦保存开关，按明确开关执行。环境变量变更需要重启。
AI 只能返回经过校验的结构化 RepairPlan，不得执行任意 shell、脚本或 runtime hook；最多修复两次。
诊断会向配置的 AI 服务发送项目结构、依赖、计划和有长度限制的日志，请确认项目适合发送。

## 构建通知行为

| 场景 | 通知顺序 |
|---|---|
| 首次构建成功 | Build Success（一次） |
| 首次失败，无 AI | Build Failed（一次） |
| 首次失败，AI 修复成功 | Build Failed → AI Repair Success，不额外发 Build Success |
| 首次失败，AI 放弃/异常/重试耗尽 | Build Failed → AI Repair Failed，不发 Build Success |

通知异常只记录异常类型，不把成功构建变成失败；禁用飞书不发送自动通知。
飞书以中文摘要显示项目、Build ID、入口、尝试次数、状态和链接，不原样发送诊断 JSON。
任务链接使用 `{base_url}/?job={Web Job ID}`；审批链接为 `{base_url}/admin`，登录后审核候选。
Web Job ID 与每次打包产生的 Build ID 不同，不能互换。

## 局域网访问

三个地址概念各司其职，不自动互相修改：

| 配置 | 含义 | 示例 |
|---|---|---|
| Listening Host | uvicorn 监听哪些网络接口 | `--host 0.0.0.0` |
| Allowed Hosts | 允许哪些请求 Host Header | `localhost,127.0.0.1,192.168.1.100` |
| Builder Base URL | 飞书等通知中的可点击链接前缀 | `http://192.168.1.100:8000` |

在系统设置中填写实际 **Builder 访问地址**，不要填监听地址；程序不会猜测 LAN IP。
在 Allowed Hosts 中加入 Builder 主机的真实 IPv4，保存后重启；也可在启动终端设置：

```powershell
$env:BUILDER_ALLOWED_HOSTS = 'localhost,127.0.0.1,192.168.1.100'
$env:BUILDER_BASE_URL = 'http://192.168.1.100:8000'
uv run uvicorn web.app:app --host 0.0.0.0 --port 8000
```

示例 IP 要换成 `ipconfig` 显示的实际 IPv4。`0.0.0.0` 是监听地址，客户端不要访问
`http://0.0.0.0:8000`，应访问 `http://192.168.x.x:8000`。
`BUILDER_ALLOWED_HOSTS='*'` 可用于可信局域网测试，但它并不是客户端权限控制。
跨电脑访问还需管理员按组织要求配置 Windows Firewall 的 TCP 8000 入站规则，
仅允许可信网段/专用网络；不要关闭防火墙或向公网开放。本项目不会自动修改防火墙。

## 经验库与管理员审批

初始 BuildProfile 生成统一 BuildPlan，记录依赖来源、GUI 类型、打包模式、
资源和隐藏导入等决策。AI 修复成功后产生 CANDIDATE，不直接应用到其他项目。
只有 APPROVED 经验会参与后续计划；REJECTED 和未审批候选不生效。
匹配条件保守：Python 源码指纹、导入集合及依赖声明必须一致。

1. 登录 `/admin/login` 后进入“经验管理”。
2. 查看失败计划、错误、AI 判断、修复计划、成功计划和适用条件。
3. 可编辑修复 JSON 后批准，或拒绝；编辑内容仍受 Builder 校验。
4. 自动化调用仍可使用 `Authorization: Bearer <BUILDER_ADMIN_TOKEN>`；浏览器后台使用 Session + CSRF。

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
Web 用户构建数据默认保留 30 天；`BUILDER_RETENTION_DAYS` 可调整。Web 在启动及每小时自动清理超过保留期的历史构建记录、上传文件、工作区和产物，
管理员也可在“运营概览”中预览并手动执行清理；用户账号和“用户心声”不会被该构建数据清理策略删除。
CLI workspace 的清理需由运维调用维护函数。
已提供普通用户账号、额度和管理员用户管理，但仍没有虚拟机隔离、硬 CPU/内存配额或分布式队列。
Windows 密钥使用当前服务用户的 DPAPI 加密；管理员密码为 scrypt 哈希，Session 令牌只存摘要。
数据库、备份和运行目录不得提交 Git；保持服务账号专用 ACL。同一用户执行的可信项目仍可能访问设置，
DPAPI 不提供 worker 沙箱。HTTP 不加密登录内容，仅适用于受控网络；生产网络建议 HTTPS。
更完整说明见 [运维与安全边界](docs/OPERATIONS.md)。

Windows Web/CLI 构建会在资源整理完成后启动最终交付目录中的 EXE，并将输出写入 `build.log`。
控制台程序须在 90 秒内以退出码 0 结束；GUI 观察 5 秒，非零退出判失败，持续运行则通过并结束测试进程树。
通过日志记录 `SMOKE TEST PASS`。这项启动检查不代表所有业务功能或硬件通信已验证。
内部集成仍可通过 `artifact_validator` 回调增加应用功能验证；该回调不能由 AI 指定。

资源计划区分源码中的 `data_files` / `sidecar_files` 与 `generated_sidecars`。
源码资源缺失会报告具体路径。明确引用但源码中不存在的 `BUILD_INFO.json` 由 Builder
在独立 workspace 中生成，版本读取 `VERSION`，GitHub 导入保留真实提交号；生成后再次严格验证。
需要 EXE 旁资源的 onefile 构建交付 ZIP，包含 EXE、sidecar 和选定的静态资源（包括 XLSX/XLS），
不会因为无关字符串 `"main.py"` 自动交付源码。Git 元数据不会进入构建副本或下载包。

## 命令行与验证

```powershell
uv run python analyze.py path\to\project
uv run python build.py path\to\project --entry main.py
uv run python build.py app.py --mode onedir
uv run pytest tests -q --basetemp .pytest-tmp-check
uv run python tests/windows_acceptance.py
uv run python tests/windows_github_import_acceptance.py
```

[发布检查清单](docs/RELEASE_CHECKLIST.md) 用于每次正式发布前的统一验证。
FakeAIProvider/FakeNotifier 仅用于显式注入的测试；真实外部服务需自行配置并联调。
