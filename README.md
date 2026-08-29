# AI Translator

轻量级桌面 AI 翻译工具，跨平台：**Linux（Wayland）** 与 **Windows** 共用同一套代码，仅打包方式不同。

- 多 LLM 配置（OpenAI 兼容接口：OpenAI / DeepSeek / SiliconFlow / Ollama …）
- 源语言自动检测，目标语言可选，语种互换
- 文本翻译 / 截图翻译 / 粘贴图片翻译
- 图片模式可切换：**OCR**（tesseract）或 **Vision**（视觉模型）
- 已是目标语言时自动反向翻译
- 自定义补充提示词
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

首次启动会自动生成默认配置。在 **设置 → LLM 配置** 中填写：

| 字段 | 说明 |
|------|------|
| Base URL | 如 `https://api.openai.com/v1`、`https://api.deepseek.com/v1`、`http://127.0.0.1:11434/v1` |
| API Key | Bearer Token（本地 Ollama 可留空） |
| API 协议 | **Chat Completions**（`/chat/completions`，默认）或 **Responses**（`/responses`，部分中转站） |
| 文本模型 | 如 `gpt-4o-mini`、`deepseek-chat`、`llama3.2` |
| 视觉模型 | 支持图片的模型，如 `gpt-4o`、`llava` |

> 中转站若只给 Responses 协议，把 API 协议切到 **Responses**，Base URL 仍填到 `/v1` 即可（会自动请求 `/v1/responses`）。

可添加多个配置，主界面顶部下拉框即时切换。

### 补充提示词示例

```
使用正式书面中文，保留专业术语英文原文，不要意译品牌名。
```

## 快捷键（应用内）

默认（可在设置中修改）：

| 操作 | 快捷键 |
|------|--------|
| 翻译 | `Ctrl+Return` |
| 截图翻译 | `Ctrl+Shift+S` |
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
   - **OCR**：tesseract 识别 → 文本模型翻译
   - **Vision**：图片直接发给视觉模型翻译

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
  workers/                 # QThreadPool 后台任务
  ui/                      # 主窗口、设置、主题 QSS
packaging/
  linux/                   # PKGBUILD + makepkg 构建脚本
  windows/                 # PyInstaller spec + 构建脚本
```

## 测试

```bash
pip install pytest
pytest -q
```

## 故障排查

| 现象 | 处理 |
|------|------|
| Linux 窗口不显示 / 白屏 | 确认在 Wayland 会话；`echo $XDG_SESSION_TYPE`；设置 `QT_QPA_PLATFORM=wayland` |
| Linux 截图无反应 | 确认 `grim`、`slurp` 在 PATH；niri 下直接运行 `slurp` 测试 |
| Windows 粘贴图片失败 | 先复制一张图片；部分程序复制的是文件引用而非图片数据 |
| OCR 报缺语言包 | Linux：`sudo pacman -S tesseract-data-eng tesseract-data-chi_sim`；Windows：UB-Mannheim 安装器勾选对应语言 |
| OCR 找不到 tesseract | Windows：安装后将 `tesseract.exe` 目录加入 PATH |
| 401 / 鉴权失败 | 检查 API Key 与 Base URL 是否匹配该服务商 |
| Vision 报错 | 确认模型支持图像输入；或改用 OCR 模式 |

## 许可

MIT
