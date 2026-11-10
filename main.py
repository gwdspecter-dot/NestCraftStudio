import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QSurfaceFormat, QIcon
from PyQt6.QtCore import QTimer

from core.version import APP_VERSION, MIN_BUILD123D_VERSION
from ui.splash import SplashScreen, run_with_splash

_ROOT = Path(__file__).resolve().parent
_LOGO = _ROOT / "ui" / "icons" / "logo.svg"


def format_build123d_error(exc: BaseException | None = None) -> str:
    """Формирует понятное сообщение при отсутствии или устаревшей версии build123d (п. 1.5)."""
    msg = (
        f"Установите build123d версии >= {MIN_BUILD123D_VERSION}:\n"
        f"pip install \"build123d>={MIN_BUILD123D_VERSION}\""
    )
    if exc is not None:
        msg = f"{msg}\n\nДетали ошибки: {exc}"
    return msg


def main():
    # OpenGL Core Profile 3.3+ до создания QApplication/виджетов
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("NestCraft Studio")
    app.setOrganizationName("NestCraft")
    app.setApplicationVersion(APP_VERSION)
    # Тема: VS Code-like, светлая/тёмная по системе
    from ui.theme import apply_theme, install_system_theme_watcher
    apply_theme(app)
    install_system_theme_watcher(app)
    if _LOGO.is_file():
        app.setWindowIcon(QIcon(str(_LOGO)))

    # Логирование после имён приложения (AppDataLocation) — план §2.1
    from core.logging_setup import setup_logging, install_excepthook, get_logger
    log_path = setup_logging()
    install_excepthook(show_dialog=True)
    log = get_logger("main")
    log.info("NestCraft Studio %s starting", APP_VERSION)

    def _boot(splash: SplashScreen):
        splash.show_message("Инициализация OpenGL…", 12)
        splash.show_message("Загрузка ядра CAD…", 22)

        try:
            from core.cad_kernel import CADKernel
        except ImportError as exc:
            err_text = format_build123d_error(exc)
            log.critical("Missing or incompatible build123d: %s", exc)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None,
                "NestCraft Studio — не найден пакет build123d",
                err_text,
            )
            raise SystemExit(1) from exc

        # Тяжёлые импорты после проверки CAD-ядра и показа splash
        from ui.main_window import MainWindow

        splash.show_message("Подготовка каталога материалов…", 38)
        try:
            from core.catalog import CatalogService
            from core.scene_controller import SceneController
            CatalogService.instance()  # прогрев SQLite + seed
            SceneController.instance()
        except Exception:
            get_logger("catalog").exception("CatalogService init failed")

        splash.show_message("Прогрев ядра B-Rep (build123d)…", 55)
        try:
            CADKernel.warmup()
        except Exception:
            get_logger("cad_kernel").exception("CADKernel warmup failed")

        splash.show_message("Создание главного окна…", 70)

        window = MainWindow()

        splash.show_message("Подключение панелей и вьюпорта…", 88)
        window.show()
        splash.show_message("Готово", 100)
        return window

    window = run_with_splash(_boot, version=APP_VERSION)

    # Небольшая задержка, чтобы splash успел показать 100%
    QTimer.singleShot(200, lambda: None)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
