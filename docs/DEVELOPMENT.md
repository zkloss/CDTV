# 开发、构建与打包

[English](DEVELOPMENT.en.md) | 简体中文

本文档面向开发者，说明源码运行、构建、前端开发、打包为 exe 与目录结构。面向用户的功能说明见 [README](../README.md)。

---

## 环境要求（源码运行）

以下安装与打包命令面向 Windows；Mac 步骤见下方“macOS 运行与打包”。

- Windows 10 / 11
- Python 3.11+
- Node.js 20.19+（20.x）或 22.12+；建议使用满足此范围的 LTS 版本
- 系统需安装 **WebView2 Runtime**（Win10/11 通常自带）

## 安装

以下 PowerShell 命令从项目根目录执行。`npm ci` 按仓库锁文件安装依赖；Node.js 下限以当前 Vite 与 Vue 插件的 `engines.node` 为依据。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
```

## 运行桌面版

```powershell
.venv\Scripts\python launcher.py
```

应用启动时会自动拉起内置的本地存储服务并以单机账号进入，无需额外启动任何服务。

## 前端开发模式

安装依赖后，可直接双击项目根目录的 `启动应用.bat`：脚本会启动或复用 5173 端口上的 Vite，再以开发模式打开桌面客户端；需先准备 `.venv` 环境。手动启动方式如下：

先启动 Vite：

```powershell
cd frontend
npm run dev
```

再打开另一个位于**项目根目录**的终端：

```powershell
.venv\Scripts\python launcher.py --dev
```

## macOS 运行与打包

首次安装可按 [Mac 用户安装、浏览器配置与打包说明](MAC_SETUP.md) 逐步操作。

已加入 macOS 适配代码，尚未进行 Mac 实机验证。Windows 仍使用原来的 `.bat`、`launcher.spec`、浏览器路径和数据目录。

Mac 需要 Python 3.11+、满足上方版本要求的 Node.js，以及安装在 `/Applications` 或 `~/Applications` 下的 Google Chrome。请在 Mac 上重新安装依赖，不要复制 Windows 的 `.venv`、`node_modules` 或 `chrome.exe`。

从项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos.txt
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python launcher.py
```

也可执行 `bash ./启动应用.command`；若希望在 Finder 双击启动，先执行 `chmod +x ./启动应用.command`。该脚本使用构建后的前端页面；仅在构建产物不存在时构建前端。前端修改后需重新执行 `npm run build`，或在两个终端分别运行 `npm run dev`（`frontend/` 下）和 `.venv/bin/python launcher.py --dev`（项目根目录下）。

生成统一通过设置中心配置的模型 API 完成，不再需要内置浏览器或网页账号登录；`runtime/` 下的浏览器文件可忽略。

Mac 使用原生窗口边框进行拖动和缩放；文件与目录使用 Finder 打开，复制素材使用系统文件剪贴板。浏览器能否接收多文件粘贴仍需实机确认。

源码运行仍将数据存入项目的 `data/`，视频输出在其 `data/storage/output/`；打包 `.app` 后改为 `~/Library/Application Support/CDTV/data/`，视频输出在其 `data/storage/output/`，避免向应用包内写数据。源码数据不会自动迁移到 `.app`：如需继续使用，关闭两端客户端后复制 `data/`，并在设置中心检查项目存储目录。跨系统复制项目数据后需重新检查素材绝对路径。

在 **Mac 本机**构建 `.app`：

```bash
.venv/bin/python -m pip install 'pyinstaller>=6'
.venv/bin/python -m PyInstaller launcher.macos.spec --noconfirm --clean
```

构建前先完成上述前端构建；产物为 `dist/CDTV.app`，可复制到“应用程序”目录。默认使用接收者已安装的 Mac Chrome，浏览器不随 `.app` 打包。构建使用当前 Python 的架构，Apple Silicon 与 Intel 版本需分别在对应架构环境构建。该配置未进行构建验证，也未配置用于公开分发的 Developer ID 签名与公证。

视频兼容转换等依赖 FFmpeg 的功能仍需安装 `ffmpeg` / `ffprobe`。从 Finder 启动时会补充 `/opt/homebrew/bin`、`/usr/local/bin` 到工具搜索路径。

---

## 打包为 exe

项目已提供 `CDTV.spec`，用 PyInstaller 打包为 Windows 可执行文件（目录模式）：

```powershell
# 1. 先构建前端
cd frontend
npm run build
cd ..

# 2. 安装 PyInstaller（若未安装）
.venv\Scripts\python -m pip install pyinstaller

# 3. 打包
.venv\Scripts\python -m PyInstaller CDTV.spec --noconfirm --clean
```


注意：

- 目标机器需安装 **WebView2 Runtime**，否则 pywebview 无法启动。
- 不再需要 Java 运行时，也不需要 storage jar。
- Playwright Node 驱动随 exe 打包；为避免安装包重复膨胀，`.local-browsers` 不打包，浏览器内核复用与 exe 同级的 `runtime/chrome-win64`（可选）。
- 字幕/配音校对所需 `runtime/audio-review` 与 `runtime/ffprobe.exe` 会打入 `_internal/runtime`；整片渲染可选地在 `motion_runtime/node.exe` 放置便携 Node.js。

## 本地回归验证

以下测试使用临时数据库和本机模拟模型服务，不读取真实 API Key，也不消耗模型额度：

```powershell
.venv\Scripts\python -m unittest scripts.test_migration_regressions scripts.test_image_generation -v
.venv\Scripts\python -m scripts.test_local_storage
node --test scripts/test_chapter_save.mjs
```

前端测试需先安装 `frontend/` 的依赖。已检查的迁移问题与实测边界见 [迁移检查记录](MIGRATION_AUDIT.md)。

## 常见启动问题

- **找不到前端产物**：在 `frontend/` 执行 `npm ci` 和 `npm run build`，再回项目根目录运行 `launcher.py`。
- **开发模式空白页**：检查 `http://127.0.0.1:5173` 是否可访问、Vite 是否仍在运行；单独用浏览器打开页面不具备 `pywebview` 桌面 API。
- **AI 生成配置报错**：图片、MiniMax 音色试听、Seedance 视频和文本转发已接入，检查模型是否启用，以及 API 地址、API Key 和模型名是否完整。修改 Python 服务代码后需重启客户端。
- **修改存储目录后仍使用旧目录**：目录修改在重启客户端后生效，不会自动搬移原数据。需要保留原数据时，关闭客户端后复制完整实际存储目录到目标目录。
- **修改后仍显示旧逻辑**：Python 改动需完全退出并重启客户端；Vite 只热更新前端。非开发模式读取 `frontend/dist`，前端改动后需重新构建。

## 目录结构

```text
comoc-drama-client/
├─ launcher.py            # 桌面主入口
├─ local_storage.py       # 内置纯 Python 本地存储服务（SQLite + 文件桶）
├─ media_server.py        # 本地媒体预览服务
├─ constants.py           # 共享常量与路径
├─ CDTV.spec              # PyInstaller 打包配置（Windows）
├─ pyinstaller_hooks/     # 自定义打包钩子（裁剪 Playwright 重复浏览器）
├─ SKILL/                 # AI 分镜创作能力定义（SKILL.md + references/）
├─ frontend/              # Vue 3 前端
├─ assets/                # 应用图标
├─ scripts/               # 工具脚本（图标生成、窗口调试、快捷方式等）
├─ docs/                  # 补充文档
└─ data/ output/          # 运行时数据（已 gitignore）
```
