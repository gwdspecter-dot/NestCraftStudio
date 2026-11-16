"""Диалог «Что нового» — пользовательские заметки из RELEASE_NOTES.md (с fallback на CHANGELOG.md)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.changelog import ChangelogEntry, load_whats_new, markdown_to_html
from ui.theme import current_theme


def _body_html(body: str) -> str:
    c = current_theme()
    inner = markdown_to_html(body)
    return f"""
    <html><head><style>
      body {{
        background-color: {c.bg};
        color: {c.text};
        font-family: 'Segoe UI', 'Consolas', 'Cascadia Code', sans-serif;
        font-size: 13px;
        line-height: 1.55;
      }}
      h2, h3 {{
        color: {c.heading};
        font-weight: 600;
        margin: 14px 0 8px 0;
      }}
      h2 {{ font-size: 15px; }}
      h3 {{ font-size: 14px; color: {c.accent_soft}; }}
      p {{ margin: 6px 0; color: {c.text}; }}
      ul {{ margin: 4px 0 10px 0; padding-left: 22px; }}
      li {{ margin: 3px 0; color: {c.text}; }}
      code {{
        background-color: {c.code_bg};
        color: {c.code_fg};
        padding: 1px 5px;
        border-radius: 3px;
        font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
        font-size: 12px;
      }}
      b {{ color: {c.accent_soft}; font-weight: 600; }}
      a {{ color: {c.accent_soft}; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      i {{ color: {c.text_dim}; }}
    </style></head><body>{inner}</body></html>
    """


class WhatsNewDialog(QDialog):
    def __init__(
        self,
        parent=None,
        entries: list[ChangelogEntry] | None = None,
        tech_entries: list[ChangelogEntry] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Что нового — NestCraft Studio")
        self.resize(860, 540)
        self.setMinimumSize(560, 360)

        c = current_theme()
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {c.bg}; color: {c.text}; }}
            QLabel#titleLabel {{
                font-size: 18px; font-weight: 600; color: {c.text_title};
                padding: 2px 0 6px 0;
            }}
            QLabel#sideLabel {{
                color: {c.text_dim}; font-size: 11px; padding: 0 0 2px 2px;
            }}
            QLabel#headingLabel {{
                font-size: 15px; font-weight: 600; color: {c.accent_soft};
                padding: 0 0 4px 2px;
            }}
            QListWidget {{
                background-color: {c.bg_alt}; color: {c.text};
                border: 1px solid {c.border}; border-radius: 4px; outline: none;
                font-size: 13px;
            }}
            QListWidget::item {{ padding: 7px 12px; }}
            QListWidget::item:hover {{ background-color: {c.bg_panel}; }}
            QListWidget::item:selected {{
                background-color: {c.select_bg}; color: {c.select_fg};
            }}
            QTextBrowser {{
                background-color: {c.bg}; color: {c.text};
                border: 1px solid {c.border}; border-radius: 4px; padding: 12px 14px;
            }}
            QCheckBox#techToggle {{
                color: {c.text_dim}; font-size: 12px;
            }}
            QPushButton {{
                background-color: {c.accent}; color: #ffffff; border: none;
                border-radius: 4px; padding: 6px 18px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {c.accent_hover}; }}
            """
        )

        if entries is None:
            self._user_entries, self._tech_entries = load_whats_new()
        else:
            self._user_entries = entries
            self._tech_entries = tech_entries if tech_entries is not None else []
        self._entries: list[ChangelogEntry] = self._user_entries

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("Что нового")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(4)
        left_lbl = QLabel("Версии")
        left_lbl.setObjectName("sideLabel")
        left_l.addWidget(left_lbl)
        self.version_list = QListWidget()
        self.version_list.setMinimumWidth(170)
        left_l.addWidget(self.version_list)
        splitter.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)
        self.heading = QLabel("")
        self.heading.setObjectName("headingLabel")
        right_l.addWidget(self.heading)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        pal = self.body.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(c.bg))
        pal.setColor(QPalette.ColorRole.Text, QColor(c.text))
        self.body.setPalette(pal)
        right_l.addWidget(self.body)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 640])
        root.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        self.tech_cb = QCheckBox("Показать технический журнал")
        self.tech_cb.setObjectName("techToggle")
        self.tech_cb.setVisible(bool(self._tech_entries))
        self.tech_cb.toggled.connect(self._on_tech_toggled)
        btn_row.addWidget(self.tech_cb)
        btn_row.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self.version_list.currentRowChanged.connect(self._on_version_selected)
        self._populate()

    def _populate(self, select_version: str | None = None) -> None:
        self.version_list.blockSignals(True)
        self.version_list.clear()
        if not self._entries:
            self.version_list.blockSignals(False)
            self.heading.setText("История изменений")
            self.body.setHtml(_body_html("Файлы `RELEASE_NOTES.md` и `CHANGELOG.md` не найдены или пусты."))
            return
        target_row = 0
        for idx, e in enumerate(self._entries):
            label = e.version
            if e.date:
                label = f"{e.version}  ({e.date})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, e)
            self.version_list.addItem(item)
            if select_version and e.version == select_version:
                target_row = idx
        self.version_list.blockSignals(False)
        self.version_list.setCurrentRow(target_row)
        self._on_version_selected(target_row)

    def _on_tech_toggled(self, checked: bool) -> None:
        current_ver: str | None = None
        row = self.version_list.currentRow()
        if 0 <= row < len(self._entries):
            current_ver = self._entries[row].version
        self._entries = self._tech_entries if (checked and self._tech_entries) else self._user_entries
        self._populate(select_version=current_ver)

    def _on_version_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            return
        e = self._entries[row]
        head = f"Версия {e.version}"
        if e.date:
            head += f" — {e.date}"
        self.heading.setText(head)
        self.body.setHtml(_body_html(e.body))
