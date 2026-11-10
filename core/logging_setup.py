"""Инициализация логирования NestCraft Studio (план §2.1)."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger("nestcraft")
_CONFIGURED = False
_LOG_FILE: Optional[Path] = None


def user_data_dir() -> Path:
    """Каталог данных пользователя (логи, будущая БД каталога).

    Путь всегда содержит ``NestCraft`` (org/app name). Если QApplication
    создан без setOrganizationName/setApplicationName (типично в pytest),
    QStandardPaths даёт ``…/python`` — такой путь отбрасываем в пользу
    явного fallback.
    """
    qt_loc = ""
    try:
        from PyQt6.QtCore import QStandardPaths, QCoreApplication
        # AppDataLocation учитывает OrganizationName / ApplicationName
        app = QCoreApplication.instance()
        if app is not None:
            # Подстраховка: если GUI ещё не выставил имена — ставим сами
            if not app.organizationName():
                app.setOrganizationName("NestCraft")
            if not app.applicationName():
                app.setApplicationName("NestCraft Studio")
            qt_loc = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
    except Exception:
        # Игнорируем отсутствие PyQt6 в консольном/тестовом окружении до старта GUI
        qt_loc = ""
    if qt_loc and "NestCraft" in qt_loc:
        return Path(qt_loc)
    # Fallback без Qt / до QApplication / при безымянном QApp
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "NestCraft"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "NestCraft"
    else:
        base = Path.home() / ".local" / "share" / "NestCraft"
    return base


def log_file_path() -> Path:
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE
    return user_data_dir() / "logs" / "nestcraft.log"


def setup_logging(level: int = logging.INFO) -> Path:
    """RotatingFileHandler + stderr. Идемпотентно. Возвращает путь к лог-файлу."""
    global _CONFIGURED, _LOG_FILE
    if _CONFIGURED:
        return log_file_path()

    log_dir = user_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "nestcraft.log"
    _LOG_FILE = path

    root = logging.getLogger("nestcraft")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)

    _CONFIGURED = True
    root.info("Logging started → %s", path)
    return path


def get_logger(name: str = "nestcraft") -> logging.Logger:
    """Именованный логгер под деревом ``nestcraft.*``.

    ``propagate=True`` обязателен: записи доходят до root ``nestcraft``
    (file handler) и до ``caplog`` в тестах (ревизия 4 §1.7).
    """
    if not name.startswith("nestcraft"):
        name = f"nestcraft.{name}"
    log = logging.getLogger(name)
    log.propagate = True
    return log


def install_excepthook(*, show_dialog: bool = True) -> None:
    """Пишет необработанные исключения в лог; опционально показывает диалог."""
    prev = sys.excepthook
    dialog_active = False

    def _hook(exc_type, exc, tb):
        nonlocal dialog_active
        log = get_logger("crash")
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", text)
        log_path = log_file_path()
        if show_dialog and not dialog_active:
            try:
                from PyQt6.QtCore import QTimer
                from PyQt6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance()
                if app is not None:
                    dialog_active = True
                    msg = (
                        "Произошла непредвиденная ошибка.\n\n"
                        f"Подробности записаны в лог:\n{log_path}\n\n"
                        f"{exc_type.__name__}: {exc}"
                    )

                    def _show_crash_box() -> None:
                        nonlocal dialog_active
                        try:
                            QMessageBox.critical(
                                None,
                                "NestCraft Studio — ошибка",
                                msg,
                            )
                        except Exception:
                            log.exception("Failed to display crash QMessageBox")
                        finally:
                            dialog_active = False

                    QTimer.singleShot(0, _show_crash_box)
            except Exception:
                dialog_active = False
                log.exception("Failed to schedule crash QMessageBox")
        # Не глотаем полностью — стандартный хук тоже
        try:
            prev(exc_type, exc, tb)
        except Exception:
            log.exception("Previous sys.excepthook failed")

    sys.excepthook = _hook

