"""Main application window."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Any

from datetime import datetime

from PySide6.QtCore import QByteArray, QEvent, QPoint, Qt, QThreadPool
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.config.schema import AppConfig, HistoryEntry
from app.config.store import ConfigStore
from app.core.clipboard_image import ClipboardImageError, ClipboardImageService
from app.core.languages import SOURCE_LANGUAGES, TARGET_LANGUAGES
from app.core.ocr import install_hint
from app.core.screenshot import (
    ScreenshotCancelled,
    ScreenshotError,
    ScreenshotService,
)
from app.core.translator import TranslateResult, Translator
from app.ui.history_panel import HistoryPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.widgets import SourceEdit, apply_theme
from app.workers.tasks import FunctionWorker


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore, config: AppConfig) -> None:
        super().__init__()
        self.store = store
        self.config = config
        self.translator = Translator()
        self.screenshot = ScreenshotService()
        self.clipboard_image = ClipboardImageService()
        self.pool = QThreadPool.globalInstance()
        self._busy = False
        self._current_image: bytes | None = None
        self._shortcuts: list[QShortcut] = []

        self.setWindowTitle("AI Translator")
        self.resize(config.ui.window_width, config.ui.window_height)

        self._build_ui()
        self._reload_profiles()
        self._apply_translation_defaults()
        self._install_hotkeys()
        self._set_status("就绪")

    # ── UI construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        # Toolbar row
        top = QHBoxLayout()
        title = QLabel("AI Translator")
        title.setObjectName("titleLabel")
        top.addWidget(title)
        top.addSpacing(12)

        top.addWidget(QLabel("配置"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)

        top.addSpacing(8)
        top.addWidget(QLabel("图片模式"))
        self.mode_ocr = QRadioButton("OCR")
        self.mode_vision = QRadioButton("Vision")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_ocr)
        self.mode_group.addButton(self.mode_vision)
        top.addWidget(self.mode_ocr)
        top.addWidget(self.mode_vision)
        top.addStretch(1)

        self.btn_history = QPushButton("历史记录")
        self.btn_history.setToolTip("最近 10 条翻译记录")
        self.btn_history.clicked.connect(self._toggle_history_panel)
        top.addWidget(self.btn_history)
        root.addLayout(top)

        # Language row
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("源语言"))
        self.source_combo = QComboBox()
        for code, name in SOURCE_LANGUAGES:
            self.source_combo.addItem(name, code)
        self.source_combo.currentIndexChanged.connect(self._update_swap_enabled)
        lang_row.addWidget(self.source_combo)

        self.btn_swap = QPushButton("⇄")
        self.btn_swap.setFixedWidth(40)
        self.btn_swap.setToolTip("交换语种")
        self.btn_swap.clicked.connect(self._swap_langs)
        lang_row.addWidget(self.btn_swap)

        lang_row.addWidget(QLabel("目标语言"))
        self.target_combo = QComboBox()
        for code, name in TARGET_LANGUAGES:
            self.target_combo.addItem(name, code)
        lang_row.addWidget(self.target_combo)
        lang_row.addStretch(1)
        root.addLayout(lang_row)

        # Image preview (hidden until image is loaded)
        self.image_frame = QFrame()
        self.image_frame.setObjectName("card")
        img_layout = QHBoxLayout(self.image_frame)
        self.image_label = QLabel("图片预览")
        self.image_label.setObjectName("imagePreview")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(100)
        self.image_label.setMaximumHeight(160)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        img_layout.addWidget(self.image_label)
        self.image_frame.setVisible(False)
        root.addWidget(self.image_frame)

        # Source / result panes
        splitter = QSplitter(Qt.Orientation.Horizontal)
        src_wrap = QFrame()
        src_wrap.setObjectName("card")
        src_l = QVBoxLayout(src_wrap)
        src_l.addWidget(QLabel("原文"))
        self.source_edit = SourceEdit()
        self.source_edit.setObjectName("sourceEdit")
        self.source_edit.setPlaceholderText(
            "在此输入或粘贴文本…\n"
            "Ctrl+V 也可粘贴图片；支持拖入图片文件。\n"
            "或用下方「截图翻译 / 粘贴图片」。"
        )
        self.source_edit.set_image_probe(self._probe_clipboard_image)
        self.source_edit.image_pasted.connect(self._on_image_bytes)
        src_l.addWidget(self.source_edit)
        splitter.addWidget(src_wrap)

        dst_wrap = QFrame()
        dst_wrap.setObjectName("card")
        dst_l = QVBoxLayout(dst_wrap)
        dst_l.addWidget(QLabel("译文"))
        self.result_edit = QPlainTextEdit()
        self.result_edit.setObjectName("resultEdit")
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("翻译结果将显示在这里。")
        dst_l.addWidget(self.result_edit)
        splitter.addWidget(dst_wrap)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Bottom actions: left 4 under 原文, right 2 under 译文
        # [翻译] [截图翻译] [粘贴图片] [清空]  ……  [复制结果] [设置]
        actions = QHBoxLayout()
        self.btn_translate = QPushButton("翻译")
        self.btn_translate.setObjectName("primaryButton")
        self.btn_translate.clicked.connect(self._on_translate)
        self.btn_screenshot = QPushButton("截图翻译")
        self.btn_screenshot.clicked.connect(self._on_screenshot)
        self.btn_paste_img = QPushButton("粘贴图片")
        self.btn_paste_img.clicked.connect(self._on_paste_image)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_copy = QPushButton("复制结果")
        self.btn_copy.clicked.connect(self._on_copy_result)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self._open_settings)

        actions.addWidget(self.btn_translate)
        actions.addWidget(self.btn_screenshot)
        actions.addWidget(self.btn_paste_img)
        actions.addWidget(self.btn_clear)
        actions.addStretch(1)
        actions.addWidget(self.btn_copy)
        actions.addWidget(self.btn_settings)
        root.addLayout(actions)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("就绪")
        status.addWidget(self.status_label, 1)

        # Floating history panel (child of central widget — not a system window)
        self.history_panel = HistoryPanel(central)
        self.history_panel.entry_selected.connect(self._on_history_selected)
        self.history_panel.clear_requested.connect(self._clear_history)
        QApplication.instance().installEventFilter(self)  # type: ignore[union-attr]

        quit_act = QAction("退出", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        self.addAction(quit_act)

    # ── Config helpers ────────────────────────────────────────────
    def _reload_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        active_idx = 0
        for i, p in enumerate(self.config.profiles):
            self.profile_combo.addItem(p.name, p.id)
            if p.id == self.config.active_profile_id:
                active_idx = i
        self.profile_combo.setCurrentIndex(active_idx)
        self.profile_combo.blockSignals(False)

    def _apply_translation_defaults(self) -> None:
        t = self.config.translation
        s_idx = self.source_combo.findData(t.source_lang)
        self.source_combo.setCurrentIndex(max(0, s_idx))
        t_idx = self.target_combo.findData(t.target_lang)
        self.target_combo.setCurrentIndex(max(0, t_idx))
        if t.image_mode == "vision":
            self.mode_vision.setChecked(True)
        else:
            self.mode_ocr.setChecked(True)
        self._update_swap_enabled()

    def _persist(self) -> None:
        # Sync live UI choices into config
        self.config.active_profile_id = self.profile_combo.currentData() or self.config.active_profile_id
        self.config.translation.source_lang = self.source_combo.currentData() or "auto"
        self.config.translation.target_lang = self.target_combo.currentData() or "zh"
        self.config.translation.image_mode = "vision" if self.mode_vision.isChecked() else "ocr"
        self.config.ui.window_width = self.width()
        self.config.ui.window_height = self.height()
        self.store.save(self.config)

    def _on_profile_changed(self, _index: int) -> None:
        pid = self.profile_combo.currentData()
        if pid:
            self.config.active_profile_id = pid
            self.store.save(self.config)
            profile = self.config.get_active_profile()
            self._set_status(f"已切换配置：{profile.name} · {profile.model}")

    def _open_settings(self) -> None:
        self._persist()
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return
        self.config = dlg.result_config()
        self.store.save(self.config)
        apply_theme(QApplication.instance(), self.config.ui.theme)  # type: ignore[arg-type]
        self._reload_profiles()
        self._apply_translation_defaults()
        self._install_hotkeys()
        self._set_status("设置已保存")

    # ── Hotkeys ───────────────────────────────────────────────────
    def _install_hotkeys(self) -> None:
        for sc in self._shortcuts:
            sc.setParent(None)
        self._shortcuts.clear()

        hk = self.config.ui.hotkeys
        mapping = [
            (hk.translate, self._on_translate),
            (hk.screenshot, self._on_screenshot),
            (hk.paste_image, self._on_paste_image),
            (hk.swap_langs, self._swap_langs),
            (hk.copy_result, self._on_copy_result),
        ]
        for seq, slot in mapping:
            if not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    # ── Language swap ─────────────────────────────────────────────
    def _update_swap_enabled(self) -> None:
        source = self.source_combo.currentData()
        self.btn_swap.setEnabled(source != "auto")

    def _swap_langs(self) -> None:
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()
        if source == "auto" or not source or not target:
            self._set_status("源语言为自动检测时无法交换")
            return
        s_idx = self.source_combo.findData(target)
        t_idx = self.target_combo.findData(source)
        if s_idx < 0 or t_idx < 0:
            self._set_status("无法交换：目标语言不在源语言列表中")
            return
        self.source_combo.setCurrentIndex(s_idx)
        self.target_combo.setCurrentIndex(t_idx)
        # Also swap pane texts when both have content
        src_text = self.source_edit.toPlainText()
        dst_text = self.result_edit.toPlainText()
        if src_text.strip() and dst_text.strip():
            self.source_edit.setPlainText(dst_text)
            self.result_edit.setPlainText(src_text)

    # ── Busy state ────────────────────────────────────────────────
    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = busy
        for w in (
            self.btn_translate,
            self.btn_screenshot,
            self.btn_paste_img,
            self.btn_settings,
            self.profile_combo,
        ):
            w.setEnabled(not busy)
        if message:
            self._set_status(message)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # ── Translate (text) ──────────────────────────────────────────
    def _on_translate(self) -> None:
        if self._busy:
            return

        if self._current_image is not None and not self.source_edit.toPlainText().strip():
            self._translate_image(self._current_image)
            return

        text = self.source_edit.toPlainText().strip()
        if not text:
            self._set_status("请输入文本，或使用截图 / 粘贴图片")
            return

        profile = self.config.get_active_profile()
        source = self.source_combo.currentData() or "auto"
        target = self.target_combo.currentData() or "zh"
        extra = self.config.translation.supplementary_prompt

        self._set_busy(True, f"翻译中… · {profile.model}")
        started = time.perf_counter()

        def work() -> dict[str, Any]:
            result = self.translator.translate_text(
                text,
                source_lang=source,
                target_lang=target,
                profile=profile,
                supplementary_prompt=extra,
            )
            return {"result": result, "elapsed": time.perf_counter() - started}

        worker = FunctionWorker(work)
        worker.signals.finished.connect(self._on_translate_ok)
        worker.signals.error.connect(self._on_translate_err)
        self.pool.start(worker)

    def _on_translate_ok(self, payload: object) -> None:
        self._set_busy(False)
        data = payload if isinstance(payload, dict) else {}
        result: TranslateResult = data.get("result")  # type: ignore[assignment]
        elapsed = float(data.get("elapsed") or 0)
        if result is None:
            self._set_status("翻译完成（无结果）")
            return
        self.result_edit.setPlainText(result.text)
        if result.ocr_text and not self.source_edit.toPlainText().strip():
            self.source_edit.setPlainText(result.ocr_text)

        source_text = self.source_edit.toPlainText().strip()
        if not source_text:
            if result.ocr_text:
                source_text = result.ocr_text
            elif result.mode in ("ocr", "vision"):
                source_text = f"[图片 · {result.mode}]"
        self._record_history(
            source_text=source_text,
            result_text=result.text,
            mode=result.mode,
            model=result.model,
        )
        self._set_status(
            f"完成 · mode={result.mode} · model={result.model} · {elapsed:.2f}s"
        )

    # ── History ──────────────────────────────────────────────────
    def _record_history(
        self,
        *,
        source_text: str,
        result_text: str,
        mode: str,
        model: str = "",
    ) -> None:
        if not (source_text or "").strip() and not (result_text or "").strip():
            return
        self.config.push_history(
            source_lang=self.source_combo.currentData() or "auto",
            target_lang=self.target_combo.currentData() or "zh",
            mode=mode or "text",
            source_text=source_text,
            result_text=result_text,
            model=model,
        )
        try:
            self.store.save(self.config)
        except OSError:
            pass
        if self.history_panel.isVisible():
            self.history_panel.set_entries(self.config.history)

    def _toggle_history_panel(self) -> None:
        if self.history_panel.isVisible():
            self.history_panel.hide_panel()
            return
        self.history_panel.set_entries(self.config.history)
        # Anchor to bottom-right of the history button
        br = self.btn_history.mapToGlobal(
            QPoint(self.btn_history.width(), self.btn_history.height())
        )
        self.history_panel.show_at(br)

    def _on_history_selected(self, entry_id: str) -> None:
        entry = self.config.get_history(entry_id)
        if entry is None:
            self._set_status("历史记录不存在")
            return
        self._restore_history(entry)

    def _restore_history(self, entry: HistoryEntry) -> None:
        s_idx = self.source_combo.findData(entry.source_lang)
        if s_idx >= 0:
            self.source_combo.setCurrentIndex(s_idx)
        t_idx = self.target_combo.findData(entry.target_lang)
        if t_idx >= 0:
            self.target_combo.setCurrentIndex(t_idx)

        self.source_edit.setPlainText(entry.source_text or "")
        self.result_edit.setPlainText(entry.result_text or "")
        self._current_image = None
        self.image_label.clear()
        self.image_label.setText("图片预览")
        self.image_frame.setVisible(False)

        when = ""
        if entry.ts:
            try:
                when = datetime.fromtimestamp(entry.ts).strftime("%Y-%m-%d %H:%M")
            except (OverflowError, OSError, ValueError):
                when = ""
        suffix = f" · {when}" if when else ""
        self._set_status(f"已载入历史记录{suffix}")

    def _clear_history(self) -> None:
        if not self.config.history:
            return
        if (
            QMessageBox.question(self, "清空历史", "清除全部翻译历史？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.config.clear_history()
        try:
            self.store.save(self.config)
        except OSError:
            pass
        self.history_panel.set_entries([])
        self._set_status("历史已清空")

    def eventFilter(self, obj, event):  # noqa: N802
        # Click outside the floating panel → close it
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self.history_panel.isVisible()
        ):
            pos = event.globalPosition().toPoint()  # type: ignore[attr-defined]
            panel_rect = self.history_panel.rect()
            panel_global_topleft = self.history_panel.mapToGlobal(QPoint(0, 0))
            panel_rect.moveTopLeft(panel_global_topleft)
            btn_rect = self.btn_history.rect()
            btn_rect.moveTopLeft(self.btn_history.mapToGlobal(QPoint(0, 0)))
            if not panel_rect.contains(pos) and not btn_rect.contains(pos):
                self.history_panel.hide_panel()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.history_panel.isVisible():
            br = self.btn_history.mapToGlobal(
                QPoint(self.btn_history.width(), self.btn_history.height())
            )
            self.history_panel.show_at(br)

    def _on_translate_err(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(f"失败：{message}")
        QMessageBox.warning(self, "翻译失败", message)

    # ── Image translate ───────────────────────────────────────────
    def _image_mode(self) -> str:
        return "vision" if self.mode_vision.isChecked() else "ocr"

    def _show_image_preview(self, png: bytes) -> None:
        self._current_image = png
        image = QImage.fromData(QByteArray(png))
        if image.isNull():
            self.image_label.setText("无法预览图片")
        else:
            pix = QPixmap.fromImage(image)
            scaled = pix.scaled(
                self.image_label.width() or 600,
                150,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
        self.image_frame.setVisible(True)

    def _translate_image(self, png: bytes) -> None:
        if self._busy:
            return
        profile = self.config.get_active_profile()
        source = self.source_combo.currentData() or "auto"
        target = self.target_combo.currentData() or "zh"
        extra = self.config.translation.supplementary_prompt
        mode = self._image_mode()
        ocr_langs = self.config.translation.ocr_langs

        if mode == "ocr" and not self.translator.ocr.available():
            QMessageBox.warning(
                self,
                "缺少 tesseract",
                f"OCR 模式需要 tesseract。\n{install_hint()}\n或切换到 Vision 模式。",
            )
            return

        label = profile.vision_model if mode == "vision" else profile.model
        self._set_busy(True, f"图片翻译中（{mode}）… · {label}")
        started = time.perf_counter()

        def work() -> dict[str, Any]:
            result = self.translator.translate_image(
                png,
                mode=mode,  # type: ignore[arg-type]
                source_lang=source,
                target_lang=target,
                profile=profile,
                supplementary_prompt=extra,
                ocr_langs=ocr_langs,
            )
            return {"result": result, "elapsed": time.perf_counter() - started}

        worker = FunctionWorker(work)
        worker.signals.finished.connect(self._on_translate_ok)
        worker.signals.error.connect(self._on_translate_err)
        self.pool.start(worker)

    def _on_screenshot(self) -> None:
        if self._busy:
            return
        if not self.screenshot.available():
            if self.screenshot.requires_gui_thread:
                QMessageBox.warning(
                    self,
                    "截图不可用",
                    "截图功能需要正在运行的 Qt 界面。",
                )
            else:
                QMessageBox.warning(
                    self,
                    "缺少截图工具",
                    "需要 grim 与 slurp（Wayland）。\n"
                    "CachyOS/Arch：sudo pacman -S grim slurp",
                )
            return

        if self.screenshot.requires_gui_thread:
            self._screenshot_gui_thread()
        else:
            self._screenshot_worker()

    def _screenshot_worker(self) -> None:
        self._set_status("框选区域中…（Esc 取消）")
        QApplication.processEvents()

        # Capture on a worker so UI stays responsive during slurp wait
        def work() -> bytes:
            return self.screenshot.capture_region()

        self._set_busy(True, "框选区域中…（Esc 取消）")
        worker = FunctionWorker(work)
        worker.signals.finished.connect(self._on_screenshot_ok)
        worker.signals.error.connect(self._on_screenshot_err)
        self.pool.start(worker)

    def _screenshot_gui_thread(self) -> None:
        # Modal Qt overlay — must run on the GUI thread.
        self._set_status("框选区域中…（Esc 取消）")
        QApplication.processEvents()
        try:
            # Hide main window so it is not in the capture
            was_visible = self.isVisible()
            if was_visible:
                self.hide()
                QApplication.processEvents()
            try:
                png = self.screenshot.capture_region()
            finally:
                if was_visible:
                    self.show()
                    self.raise_()
                    self.activateWindow()
        except ScreenshotCancelled:
            self._set_status("已取消截图")
            return
        except ScreenshotError as exc:
            self._set_status(f"截图失败：{exc}")
            QMessageBox.warning(self, "截图失败", str(exc))
            return

        self._show_image_preview(png)
        self._translate_image(png)

    def _on_screenshot_ok(self, png: object) -> None:
        self._set_busy(False)
        if not isinstance(png, (bytes, bytearray)):
            self._set_status("截图失败：无效数据")
            return
        data = bytes(png)
        self._show_image_preview(data)
        # OCR mode: put recognized text into source after translate; clear text for image path
        if not self.source_edit.toPlainText().strip():
            pass
        self._translate_image(data)

    def _on_screenshot_err(self, message: str) -> None:
        self._set_busy(False)
        if "cancelled" in message.lower() or "取消" in message:
            self._set_status("已取消截图")
            return
        self._set_status(f"截图失败：{message}")
        # ScreenshotCancelled comes through as string
        if "Screenshot cancelled" in message:
            return
        QMessageBox.warning(self, "截图失败", message)

    def _probe_clipboard_image(self) -> bytes | None:
        """供原文框 Ctrl+V 探测；失败返回 None，不弹窗。"""
        # Prefer wl-paste on Wayland; fall back to Qt mime.
        if self.clipboard_image.available():
            try:
                return self.clipboard_image.read_png()
            except ClipboardImageError:
                pass
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return None
        md = clipboard.mimeData()
        if md is None:
            return None
        if md.hasImage():
            img = md.imageData()
            if isinstance(img, QImage) and not img.isNull():
                from app.ui.widgets import qimage_to_png_bytes

                return qimage_to_png_bytes(img)
        for fmt in ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"):
            if md.hasFormat(fmt):
                raw = bytes(md.data(fmt))
                if raw:
                    qimg = QImage.fromData(raw)
                    if not qimg.isNull():
                        from app.ui.widgets import qimage_to_png_bytes

                        return qimage_to_png_bytes(qimg) or raw
        return None

    def _on_image_bytes(self, png: bytes) -> None:
        """统一入口：按钮 / 快捷键 / 原文框粘贴 / 拖放。"""
        if self._busy:
            return
        if not png:
            return
        self._show_image_preview(png)
        self._translate_image(png)

    def _on_paste_image(self) -> None:
        if self._busy:
            return
        png = self._probe_clipboard_image()
        if png:
            self._on_image_bytes(png)
            return
        # 明确失败时再提示
        if not self.clipboard_image.available():
            hint = ""
            if sys.platform.startswith("linux"):
                hint = "\n若在 Wayland 下，建议安装 wl-clipboard：\nsudo pacman -S wl-clipboard"
            QMessageBox.warning(
                self,
                "粘贴图片",
                "剪贴板里没有图片。" + hint,
            )
            return
        try:
            png = self.clipboard_image.read_png()
        except ClipboardImageError as exc:
            self._set_status(f"粘贴图片失败：{exc}")
            QMessageBox.information(self, "粘贴图片", str(exc))
            return
        self._on_image_bytes(png)

    # ── Clear / copy ──────────────────────────────────────────────
    def _on_clear(self) -> None:
        self.source_edit.clear()
        self.result_edit.clear()
        self._current_image = None
        self.image_label.clear()
        self.image_label.setText("图片预览")
        self.image_frame.setVisible(False)
        self._set_status("已清空")

    def _on_copy_result(self) -> None:
        text = self.result_edit.toPlainText()
        if not text.strip():
            self._set_status("没有可复制的译文")
            return
        # Prefer wl-copy on Wayland for reliability; fall back to Qt clipboard
        if shutil.which("wl-copy"):
            try:
                subprocess.run(
                    ["wl-copy"],
                    input=text.encode("utf-8"),
                    check=False,
                    timeout=5,
                )
                self._set_status("译文已复制到剪贴板")
                return
            except (OSError, subprocess.TimeoutExpired):
                pass
        QApplication.clipboard().setText(text)
        self._set_status("译文已复制到剪贴板")

    # ── Lifecycle ─────────────────────────────────────────────────
    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist()
        super().closeEvent(event)
