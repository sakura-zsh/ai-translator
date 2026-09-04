# 项目进度存档（AI Translator）

> 最后更新：2026-09-04。本文件供跨会话恢复开发用，完成某项后请打勾并更新「当前状态」。

## 一、当前状态一句话

**§3.2 之后新增：单实例唤起（IPC）+ 场景进设置页 + 托盘退出修复 + §3.3 全部完成（124 测试全过，ruff 全绿）。**
✅ 单实例唤起：`app/ipc.py`（ActivateServer/notify_running，QLocalServer socket "ai-translator-activate"）；第二实例启动 → 发送 "activate" 并退出 → 首实例 `MainWindow.summon()` 弹出/聚焦窗口。niri 等合成器快捷键绑定启动命令即可恢复"呼出"工作流，不依赖任何合成器。注意：GlobalShortcuts 门户在 niri/wlroots 系不可用（无后端），未采用。
✅ 设置→翻译页：「翻译场景」下拉 + 缩小的补充提示词（56–96px）+ **术语表编辑器**（`parse_glossary`/`format_glossary` 在 presets.py，每行一条，分隔符 = / → / -> / Tab，最早出现者切分，上限 100）+ **Tesseract 路径** QLineEdit。
✅ 设置→外观页：**close_to_tray** QCheckBox + **历史条数** QSpinBox(0..100)，缩小时同步截断内存 history；对话框最小高度 566→620。
✅ 托盘退出修复：窗口隐藏时托盘「退出」无效——`quitOnLastWindowClosed` 只对可见窗口的 close 反应；`_quit()` 现在在 close() 后显式 `QApplication.quit()`。
✅ 新增测试：tests/test_ipc.py 4 个 + 集成测试 14 个（场景 roundtrip、提示词紧凑、summon 显隐、隐藏态 _quit 持久化、glossary 解析/roundtrip/上限、术语表+tesseract 控件 roundtrip、close_to_tray 控件、历史条数截断、历史搜索过滤、卡片复制信号分离、历史译文复制）。
✅ §3.4 历史面板增强（2026-09-03，127 测试全过）：HistoryPanel 顶部搜索框（textChanged → source_text+result_text 不区分大小写子串过滤，实时重渲染；`_all_entries` 缓存全量，清空搜索框恢复；无匹配显示「无匹配记录」）；HistoryCard meta 行加「复制」按钮 → `copy_requested(entry_id)` → 面板转发 → MainWindow `_on_history_copy`（复制译文到剪贴板 + 状态栏提示，面板不关闭；按钮点击不触发卡片激活）。面板高度 390→430 容纳搜索行。
⬜️ 剩余：无（§3.x 批次全部完成；剩余事项均为跨平台实测，见下方「待实测」）。
✅ §3.6 测试补齐（2026-09-04，148 测试全过）：新增 tests/test_ui_smoke.py 6 个（offscreen session QApplication + QMessageBox 打桩：ModelSelector 状态行高度稳定、推理模型提醒切换、模板填充 profile、工具栏切换配置持久化、提取文字回填+Qt 剪贴板自动复制（patch shutil.which 禁用 wl-copy）、首启向导构建）；test_config.py 补 schema 清洗 roundtrip（glossary 空键值清洗、history_limit 钳制 0..100 且截断、splitter_sizes 类型过滤）。其余 §3.6 清单项（CLI/glossary 注入/normalize_to_png/presets 兜底）此前已覆盖。
✅ §3.7 CI（2026-09-04）：.github/workflows/ci.yml —— test job matrix 3.11/3.12/3.13（apt 装 offscreen Qt 依赖 → pip install -e .[dev] → ruff → offscreen pytest → mypy 非阻塞 continue-on-error）+ windows-build job（PyInstaller onedir 冒烟构建，防 spec 腐化）。注：仓库当前无远端，推送 GitHub 后生效。
✅ §3.8 收尾（2026-09-04）：README 补 CLI 用法（含 niri/Hyprland bind 示例）、翻译场景/术语表/历史/托盘与唤起/Windows 全局呼出章节、快捷键表、故障排查新增 CLI×2 + Tesseract 路径 + 热键占用行、测试与 CI 章节、项目结构补 ipc/hotkey_win/TaskRunner。全量验证通过：148 pytest 全绿 + ruff 全绿 + 全量 UI 冒烟（窗口/历史/设置/场景管理/向导）+ `bash packaging/linux/build-package.sh` 产出 ai-translator 0.2.0-2 any.pkg.tar.zst（188K，包内含 ipc.py/hotkey_win.py）。
✅ §3.5 TaskRunner 抽取（2026-09-04，139 测试全过）：`app/workers/tasks.py` 新增 `TaskRunner(QObject)`（busy 属性 + `run(work, on_ok=None, on_err=None)`，busy 期间二次提交直接丢弃；ok/err 回调经绑定槽 `_on_finished`/`_on_error` 分发——**勿直接把闭包连到跨线程信号**，PySide 对非 QObject 接收者持弱引用会丢回调/段错误）；busy 视觉部分（_set_busy/按钮禁用）仍留在各调用方。五处样板全部迁移：main_window（translate_text/translate_image/screenshot/extract）、settings_dialog（test_connection）、first_run_dialog（test_connection）、widgets.py ModelSelector（fetch_models）。FunctionWorker 不再被 UI 层直接引用。
✅ 新增测试 5 个（tests/test_task_runner.py，专用 QThreadPool）：结果投递+busy 复位、异常对象投递（类型保留）、busy 期间二次提交忽略、无回调安全、任务确在 worker 线程执行。
✅ 自定义翻译场景（2026-09-04，134 测试全过）：5 个内置场景（presets.py SCENE_PRESETS，只读）+ 用户自定义（config `translation.custom_scenes`，dict {id,label,prompt}，schema `sanitize_custom_scenes` 清洗去重上限 20）；`all_scene_presets`/`get_scene(id, custom)`/`scene_prompt`/`effective_extra_prompt` 全部支持 custom；设置→翻译页「管理…」按钮打开 SceneManageDialog（内置只读标记，自定义可增删改，编辑实时写回）；工具栏与设置页下拉均动态重建（_apply_translation_defaults / _reload_scene_combo），删除当前选中自定义场景自动回退通用。
✅ Windows 全局呼出热键（2026-09-04）：`app/core/hotkey_win.py`（ctypes RegisterHotKey/UnregisterHotKey，MOD_NOREPEAT，纯函数 parse_hotkey 可跨平台单测：Ctrl/Alt/Shift/Win + 字母/数字/F1–F24，必须含修饰键）；MainWindow `_setup_windows_hotkey`（win32 only，init 与 reload_config 时注册/重注册）+ `nativeEvent` 捕获 WM_HOTKEY → `summon()`（托盘隐藏态可用）+ closeEvent 注销；配置 `ui.hotkeys.summon` 默认 "Ctrl+Alt+T"，设置→外观页新增「全局呼出」行（Linux 下该字段无效，提示用合成器快捷键绑定启动命令）。
✅ Windows 热键修复（2026-09-04，用户实测无效无提示后重构）：① 新增应用级 `HotkeyNativeFilter`（QAbstractNativeEventFilter，main.py 安装，`install_native_filter(window.summon)`）作为 WM_HOTKEY 主投递路径——应用级 filter 收到 Qt 分发的全部窗口消息，不再依赖可能被静默丢弃的 widget 级 nativeEvent（后者保留为兜底，summon 幂等，双投递无害）；② 注册成败均给**托盘气泡**（`_notify_tray`，"全局热键已启用" / "注册失败可能被占用"），不再依赖状态栏（原状态栏提示在 init 里被"就绪"立即覆盖）；③ init 顺序调整：`_set_status("就绪")` 先于热键注册。Windows 端实测：启动应见"全局热键已启用"气泡，按 Ctrl+Alt+T 应呼出。
✅ 新增测试 7 个（集成共 21 个）：parse_hotkey 序列（含非法输入）、custom_scenes 清洗/上限、自定义场景查找/叠加提示词、工具栏下拉显示自定义场景、自定义场景切换持久化、场景管理对话框增改+内置只读+设置 roundtrip、summon 热键 roundtrip（含旧配置缺字段回退默认）。
✅ Windows 打包瘦身（2026-09-03）：① pyproject 依赖 `PySide6` → `PySide6-Essentials>=6.6`（代码只用 Core/Gui/Widgets/Network，已 grep 确认；省掉 Addons 的 WebEngine/3D 等 ~1GB）；② spec excludes 全部未用 PySide6 子模块 + tkinter；③ build-windows.ps1 去掉 `--clean`（保留 PyInstaller 依赖分析缓存，重建显著加速）和 `pip install --upgrade`（免每次联网检查）。注：PySide6 应用首次打包 5–15 分钟属正常，非卡死。Windows 端打包待实测。
⚠️ 升级注意：旧版本实例持有锁且无 IPC，升级后需先彻底退出旧实例（Ctrl+Q 或托盘退出），否则第二实例会提示"暂时无法通知"。

---

## 二、已完成并验证的工作（勿重做）

### Bug 修复（全部有回归测试）
1. ✅ 首启动只读 FS 崩溃 → `store.load()` 首次写入 best-effort
2. ✅ Wayland 文本粘贴空转 6 个子进程 → `clipboard_wayland.read_png()` 无 image/* 时快速失败
3. ✅ Worker 错误信号改发异常对象 `Signal(object)`，UI 用 `isinstance(exc, ScreenshotCancelled)` 判断
4. ✅ 退出竞态：`closeEvent` 先 `pool.clear()+waitForDone(2000)`；`_save_config()` 统一吞 OSError
5. ✅ Vision 载荷降采样：`imaging.downscale_for_vision()`（长边>2000 必降采样，不透明转 JPEG），`chat_vision` 的 data URL 用 `sniff_image_mime` 跟随真实格式；OCR 路径保持原图
6. ✅ wl-copy 假成功 → `check=True` 失败回落 Qt 剪贴板
7. ✅ 思维链泄漏三层修复：`strip_reasoning()`（<think> 块剥离）+ 提示词硬化（禁止推理、纯命令原样返回）+ **`<final_translation>` 标签提取**（`extract_tagged_final()`，提示词要求模型包裹答案，客户端只取标签内；未闭合/无标签均有兜底）
8. ✅ ModelSelector 布局挤压：状态行改为**常驻占位一行**（`setFixedHeight`，Ignored 水平策略），长文本进 tooltip；设置对话框最小高度 566
9. ✅ 打包脚本自递归 22GB 事故：暂存目录改 `mktemp -d` + trap 清理、exclude 路径修正、50MB 保险丝（详见 git log 提交说明）
10. ✅ 死代码清理（menu_label / build_user_text_message / status 信号 / 空 pass 块）

### 新功能（v0.1.0 已含）
- 自动复制译文开关（设置→翻译）
- 服务商模板 10 家（`app/core/providers.py`）+ `LlmClient.list_models()`（`GET /models`，兼容 OpenAI/Ollama 两种响应）+ `ModelSelector` 组件（可编辑下拉+获取按钮+推理模型提醒 `_REASONING_MODEL_RE`）
- 首启向导 `app/ui/first_run_dialog.py`（`config.needs_setup()` 触发，可跳过）
- 提取文字模式（按钮+Ctrl+Shift+T；`imaging.prepare_for_ocr()` 小图 2x 放大）
- OCR 预处理已接入 `OcrService.extract_text`

### 工程基础（本轮 0.2.0 批次已完成部分）
- ✅ **版本单源**：`app/__init__.py` `__version__ = "0.2.0"`；main.py 导入它；pyproject `dynamic = ["version"]` + `[tool.setuptools.dynamic] attr`；`build-package.sh` 改读 `app/__init__.py`（⚠️ PKGBUILD 的 pkgver 仍是 0.1.0，下次跑脚本自动同步）
- ✅ `app/logsetup.py` 已创建（RotatingFileHandler，XDG_STATE_HOME/~/.local/state/ai-translator/，Windows %LOCALAPPDATA%/logs；main.py 已调用 `setup_logging()`）
- ✅ `requirements.txt` → `-e .`（依赖唯一来源是 pyproject）
- ✅ `.gitignore` 清理（移除失效的 src-staging 条目）
- ✅ pyproject 新增：`[project.scripts] ai-translator-cli`、`[project.optional-dependencies] dev`、`[tool.ruff]`、`[tool.mypy]`（line-length 100，select E/F/W/I/UP/B/SIM，ignore E501，ui 目录豁免 N802）
- ✅ **schema 扩展**（`app/config/schema.py`）：
  - TranslationConfig：`scene: str = "general"`、`glossary: dict[str,str]`（from_dict 清洗 ≤100 项）、`tesseract_path: str = ""`
  - UiConfig：`window_maximized: bool`、`splitter_sizes: list[int]`、`close_to_tray: bool = True`
  - AppConfig：`history_limit: int = 10`（0..100 钳制）；原 `HISTORY_LIMIT` 常量改名 `HISTORY_LIMIT_DEFAULT`，新增 `HISTORY_LIMIT_MAX = 100`；push_history/from_dict/__post_init__ 均已改用实例字段
- ✅ **场景预设** `app/core/presets.py`：5 个内置场景（general/academic/technical/casual/formal）、`get_scene()`、`scene_prompt()`、`effective_extra_prompt(config)`（预设+个人补充提示词合并）
- ✅ **术语表注入**：`build_system_prompt(..., glossary=None)` 追加 "Glossary — always render these terms exactly as given"；`Translator.translate_text/translate_image` 已加 `glossary` 参数（默认 None，向后兼容）

- ✅ **图片转换去重（原 Step 5，已完成）**：
  - `imaging.normalize_to_png(raw)`：PIL 解码→RGB(A)→PNG，失败 `raise ValueError`（与 `downscale_for_vision` 的"不可解码原样返回"语义不同，调用方需自行兜底）
  - 新建 `app/core/qtimage.py`：`qimage_to_png_bytes()`（Qt 编码优先，Pillow 兜底）；放在 core 是因为后端需要它而 core 不能 import ui
  - `widgets.py` 改为 `from app.core.qtimage import qimage_to_png_bytes` 并加 `__all__` 显式 re-export；`main_window.py` 两处改为顶层导入 core 版本
  - `clipboard_windows.py` 删私有 `_qimage_to_png`/`_to_png`；`clipboard_wayland.py` 删私有 `_to_png`；`screenshot_windows.py` 的 `_pixmap_to_png_bytes` 由 40 行缩到 3 行
- ✅ **CLI 模式（`app/cli.py`，已完成）**：文本参数 / `--clipboard` / `--image` / `--screenshot` / stdin；`-s`/`-t`/`--mode`/`--profile`/`--no-copy`/`--no-notify`/`--verbose`/`--config`
- ✅ **ruff 全绿**：`ruff check app tests` → All checks passed（修 2 处 I001、1 处 F401、5 处 SIM105、2 处 SIM108、2 处 SIM102）

**✅ 测试状态：96 passed（基线 76 + 新增 20）。** ruff 全绿，offscreen GUI 冒烟全过（MainWindow / SettingsDialog / HistoryPanel / FirstRunDialog 均可构造）。

---

## 三、剩余工作清单（按建议实施顺序）

### 3.2 主窗口接入新配置（✅ 已完成，见「一、当前状态」）
- ✅ 工具栏「场景」QComboBox（SCENE_PRESETS，on change → `config.translation.scene` + `_save_config()`）；busy 时随其他控件一并禁用
- ✅ 两条翻译路径 `extra = effective_extra_prompt(self.config.translation)`；translate_text/translate_image 均传 `glossary=self.config.translation.glossary or None`
- ✅ `_rebuild_translator()`：`Translator(ocr=OcrService(tesseract_bin=config.translation.tesseract_path or "tesseract"))`；`__init__` 与 `reload_config()` 均调用
- ✅ 窗口状态：`window_maximized` → `setWindowState(WindowMaximized)`；splitter 恢复/写回（len==2 且和>0 才用）
- ✅ 单实例锁：`app/main.py` QLockFile(tempdir/"ai-translator.lock")，tryLock(0) 失败 → stderr + return 0；锁对象存活至进程结束
- ✅ 单实例唤起（2026-09-03 追加）：`app/ipc.py` ActivateServer（QLocalServer）+ notify_running（QLocalSocket）；main.py 锁失败 → 通知首实例后退出；首实例 `command_received("activate")` → `MainWindow.summon()`（show+raise+activate，先清 minimized）；listen 前 `QLocalServer.removeServer` 清理崩溃残留；socket 不可用仅 log 降级
- ✅ 设置页场景控件（2026-09-03 追加）：`settings_dialog._build_translation_tab` 新增 t_scene 下拉 + 补充提示词缩小（56–96px）置于其下；`_on_accept` scene=self.t_scene.currentData()
- ✅ 托盘：QSystemTrayIcon + 程序化图标（64px 圆角蓝底白「译」）；菜单：显示/隐藏、截图翻译、提取文字、粘贴图片翻译、退出；单击切换窗口；`closeEvent` 托盘可用且 close_to_tray 且非强制退出 → hide；Ctrl+Q 与托盘「退出」走 `_quit()`（强制退出）；`isSystemTrayAvailable()` 为 False → 不创建、正常关闭
- ✅ 日志：UI 三个 error handler 加 `log.error(..., exc_info=exc)`；`workers/tasks.py` worker 异常、`llm_client._request` 网络/HTTP 错误、`ocr.py` 失败分支均已加 log
- ✅ 测试：`tests/test_main_window_integration.py`（场景切换/持久化/busy 禁用、translator 重建、splitter 恢复、settings 透传+场景 roundtrip、close-to-tray 降级、summon 显隐）；`tests/test_ipc.py`（socket 收发、无服务降级、陈旧 socket 恢复、空载荷忽略）

### 3.3 设置对话框新控件（`app/ui/settings_dialog.py`）
- 翻译页：术语表 QPlainTextEdit（每行一条，分隔符支持 `=`、`→`、`->`、Tab；解析函数可放 presets.py 或 dialog 内 `_parse_glossary()`；上限 100 条）；tesseract 路径 QLineEdit（placeholder "tesseract（留空用 PATH）"）
- 外观页：`close_to_tray` QCheckBox「关闭时最小化到托盘」；历史条数 QSpinBox(0..100)（写 `config.history_limit`，在 `_on_accept` 里 `self._config.history_limit = ...`，注意 UiConfig 构造不含它）
- `_on_accept` 的 TranslationConfig/UiConfig 构造补齐新字段（scene 不在设置页，保持原值传递；window_maximized/splitter_sizes 原值透传，别丢了）

### 3.4 历史面板增强（`app/ui/history_panel.py`）
- 顶部 QLineEdit 搜索框（objectName 建议历史搜索样式沿用 hintLabel），`textChanged` → 过滤（source_text+result_text 不区分大小写子串）后重新 `set_entries`
- `set_entries` 前先存 `self._all_entries`；清空搜索框时全量显示
- HistoryCard meta 行加「复制」小按钮 → 新信号 `copy_requested(str)`（entry_id）→ 面板转发 → MainWindow `_on_history_copy`：`_copy_text_to_clipboard(entry.result_text)` + 状态栏提示（面板不关闭）
- HistoryPanel 构造后需 `refresh`（MainWindow 打开面板时已 set_entries ✓）

### 3.5 TaskRunner 抽取（worker 样板去重，中等风险）
- 现状：translate/image/extract/screenshot/test-connection 五处重复 `FunctionWorker + finished/error connect + busy 切换`
- 方案：`app/workers/tasks.py` 加 `TaskRunner(QObject)`：`busy` 属性、`run(work, on_ok, on_err=None)`（内部 FunctionWorker + 信号转发，error 传异常对象）；MainWindow 持有实例，`_set_busy` 视觉部分留在窗口（runner.busy 改变时回调）
- 可渐进：先新代码用，旧方法逐步迁移；UI 冒烟全绿才算完成

### 3.6 测试补齐
- 单元：glossary 注入 prompt 断言、`effective_extra_prompt` 组合、presets 兜底（未知 id → general）、schema 新字段 roundtrip（glossary 清洗、history_limit 钳制、splitter_sizes 类型过滤）、CLI argparse + 文本翻译路径（mock LlmClient）、normalize_to_png
- `tests/test_ui_smoke.py`（新）：`pytest.importorskip("PySide6")`；session 级 QApplication fixture（`QT_QPA_PLATFORM=offscreen`）；QMessageBox.information/warning 打桩防模态阻塞；移植此前 /tmp 冒烟的关键断言：①ModelSelector 状态文字变化前后 height/combo height 不变 ②推理模型提醒文案切换 ③模板选择填充 base_url/model ④配置切换回写路径 ⑤提取文字 handler + 自动复制（patch shutil.which 禁用 wl-copy 走 Qt 剪贴板）⑥向导构建
- 注意旧测试：`test_config.py::test_history_keeps_ten_newest` 仍应过（默认 limit=10）

### 3.7 CI + Lint
- `.github/workflows/ci.yml`：matrix 3.11/3.12/3.13；`pip install -e .[dev]`；apt 装 `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`（offscreen Qt 需要）；`QT_QPA_PLATFORM=offscreen ruff check app tests` + `QT_QPA_PLATFORM=offscreen pytest -q`；mypy 可加为 non-blocking（`continue-on-error: true` 先观察）
- 本地先跑 `ruff check app tests` 修问题（预计有未用 import 等 F 类）；mypy 按需放行

### 3.8 收尾
- README：CLI 用法（niri/hyprland bind 示例）、托盘、场景、术语表、历史、新设置项、故障排查补「CLI」行
- 全量验证：`pytest -q` → offscreen UI 冒烟 → `bash packaging/linux/build-package.sh`（应出 0.2.0 包）→ 用 `--schemas` 无所谓，重装 `sudo pacman -U` 实测一轮

---

## 四、验证命令速查

```bash
pip install --target /tmp/pylibs pytest            # 沙箱每次 /tmp 被清后重装
PYTHONPATH=/tmp/pylibs python -m pytest -q         # 基线：中断前 76 passed
# UI 冒烟需要 PySide6：pip install --target /tmp/pylibs PySide6（约 500MB，较慢）
# 仓库内不要装任何东西！.testlibs 事故：665MB 曾被 rsync 卷进打包流程
QT_QPA_PLATFORM=offscreen python -m app            # 冒烟跑 GUI
bash packaging/linux/build-package.sh              # 产出 ai-translator-0.2.0-*.pkg.tar.zst
```

## 五、关键设计决策记录（避免重新讨论）

- 标记提取用 XML 标签 `<final_translation>` 而非 emoji（译文可能含 emoji；模型复现 XML 更可靠；中转不碰 ASCII）
- 场景预设与个人补充提示词**叠加生效**：preset 在前、personal 在后，settings 只编辑 personal
- 术语表 prompt 注入上限 100 条；config 加载时清洗空项
- 状态行常驻占位（防止布局跳动），超长文本走 tooltip
- 托盘不可用（无 SNI 的 Wayland）→ 自动降级为普通关闭行为
- CLI 不依赖 Qt（Linux），保证 headless/脚本场景可用
