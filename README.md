# AI Translator

轻量级桌面 AI 翻译工具，面向 **CachyOS + niri（Wayland）**。

- 多 LLM 配置（OpenAI 兼容接口：OpenAI / DeepSeek / SiliconFlow / Ollama …）
- 源语言自动检测，目标语言可选，语种互换
- 文本翻译 / 截图翻译 / 粘贴图片翻译
- 图片模式可切换：**OCR**（tesseract）或 **Vision**（视觉模型）
- 自定义补充提示词
- 现代化深色 / 浅色主题（Catppuccin 风格 QSS）

## 依赖

### 系统

```bash
# 截图与剪贴板（你的环境通常已具备）
sudo pacman -S grim slurp wl-clipboard

# OCR 模式（可选，Vision 模式可不装）
sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim
```

### Python

```bash
cd /path/to/ai_translator
python -m venv .venv
# bash/zsh:
source .venv/bin/activate
# fish:
#   source .venv/bin/activate.fish
pip install -e .
# 或：pip install -r requirements.txt
```

需要：Python ≥ 3.11，`PySide6`、`httpx`、`Pillow`。

## 运行

```bash
# 推荐：直接用 venv 解释器（bash / zsh / fish 通用，无需 activate）
QT_QPA_PLATFORM=wayland .venv/bin/python -m app

# 已 activate 时：
QT_QPA_PLATFORM=wayland python -m app

# 安装入口脚本后：
.venv/bin/ai-translator
```

> **fish 用户注意**：不要 `source .venv/bin/activate`（那是 bash 脚本）。请用  
> `source .venv/bin/activate.fish`，或直接调用 `.venv/bin/python`。

## 配置

配置文件：`~/.config/ai-translator/config.json`（权限 `600`）。

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
2. `slurp` 框选区域（`Esc` 取消）
3. `grim` 截取 PNG
4. 按当前模式：
   - **OCR**：tesseract 识别 → 文本模型翻译
   - **Vision**：图片直接发给视觉模型翻译

## 项目结构

```
app/
  config/          # JSON 配置 schema + 存取
  core/            # LLM / 翻译 / 截图 / OCR / 剪贴板
  workers/         # QThreadPool 后台任务
  ui/              # 主窗口、设置、主题 QSS
```

## 测试

```bash
pip install pytest
pytest -q
```

## 故障排查

| 现象 | 处理 |
|------|------|
| 窗口不显示 / 白屏 | 确认在 Wayland 会话；`echo $XDG_SESSION_TYPE`；设置 `QT_QPA_PLATFORM=wayland` |
| 截图无反应 | 确认 `grim`、`slurp` 在 PATH；niri 下直接运行 `slurp` 测试 |
| OCR 报缺语言包 | `sudo pacman -S tesseract-data-eng tesseract-data-chi_sim` |
| 401 / 鉴权失败 | 检查 API Key 与 Base URL 是否匹配该服务商 |
| Vision 报错 | 确认模型支持图像输入；或改用 OCR 模式 |

## 许可

MIT
