# 项目进度存档（AI Translator）

> 最后更新：2026-11-23。本文件供跨会话恢复开发用，完成某项后请打勾并更新「当前状态」。

## 一、当前状态一句话

**0.5.0（2026-11-23）：底部「模型 / 推理强度」选择器完成——每供应商多候选、服务商标题栏下拉、视觉模型降级为备选。239 测试全过，ruff 全绿。**
✅ 引擎：`app/core/tts.py`（edge-tts 神经语音，异步合成在 worker 线程 asyncio.run，超时 30s；音频缓存 `~/.cache/ai-translator/tts/`（Windows %LOCALAPPDATA%\ai-translator\cache\tts），sha1(voice|rate|text) 键，上限 200 个自动清最旧；TtsPlayer 懒加载 QMediaPlayer/QAudioOutput，offscreen 环境不创建媒体后端）。
✅ 配置：`AppConfig.tts: TtsConfig`（voice 默认 zh-CN-XiaoxiaoNeural，rate -50..+100 钳制，auto_pronounce 开关；from_dict 全清洗）。
✅ UI：原文/译文卡片标题行 🔊 按钮（单击正常语速，右键慢速 -50%）；`_on_translate_ok` 自动朗读（auto_pronounce）；独立 `_tts_runner` 与翻译 TaskRunner 并行不互斥；合成期间双按钮禁用。
✅ 设置→翻译页：发音音色下拉（7 个精选音色 + 可粘贴任意 edge-tts 音色名）、语速偏移 SpinBox(-50..+100%)、自动朗读复选框、「试听」按钮（网络合成+播放，失败提示在服务商测试状态行）。
✅ 打包：Windows spec 移回 QtMultimedia/QtMultimediaWidgets（TTS 播放需要）；pyproject 加 `edge-tts>=6.1`；PKGBUILD optdepends 加 python-edge-tts（官方仓库无此包、仅 AUR；缺失时按钮报「语音引擎不可用」优雅降级）；版本号 0.2.0 → 0.4.0（pkgrel=1）。
✅ 测试：tests/test_tts.py 9 个（缓存键确定性、缓存命中不合成、合成失败清理、缺引擎降级、缓存清理、播放器懒加载、TtsConfig 清洗与 roundtrip）。
⬜️ 0.4 剩余：Windows 端实测 TTS（合成/播放/自动朗读）；可选增强（历史卡片发音、生词本、发音热键）。
✅ TTS 首轮实测反馈修复（2026-09-09，161 测试全过）：① 发音按钮串台——按钮标识传的是「朗读原文/朗读译文」而 _speak 派发键是「原文/译文」，字符串不匹配导致两按钮都落到译文分支；已统一传「原文/译文」且 _speak 对未知键直接返回（绝不落到另一侧）；② 朗读结束状态栏「朗读中」不消失——TtsPlayer 监听 QMediaPlayer EndOfMedia → state_changed("stopped") → 主窗口恢复「就绪」（error: 前缀则提示播放失败）；③ 按钮无图标——emoji 在部分 Windows 字体渲染为豆腐块，改用 QStyle.SP_MediaVolume 标准扬声器图标。回归测试 3 个（按钮各自派发+图标非空、未知键 no-op、播放状态复位）。

---

## 0.5.0 发布（2026-11-23）

**版本**：`app/__init__.py` 0.4.0 → **0.5.0**（pyproject 是 dynamic version，读这里）；
`packaging/linux/PKGBUILD` pkgver 同步 0.5.0、pkgrel=1。

**发布内容**（详细记录见下方「0.4.0 追加（一改～四改）」四节）：
- 底部操作栏中间新增模型 / 推理强度选择器（子控件 overlay，非系统窗口）。
- 每个服务商维护多个候选模型（上限 50）；服务商全量 `/models` 只在设置页「从服务商列表…」出现。
- 浮层三层结构：服务商标题栏（点击向上展开服务商列）→ 当前服务商的候选模型 → 推理强度滑杆 + 「管理候选模型…」。
- 视觉模型降级为备选（`vision_model=""` 表示跟随当前模型）。
- 推理强度：`chat_completions` 发扁平字段，`responses` 发 `reasoning.effort`，被网关拒绝时去参重试一次并在状态栏提示。
- 旧配置自动迁移（单模型 → 候选列表）。

**验证**：239 个测试通过（`tests/test_model_picker.py` 30 个），`ruff check app tests` 全绿。

---

## 0.4.0 追加：底部模型 / 推理强度选择器（2026-11-23，223 测试全过，ruff 全绿）

**需求**：底部操作栏中间（原为空白 stretch）加一块"选模型 + 选推理强度"的面板，交互参照 Codex 的模型选择浮层。

✅ 新组件 `app/ui/model_picker.py`：
- `ModelPickerButton`（objectName `modelPickerButton`）：文本 `模型 · 强度 ▾`，超长模型名 30 字符截断。
- `ModelPickerPopup`（`QFrame#modelPickerPanel`）：**子控件 overlay，不是系统窗口**（与 HistoryPanel 同策略，避开 Wayland 下 frameless 顶级窗口的定位问题）。内容 = 配置名 caption + 「刷新」+ 模型列表（`✓` 标记当前，点击即时生效且**不关闭面板**，便于接着调强度）+ 常驻状态行（预留高度，避免拉取时行高跳动）+ 分隔线 + 强度名居中显示 + 5 档滑杆 + `更快 / 更深入` 端点 + `↺` 重置。
- 定位 `show_above(anchor)`：面板居中于按钮上方 8px，clamp 在 central widget 内；上方不够则落到按钮下方。
- 关闭：点面板外（主窗口 `eventFilter` 复用历史面板那套逻辑，`hides_click_at` 排除触发按钮本身的点击）、Esc、窗口 resize、翻译开始（`_set_busy`）。
- 首次打开无缓存时自动在后台拉一次 `/models`（`QTimer.singleShot(0, refresh_models)`）；拉取结果按 **profile id** 回写（`models_fetched(str, list)`），切配置后的迟到回调不会串到别的配置上。

✅ 配置（`app/config/schema.py`）：
- `LlmProfile.reasoning_effort: str = ""`，白名单 `REASONING_EFFORTS = ("", minimal, low, medium, high)`，`sanitize_reasoning_effort` 清洗非法值 → `""`。
- `LlmProfile.model_options: list[str]`：`/models` 结果缓存（`sanitize_model_options` 去空去重，上限 200），让面板离线/首次打开就有列表。

✅ 请求侧（`app/core/llm_client.py`）：
- `chat_completions` 发扁平 `reasoning_effort`；`responses` 发 `reasoning: {effort}`；`""` 时**一个字段都不发**（默认路径与改动前完全一致）。
- **兼容回退**：400/422 且错误文本含 `reason`/`effort` 时，去掉该参数重试一次，并把「网关不支持推理强度，本次已按默认强度发送」写进 `LlmClient.warnings` → `TranslateResult.warnings` → 状态栏。用户设了强度却报错/静默失效都不会变成硬失败。
- `chat_vision` 同样生效。

✅ 主窗口（`app/ui/main_window.py`）：
- 按钮插在两个 stretch 之间居中；`_refresh_model_picker` 同步按钮文案与（打开中的）面板；切配置 / 设置保存后自动刷新。
- 模型切换：`vision_model` 原本与 `model` 相同 → 一起切换；用户单独设过视觉模型 → 保留，状态栏注明「图片翻译仍用 X」。
- 完成状态行追加 `· 推理 标准` 及 warnings。
- 翻译中禁用选择器（与配置/场景下拉一致）。

✅ 主题：light/dark 各补 `modelPickerButton` / `modelPickerPanel` / `modelPickerStatus` / `modelPickerSeparator` / `modelPickerList` / `modelPickerSlider` 样式。注意底部 `QMainWindow, QDialog, QWidget` 通配背景会让面板里的 QLabel 露出灰底，故 caption/status/effort 值三个 QLabel 必须显式 `background: transparent`（踩过）。

✅ 测试 `tests/test_model_picker.py`（14 个）：schema 清洗与 roundtrip、两种协议的发包形状、未设置时不发参数、被拒后重试并告警、无关 400 不重试、按钮文案、模型切换与视觉模型同步/保留、滑杆写配置+重置、列表 ✓ 标记与点击信号、面板经主窗口完整往返、缓存按 profile 落位。另修 tests/test_cli.py 与 tests/test_translator.py 的 `_StubClient` 补 `warnings` 属性。

⬜️ 待实测：DashScope（chat_completions）是否接受 `reasoning_effort`（若不接受，状态栏会出现「网关不支持推理强度」，属预期降级）；Windows 侧同一套 UI 的表现。

### 0.4.0 追加（二改）：候选模型列表 + 视觉模型降级为备选（235 测试全过，ruff 全绿）

**用户反馈**：每个供应商要能加**多个候选模型**（放弃单模型）；视觉模型单拎出来、只作备选（多数模型已原生支持图片）；主页浮层打开应是「切供应商 + 选设置里加进去的模型」，**不能**列某供应商全部可用模型（Qwen 一百多个没法用）。

✅ schema（`app/config/schema.py`）：
- `LlmProfile.models: list[str]`（候选，上限 `MODEL_CANDIDATES_MAX=50`）、`add_model` / `remove_model`（删到最后一个时自动改选剩余项）。
- 哨兵值 `MODEL_AUTO = "__auto__"`（自动挑非推理模型）、`MODEL_VISION = "__vision__"`（仅兼容旧配置）。
- `vision_model: str = ""` 表示**跟随当前模型**（隐式默认，不再镜像写入）；`vision_model_effective` 负责回落。
- `resolve_model(profile, vision_mode=False)` 统一解析哨兵；`likely_reasoning_model` 用于自动模式跳过推理模型。
- `from_dict` 迁移：无 `models` → `[model]`；`vision_model == model` → 清空（镜像已是隐式行为）。

✅ 主页浮层（`app/ui/model_picker.py` 重写）：
- 双页签「模型 / 设置」；模型页按**供应商分组**，只列各供应商 `models` 里的候选，点击行**一步**同时切 `active_profile_id` + `model`（`model_selected(profile_id, model)`）。
- 设置页 = 推理强度 5 档滑杆（原来的强制度页签）。
- 底部按钮文案 `qwen3.7-flash · 标准 ▾`。

✅ 设置页（`app/ui/model_editor.py` 新增 + `settings_dialog.py` 重构）：
- `CandidateModelEditor`：添加行（输入 + 添加 + 从服务商列表… + 删除）在上，候选列表在下；首行固定「自动选择」哨兵，可点选为当前。
- `ModelCatalogDialog`（`app/ui/model_catalog.py`）：拉 `/models` 全量，带搜索过滤，勾选后批量加入候选 —— **全量列表只在这里出现**。
- 视觉模型 `QComboBox`：首项「跟随当前模型」，其余为本供应商候选；候选增减时自动刷新，失效值回落到首项。
- 模板填充改为 `add_model(template.text_model)`，不再覆盖单模型。

✅ 修复的两个真 bug：
1. **`QFormLayout` 把候选列表压成 3 行高**：`QAbstractScrollArea` 在表单行里只按 `minimumSizeHint` 分配。改为 `tree.setMinimumHeight(_TREE_HEIGHT=150)` + 覆盖 `sizeHint`/`minimumSizeHint` 返回 `_TREE_HEIGHT + 100`。
2. **列表行文本被哨兵值覆盖**：`QTreeWidgetItem([text])` 的构造参数是**字符串列表**，只传一个字符串时 Qt 会把它当作 list 迭代；再叠加 `setData(0, 0, value)`（role 0 = `DisplayRole`）会把标签写掉。**换成 `QListWidget` + `QListWidgetItem`，载荷走自定义 role**（`int(Qt.ItemDataRole.UserRole) + 1`），QSS 选择器同步改为 `QListWidget#candidateTree`。

✅ 测试 `tests/test_model_picker.py`（26 个）：候选清洗/上限/去重、增删候选保持选中合法、两种旧配置迁移、自动模式避开推理模型、自动模式优先视觉模型、显式模型原样发送、两种协议发包形状、空强度不发参数、被拒重试、无关 400 不重试、哨兵解析后再发、候选编辑器增删选、设置对话框联动视觉下拉、按钮文案、面板按供应商分组、一步切换供应商+模型、滑杆写配置、往返交互、当前行标记、catalog 勾选子集。

### 0.4.0 追加（三改）：浮层结构重排 —— 服务商进标题栏（237 测试全过，ruff 全绿）

**用户反馈**：二改的「按服务商分组的平铺列表」不是要的样子。要的是——**服务商名称放标题栏，点标题栏向上展开一列服务商选择器；下面的列表只显示当前服务商的候选模型**。

✅ `ModelPickerPopup` 结构（`app/ui/model_picker.py` 重写为三层）：
- **标题栏**（`QFrame#modelPickerHeader`）：`QPushButton#modelPickerProvider` 显示当前服务商名 + `▾`，点击就地展开/收起服务商列；右侧 ✕ 关闭。
- **服务商列**（`QFrame#modelPickerProviders` + `QListWidget#modelPickerProviderList`）：位于标题栏与模型列表**之间**，展开时 `_relayout_growing_up()` 按"底边不动"重新定位 —— 面板向上长高，不会盖住底部触发按钮。✓ 标当前项、每项 tooltip 带候选数；最多 5 行后滚动。
- **模型列表**：只渲染 `active profile` 的 `models`，带 ✓ 当前标记；无候选时只放一行提示并 `setDisabled(True)` + `disabled_changed` 让主窗口在状态栏说明何去何从。
- **底栏**：`推理强度` 标签 + 滑杆 + 当前档名（原来独立的「设置」页签取消，强度常驻可见）；下面一行 `pickerLink` 「管理候选模型…」直达 设置 → LLM 配置。
- 新增信号：`provider_selected(str)`（只切服务商，不动该服务商的 `model`）、`disabled_changed(bool)`、`settings_requested(str)`。
- Esc 分两级：服务商列展开时先收起，再按才整块关闭。

✅ 主窗口（`app/ui/main_window.py`）：
- `_on_provider_picked`：切 `active_profile_id` 并刷新，状态栏报「已切换服务商：X · Y」。
- `_on_picker_disabled`：候选为空时状态栏提示去点「管理候选模型…」。
- `_open_settings` 拆成 `_show_settings(profile_id="", tab=-1)`；`_open_llm_settings(profile_id)` 从浮层跳转时定位到该服务商 + LLM 配置页。
- `SettingsDialog` 新增公开方法 `select_profile(pid)` / `show_tab(index)`。

✅ 主题：light/dark 各补 `modelPickerHeader` / `modelPickerProvider`（含 `[expanded="true"]`）/ `modelPickerProviders` / `modelPickerProviderList` / `pickerLink`。
- 坑：`QWidget#modelPickerProviders` 的 border/圆角不生效，必须用 `QFrame` + `WA_StyledBackground`。
- 坑：服务商列表固定高度按 `rows*30+2` 算会差几个像素 → 最后一行被切、冒出滚动条，改成 `rows*30 + 2*3 + 2`（QSS item padding 计进去）。

✅ 测试（28 个，净增 3 个换了语义的用例）：只列当前服务商候选、标题栏展开/切换服务商（不动 model）、先切服务商再选模型、无候选时禁用并提示。

### 0.4.0 追加（四改）：浮层高度不随候选数变化（239 测试全过，ruff 全绿）

**用户反馈**：从「单候选服务商」切到「多候选服务商」时列表还是只有一行高，反过来则是更高的高度显示一行。

**根因**（两个叠加）：
1. `rebuild_list()` 里用 `self.list.setFixedHeight(rows * 34 + 8)` 的固定常量行高 —— 与 QSS 的 `item padding` 不匹配，导致行被切或留白条。改为按行数与**实测行高**（`item(0).sizeHint().height()`，取不到才回落 `_MODEL_ROW_HEIGHT`）计算。
2. 更关键的是 `_relayout_growing_up()` 里**用了 `setFixedSize()`** —— 面板高度被钉死，后续内容变化再也撑不开。改为 `resize(_PANEL_WIDTH, height)` + 仅重算 top（`bottom - height + 1`），高度始终由布局决定。
3. 附带：`setFixedHeight()` 作用在子控件上**不会自动让父布局失效**，`layout().totalSizeHint()` 会继续返回旧值 → 重排前先对所有子控件 `updateGeometry()` + `layout().invalidate()` / `activate()`。

✅ 新增 `_refit()`：内容变化且面板可见时自动按「底边不动」重新测量、向上长高。
✅ 实测：单候选 153px ↔ 3 候选 221px ↔ 4 候选 255px，展开服务商列 +106px，**所有场景 bottom 恒定**。
✅ 测试（30 个，新增 2 个回归）：`test_list_height_follows_candidate_count`（1↔4 候选来回切，列表高度与面板底边都要对）、`test_expanding_providers_grows_upward`。

⬜️ 待实测：Windows 端 QListWidget 行高与滚动条表现。

---

## 历史：0.2.0 / §3.x 批次

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
