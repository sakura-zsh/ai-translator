# AI Translator

轻量级跨平台桌面 AI 翻译工具（**Rust + Tauri v2 + React + Tailwind**），支持 **Linux（Wayland）** 与 **Windows**，共享同一套 Rust 核心库与原生极速 CLI。

- 多 LLM 配置（OpenAI 兼容接口：Chat Completions `/chat/completions` 与 Responses `/responses`），**支持 SSE 实时流式输出**
- 源语言自动检测，目标语言可选，语种互换，已是目标语言时自动反向翻译
- **单词 / 短语自动词典模式**：1–3 个英文单词自动输出音标（IPA）、词性、释义、例句与常见搭配
- **划词 / 选区快翻小窗**（`ai-translator --quick`）：Linux 读取 Primary Selection（无需复制），Windows 全局热键 `Ctrl+Alt+Q` 呼出紧凑悬浮窗
- 文本翻译 / 截图翻译 / 粘贴图片翻译，图片模式支持 **OCR**（`tesseract`）与 **Vision**（视觉模型）
- **提取文字**：OCR 提取截图文字到原文框并复制到剪贴板，不调用翻译
- **翻译场景**：5 个内置预设（通用/学术/技术/口语/正式）+ 自定义场景（最多 20 个），与补充提示词叠加生效
- **术语表**：固定译法（最多 100 条），翻译时严格按指定译法渲染
- **历史记录 & 生词本（收藏夹）**：历史可调条数（0–100）+ 搜索；生词本支持星标收藏、TTS 朗读、导出 **Markdown / Anki TSV**，支持完整配置 JSON 导出与导入
- **底部模型 / 推理强度选择器**：三层向上展开浮层（服务商标题栏切换 → 候选模型 → 5 档推理强度滑杆），支持网关不兼容时自动去掉推理参数重试
- **Jev 智能判断（可选）**：辅助场景自动路由、语种检测、译文质量评分与低分重译
- **TTS 朗读**：内置 Edge 神经语音 WebSocket 合成与本地 MP3 缓存（200 条 LRU），支持左键正常语速 / 右键慢速 `-50%` 跟读、翻译后自动朗读
- **桌面增强**：系统托盘（无托盘环境自动降级）、单实例唤起、Windows 全局呼出热键、Catppuccin Mocha / Latte 深浅主题
- **原生 CLI**（`ai-translator-cli`）：纯 Rust 编译单二进制，无 GUI 依赖，毫秒级启动

## 平台后端

| 功能 | Linux (Wayland) | Windows |
|------|-----------------|---------|
| UI 壳层 | Tauri v2 (`webkit2gtk-4.1`) | Tauri v2 (WebView2) |
| 截图 | `slurp` + `grim` | `xcap` 虚拟桌面捕获 + 全屏框选窗口 |
| 剪贴板 | `wl-paste` / `wl-copy` | `arboard` 原生剪贴板 |
| TTS 播放 | Rust Edge WebSocket + Web `<audio>` | Rust Edge WebSocket + Web `<audio>` |
| 配置路径 | `~/.config/ai-translator/config.json` | `%APPDATA%\ai-translator\config.json` |
| 打包 | `makepkg`（pacman） | Tauri NSIS / MSI + CLI 二进制 |

> 与原 Python v0.5.0 的 `config.json` 及 TTS 缓存完全兼容，可直接平滑升级。

## 依赖与开发构建

### Linux（Arch / CachyOS）

```bash
sudo pacman -S rust cargo nodejs pnpm webkit2gtk-4.1 gtk3 libappindicator-gtk3
# 运行期可选依赖
sudo pacman -S grim slurp wl-clipboard libnotify tesseract tesseract-data-eng tesseract-data-chi_sim
```

### 本地开发与测试

```bash
pnpm install
pnpm typecheck
pnpm test
pnpm tauri dev
```

### 生产构建与测试

```bash
pnpm build
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release -p ai-translator --features custom-protocol
cargo build --release -p ai-translator-cli
```

## 打包

### Linux（pacman 包）

```bash
./packaging/linux/build-package.sh
sudo pacman -U packaging/linux/ai-translator-0.6.0-*.pkg.tar.zst
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build-windows.ps1
```

## CLI（无界面翻译）

```bash
ai-translator-cli "Hello world"
ai-translator-cli --primary            # 翻译鼠标选区（Wayland Primary Selection）
ai-translator-cli --clipboard -t ja
ai-translator-cli --clipboard --image
ai-translator-cli --screenshot --mode vision
echo 'text' | ai-translator-cli
```

## Wayland 提示（niri / Hyprland）

单实例唤起与划词快翻可在合成器配置绑定：

```kdl
// niri (~/.config/niri/config.kdl)
binds {
    Mod+T { spawn "ai-translator"; }
    Mod+Shift+T { spawn "ai-translator" "--quick"; }
}
```

若 NVIDIA + Wayland 遇到 WebKitGTK 渲染异常，可尝试在启动前设置 `WEBKIT_DISABLE_DMABUF_RENDERER=1`。

## 许可

MIT
