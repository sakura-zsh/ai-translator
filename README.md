# AI Translator

轻量级桌面 AI 翻译工具，跨平台：**Linux（Wayland）** 与 **Windows** 共用同一套代码，仅打包方式不同。

- 多 LLM 配置（OpenAI 兼容接口：OpenAI / DeepSeek / SiliconFlow / Ollama …）
- 源语言自动检测，目标语言可选，语种互换
- 文本翻译 / 截图翻译 / 粘贴图片翻译
- 图片模式可切换：**OCR**（tesseract）或 **Vision**（视觉模型）
- **提取文字**：OCR 提取当前图片 / 新截图的文字到原文框并复制，不翻译
- 已是目标语言时自动反向翻译
- 可选：翻译完成后**自动复制**到剪贴板
- **翻译场景**：5 个内置风格预设（通用/学术/技术/口语/正式）+ 自定义场景，与补充提示词叠加生效
- **术语表**：固定译法（最多 100 条），翻译时严格按指定译法渲染
- **历史记录**：可调条数（0–100），支持搜索、一键复制译文
- 系统托盘（可关闭时最小化到托盘）、单实例唤起、Windows 全局呼出热键
- 首次启动**服务商模板向导**；设置中可一键**拉取模型列表**（`/models`）下拉选择
- 现代化深色 / 浅色主题（Catppuccin 风格 QSS）

## 平台后端

| 功能 | Linux (Wayland) | Windows |
|------|-----------------|---------|
| 截图 | `slurp` + `grim` | Qt 全屏遮罩框选（多屏支持） |
| 剪贴板图片 | `wl-paste` | Qt clipboard |
| 配置路径 | `~/.config/ai-translator/` | `%APPDATA%\ai-translator\` |
| 打包 | makepkg（pacman） | PyInstaller（onedir） |

## 依赖

- Python ≥ 3.11，`PySide6`、`httpx`、`Pillow`
- 可选系统依赖：
  - **Linux**：`grim`、`slurp`（截图）、`wl-clipboard`（剪贴板图片）、`tesseract` + 语言包（OCR 模式）
  - **Windows**：[Tesseract for Windows](https://github.com/UB-Mannheim/tesseract/wiki)（OCR 模式，需加入 PATH）

### Linux（Arch / CachyOS）

```bash
sudo pacman -S grim slurp wl-clipboard
# OCR 模式（可选，Vision 模式可不装）
sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim
```

### 从源码运行

```bash
cd /path/to/ai_translator
python -m venv .venv
# bash/zsh:
source .venv/bin/activate
# fish:
#   source .venv/bin/activate.fish
pip install -e .
python -m app
# 或安装入口脚本后：
ai-translator
```

## 打包

### Linux（pacman 包）

```bash
./packaging/linux/build-package.sh
sudo pacman -U packaging/linux/ai-translator-<版本>-*.pkg.tar.zst
```

### Windows（PyInstaller onedir）

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build-windows.ps1
# 产物：packaging\windows\dist\ai-translator\ai-translator.exe
```

## 配置

配置文件：

- Linux：`~/.config/ai-translator/config.json`（权限 `600`）
- Windows：`%APPDATA%\ai-translator\config.json`

首次启动会自动生成默认配置，并弹出**服务商向导**：选择 OpenAI / DeepSeek / SiliconFlow / Kimi / 智谱 / 通义 / OpenRouter / Gemini / Ollama / LM Studio 模板，填入 API Key，点「获取模型」拉取真实模型列表后下拉选择，测试连接即可开始。之后可在 **设置 → LLM 配置** 中修改：

| 字段 | 说明 |
|------|------|
| 服务商模板 | 选择后自动填入 Base URL、协议与推荐模型（可随时改回「自定义」） |
| Base URL | 如 `https://api.openai.com/v1`、`https://api.deepseek.com/v1`、`http://127.0.0.1:11434/v1` |
| API Key | Bearer Token（本地 Ollama 可留空） |
| API 协议 | **Chat Completions**（`/chat/completions`，默认）或 **Responses**（`/responses`，部分中转站） |
| 文本模型 | 可手输，或点「获取模型」从服务方拉取列表后选择 |
| 视觉模型 | 同上；需支持图片输入，如 `gpt-4o`、`llava` |

> 中转站若只给 Responses 协议，把 API 协议切到 **Responses**，Base URL 仍填到 `/v1` 即可（会自动请求 `/v1/responses`）。

可添加多个配置，主界面顶部下拉框即时切换。

### 补充提示词示例

```
使用正式书面中文，保留专业术语英文原文，不要意译品牌名。
```

### 翻译场景与术语表

**设置 → 翻译** 中：

- **翻译场景**：内置 5 个（通用 / 学术论文 / 技术文档 / 口语化 / 正式书面，只读），点「管理…」可**新增 / 修改 / 删除自定义场景**（名称 + 提示词，最多 20 个）。翻译时场景提示词在前、个人补充提示词在后，两者叠加。主窗口工具栏可随时切换。
- **术语表**：每行一条 `术语 = 译文`（分隔符也支持 `→`、`->` 或 Tab），最多 100 条，翻译时严格按指定译法渲染。

### 历史

工具栏「历史记录」打开浮层：顶部搜索框可按原文/译文过滤（不区分大小写），每张记录卡右上角「复制」一键复制译文，点击卡片可整体载入回主界面。条数在 **设置 → 外观与快捷键 → 历史条数**（0–100，调小会截断现有记录）。

### 托盘与唤起

- 关闭窗口默认**最小化到托盘**（可在设置关闭）；托盘菜单含显示/隐藏、截图翻译、提取文字、退出；`Ctrl+Q` 真退出。无托盘的桌面（部分 Wayland）自动降级为普通关闭。
- **单实例**：重复启动第二个实例会自动唤起已运行实例的窗口并退出。Linux 下配合合成器快捷键实现「随用随弃」：

```bash
# niri (~/.config/niri/config.kdl)
binds {
    Mod+T { spawn "ai-translator"; }
}
# Hyprland (~/.config/hypr/hyprland.conf)
bind = SUPER, T, exec, ai-translator
```

- **Windows 全局呼出**：`Ctrl+Alt+T`（默认，可在 **设置 → 外观与快捷键 → 全局呼出** 修改）在任何界面按下即唤起主窗口。

## CLI（无界面翻译）

```bash
ai-translator-cli "Hello world"       # 直接翻译
ai-translator-cli --clipboard -t ja   # 翻译剪贴板文本
ai-translator-cli --clipboard --image # 翻译剪贴板图片
ai-translator-cli --screenshot --mode vision  # 截图后 Vision 翻译
echo 'text' | ai-translator-cli       # 管道输入
```

常用参数：`-s/-t` 源/目标语言、`--profile 名称` 指定服务商、`--no-copy` / `--no-notify` 关闭复制与通知、`--config 路径` 指定配置文件、`--verbose` 诊断输出。结果打印到 stdout 并复制到剪贴板。CLI 只读配置，不回写（与运行中的 GUI 互不干扰）。

## 快捷键（应用内）

默认（可在设置中修改）：

| 操作 | 快捷键 |
|------|--------|
| 翻译 | `Ctrl+Return` |
| 截图翻译 | `Ctrl+Shift+S` |
| 提取文字 | `Ctrl+Shift+T` |
| 粘贴图片 | `Ctrl+Shift+V` |
| 交换语种 | `Ctrl+Shift+X` |
| 复制结果 | `Ctrl+Shift+C` |

> 源语言为「自动检测」时不可交换语种。

## 截图翻译流程

1. 点击 **截图翻译** 或快捷键
2. 框选区域（`Esc` 取消）
   - Linux：`slurp` 框选，`grim` 截取
   - Windows：Qt 全屏遮罩拖拽框选（截图期间主窗口自动隐藏）
3. 按当前模式：
   - **OCR**：tesseract 识别（小图自动 2x 放大提升识别率）→ 文本模型翻译
   - **Vision**：图片降采样后直接发给视觉模型翻译

> 只想要图里的文字？用 **提取文字**（`Ctrl+Shift+T`）：OCR 结果直接进原文框并复制，不调用翻译。

## 项目结构

```
app/
  config/                  # JSON 配置 schema + 存取（XDG / %APPDATA%）
  core/
    screenshot.py          # 截图门面（按平台选择后端）
    screenshot_wayland.py  #   slurp + grim 后端
    screenshot_windows.py  #   Qt 遮罩框选后端
    clipboard_image.py     # 剪贴板图片门面
    clipboard_wayland.py   #   wl-paste 后端
    clipboard_windows.py   #   Qt clipboard 后端
    llm_client.py          # OpenAI 兼容 HTTP 客户端
    translator.py          # 翻译编排（文本 / OCR / Vision）
    ocr.py  prompts.py  languages.py
    hotkey_win.py          # Windows 全局呼出热键（RegisterHotKey）
  workers/                 # QThreadPool 后台任务 + TaskRunner
  ui/                      # 主窗口、设置、主题 QSS
  ipc.py                   # 单实例唤起（第二实例 → 通知首实例）
packaging/
  linux/                   # PKGBUILD + makepkg 构建脚本
  windows/                 # PyInstaller spec + 构建脚本
```

## 测试与 CI

```bash
pip install -e .[dev]
ruff check app tests
QT_QPA_PLATFORM=offscreen pytest -q
```

GitHub Actions（`.github/workflows/ci.yml`）在 3.11/3.12/3.13 上跑 ruff + pytest（offscreen Qt），并附一次 Windows PyInstaller 冒烟构建；mypy 暂为非阻塞观察项。

## 故障排查

| 现象 | 处理 |
|------|------|
| Linux 窗口不显示 / 白屏 | 确认在 Wayland 会话；`echo $XDG_SESSION_TYPE`；设置 `QT_QPA_PLATFORM=wayland` |
| Linux 截图无反应 | 确认 `grim`、`slurp` 在 PATH；niri 下直接运行 `slurp` 测试 |
| CLI 报「未找到 wl-paste 或 xclip」 | 安装 `wl-clipboard`（Wayland）或 `xclip`（X11）；`ai-translator-cli --clipboard` 依赖它们读剪贴板 |
| CLI 没有通知 | 桌面通知依赖 `notify-send`（libnotify），缺失时静默跳过，翻译本身不受影响 |
| Windows 粘贴图片失败 | 先复制一张图片；部分程序复制的是文件引用而非图片数据 |
| OCR 报缺语言包 | Linux：`sudo pacman -S tesseract-data-eng tesseract-data-chi_sim`；Windows：UB-Mannheim 安装器勾选对应语言 |
| OCR 找不到 tesseract | Windows：安装后将 `tesseract.exe` 目录加入 PATH，或在设置中填「Tesseract 路径」 |
| 全局呼出热键不生效（Windows） | 组合可能被其他程序占用，换一个（如 `Ctrl+Alt+Y`）；修改后需重启应用 |
| 401 / 鉴权失败 | 检查 API Key 与 Base URL 是否匹配该服务商 |
| 模型输出思维链/分析过程 | 客户端只提取 `<final_translation>` 标签内的结果，标签外内容自动丢弃；若模型连标签也不输出，建议更换非推理模型（如 `deepseek-chat`） |
| Vision 报错 | 确认模型支持图像输入；或改用 OCR 模式 |

## 许可

MIT
