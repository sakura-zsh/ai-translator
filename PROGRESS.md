# 项目进度存档（AI Translator）

> 最后更新：2026-11-26（`feat/tauri-rewrite` 分支）。`main` 分支完整保留 Python + PySide6 v0.5.0 作为基线对照。

## 一、当前状态一句话

**0.6.0（2026-11-26）：完成 Rust + Tauri v2 + React + Tailwind 全量重写，100% 兼容原有 `config.json` 与功能集。**

## 二、架构与完成清单

- ✅ **Workspace 结构**：
  - `crates/core`：纯 Rust 核心库（零 GUI 依赖），涵盖：
    - `config/`：`schema.rs` + `store.rs`（100% 兼容 v0.5.0 JSON 字段、单模型旧配置迁移、原子写入与 Linux `0600` 权限）。
    - `providers.rs`：10 家内置服务商模板。
    - `languages.rs`：20 种语言代码与 prompt 语言名。
    - `presets.rs` & `prompts.rs`：5 个内置场景 + 自定义场景（上限 20）+ 术语表解析/注入 + `<final_translation>` 提示词构建。
    - `imaging.rs` & `ocr.rs`：MIME 嗅探、PNG 归一化、Vision 降采样、OCR 2x 放大、`tesseract` CLI 封装。
    - `llm_client.rs`：Chat Completions + Responses 双协议、`reasoning_effort` 自动回退重试、思维链剥离与 `<final_translation>` 提取。
    - `jev_client.rs`：System One 原生 / OpenAI 双协议自动探测与路由缓存、场景路由、语种检测、质量评分。
    - `translator.rs`：文本 / OCR / Vision / Jev 联合编排（含低分自动重译一次）。
    - `tts.rs`：自研 Edge TTS WebSocket（含 `Sec-MS-GEC` 令牌）与 200 条 MP3 磁盘缓存（兼容原缓存目录）。
    - `platform.rs`：Wayland `slurp + grim` / `wl-paste` / `wl-copy` / `notify-send` 与 Windows `arboard` 剪贴板。
  - `crates/cli`：原生 `ai-translator-cli` 二进制（`clap`），对齐全部参数，只读配置不回写 GUI 编辑。
  - `src-tauri`：Tauri v2 桌面壳，集成单实例唤起（`tauri-plugin-single-instance`）、系统托盘、每日日志轮转、Windows `xcap` 多屏截取与全局热键（`tauri-plugin-global-shortcut`）。
  - `src/`：React 19 + TypeScript + Tailwind v4 + Catppuccin Mocha / Latte 双主题前端，覆盖主界面、分栏拖拽、底部三层向上展开模型选择器、历史搜索抽屉、4 页签设置模态框、模型目录弹窗、自定义场景管理、首启向导与 Windows 截图框选层。
- ✅ **打包与 CI**：更新 `packaging/linux/PKGBUILD`、`packaging/linux/build-package.sh`、`packaging/windows/build-windows.ps1` 与 `.github/workflows/ci.yml`。
