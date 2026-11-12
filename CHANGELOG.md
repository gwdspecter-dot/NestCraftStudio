# Changelog

Все значимые изменения проекта NestCraft Studio фиксируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [Semantic Versioning](https://semver.org/lang/ru/).

## [0.0.21] - 2026-11-12

### Added
- **Персистентные формулы (drivers)** (`core/drivers.py`, `core/formula.py`):
  выражение вроде `cw - 2*ct` или `w - 32` сохраняется на панели в `drivers[attr]` и
  пересчитывается при смене размеров панели или родительского корпуса.
  Переменные корпуса: `cw/ch/cd/ct` (и `cabinet_w` …). Относительные `+=`/`-=` не сохраняются.
- **Формат проекта 0.0.10**: поле `drivers` у панелей, миграция `0.0.9 → 0.0.10`.
- **Свойства / Undo** (`ui/panels/properties_panel.py`, `core/undo.py`): ввод формулы в таблице
  свойств записывает driver; голое число снимает; `EditPropertyCommand` откатывает driver;
  после изменения габаритов корпуса вызывается `apply_block_drivers`.
- Тесты: `tests/test_drivers.py`.

### Changed
- `APP_VERSION` → **0.0.21**; `FORMAT_VERSION` → **0.0.10**.

## [0.0.20] - 2026-11-12

### Added
- **Ассоциативные отверстия (`AssocRef`, kind=`face_hole`)** (`core/assoc.py`):
  отверстие на панели-target считается от грани панели-source (`X+`…`Z-`) + смещения `u`/`v`/`inset`,
  диаметр и глубина. При сдвиге/resize source или rebuild блока позиция пересчитывается (`apply_assoc_refs`).
- **Хранение на блоке** (`models/panel.py`): `block.assoc_refs`, `panel.assoc_hole_map`; отверстия
  помечаются тегом `a:<uid>` (7-е поле), ручные и стыковые отверстия не затрагиваются.
- **Формат проекта 0.0.9** (`core/project_io.py`, `core/version.py`):
  сериализация `assoc_refs` / `assoc_hole_map`, миграция `0.0.8 → 0.0.9`.
- **Совместимость со стыками** (`core/joint.py`): `apply_joints` сохраняет assoc-отверстия и
  в конце вызывает `apply_assoc_refs`.
- **Undo/Redo** (`core/undo.py`): `AddAssocRefCommand`, `EditAssocRefCommand`, `DeleteAssocRefCommand`;
  `MovePanelCommand` / `ResizePanelCommand` пересчитывают assoc при отсутствии joints.
- **Диалог создания и правки** (`ui/assoc_dialog.py`): target/source, грань, u/v, inset, Ø, глубина, ось;
  live-превью точки в 3D; режим правки по существующей ссылке.
- **Док «Ассоциации»** (`ui/panels/assoc_panel.py`): список ссылок, добавить / правка / удалить,
  быстрые поля параметров с merge в undo-стеке.
- **Интеграция в главное окно** (`ui/main_window.py`): меню «Инструменты → Ассоциативное отверстие…»
  (`Ctrl+Shift+H`), док справа под «Стыки», выделение target/source и превью при выборе в списке.
- **Превью в viewport** (`ui/viewport.py`): синий крест в мировой точке ассоциации
  (`set_assoc_preview_point` / `_draw_assoc_preview`).
- Тесты: `tests/test_assoc_refs.py`, `tests/test_assoc_undo.py` (smoke, миграция, undo/redo, сдвиг source).

### Changed
- `APP_VERSION` → **0.0.20**; `FORMAT_VERSION` остаётся **0.0.9** (введён в этой линии для assoc).

## [0.0.19] - 2026-11-08

### Added
- **Конструктор параметрической фурнитуры** (`ui/fastener_constructor_dialog.py`, `core/fastener_constructor.py`):
  при «Крепёж по стыку» открывается окно с вкладками Параметрическая / Пользовательская,
  левой панелью типов (иконки SVG), схемами размеров, таблицей параметров (D1/D2/H/H1)
  и 3D-предпросмотром конфирмата. Реализован тип «Конфирмат»; остальные кнопки — заглушки.
  Кнопки «Добавить / Удалить / Создать копию» управляют строками таблицы.
- **Персистентность строк конструктора крепежа** (`core/fastener_constructor.py`):
  пользовательские строки и выбранный вариант сохраняются между вызовами диалога
  в `fastener_constructor_rows.json` (в каталоге данных пользователя) и в памяти сессии.
- **Сквозная передача параметров `D1` / `D2` / `H` / `H1` в сверление и `JointRecord`** (`core/joint.py`, `ui/viewport.py`):
  выбранные в конструкторе диаметр в пласть (`D1`), диаметр в торец (`D2`) и глубина в торец (`H` / `H1`)
  применяются в `make_joint_holes` / `_hole_dims_for_fastener` и сохраняются в `JointRecord.params`
  при сериализации и пересчёте `apply_joints`.
- Иконки типов фурнитуры: `ui/icons/fasteners/*.svg` (петля, конфирмат, минификс, шкант…).
- **Копирование / вставка (Ctrl+C / Ctrl+V)** с точкой привязки:
  выделение → Ctrl+C → клик якоря → Ctrl+V → превью → клик размещения.
  Клон блоков и панелей с новыми `uid`, перепись `JointRecord`, Undo (`PasteBlocksCommand`).
  После вставки обновляется «Структура модели» (`scene_structure_changed`).
- **Пункты «Копировать (Ctrl+C)» и «Вставить (Ctrl+V)» в меню «Правка»** (`ui/main_window.py`):
  глобальные горячие клавиши окна с корректным пробросом текстового копирования/вставки, если фокус в поле ввода.
- **OBB-каркас повёрнутых панелей в предпросмотре вставки** (`core/clipboard.py`, `ui/viewport.py`):
  `panel_dict_preview_corners` и `_draw_oriented_box_wireframe` корректно рисуют фантом повёрнутых (`rx/ry/rz`) деталей.
- **Умная 3D-линейка / Контекстные измерения в 3D** (`core/dimension.py`, `ui/viewport.py`):
  единый инструмент измерения (`M`) автоматически распознаёт тип геометрии под курсором без переключения режимов:
  две параллельные грани панелей → чистое перпендикулярное расстояние **«В свету»** (или толщина детали);
  две непараллельные грани → **угол между гранями**;
  наведение на отверстие → паспорт `Ø × глубина` и отступы до кромок;
  два отверстия → **межцентровый шаг** с автоопределением кратности **«Системе 32»** (`N×32`);
  отверстие + грань → точный перпендикулярный отступ от центра отверстия до плоскости грани;
  ребро → длина ребра `L`.
- **Пакет 1 улучшений 3D-движка — «Качество картинки и читаемость 3D»** (`core/glmath.py`, `ui/viewport.py`):
  двухточечный асимметричный студийный свет (`Key + Fill + Ambient`), привязанный к камере (`compute_camera_studio_lights`),
  гарантирует, что любые три взаимно перпендикулярные грани детали всегда имеют разный тон;
  стабилизация плоских граней через аналитическую производную `cross(dFdx(vPos), dFdy(vPos))` в `_SOLID_FS`
  устраняет «подушкообразное» размытие на острых 90° кромках при сохранении гладких цилиндров отверстий;
  адаптивные плоскости отсечения `z_near` / `z_far` (`compute_adaptive_clip_planes`, `_scene_bounding_radius`)
  повышают точность буфера глубины в 10–15 раз при макро-осмотре крепежа и исключают Z-fighting контуров (`glPolygonOffset`).
- **Пакет 3 улучшений 3D-движка — «Скорость 3D-пикинга и бесшовный ребилд»** (`models/panel.py`, `core/geometry_service.py`, `ui/viewport.py`):
  кэширование мировых углов и точек привязки панели (`pose_key`, `snap_cache_token`, `_collect_panel_snap_points`)
  с автоматической инвалидацией при `rebuild_geometry()`;
  быстрое экранное отсечение по 8 углам бокса (`_panel_within_screen_radius` / Screen-Space BBox Cull) перед проверкой
  отверстий, рёбер и пересечения луча с гранями в режимах Рулетки (`M`), Перемещения (`G`) и Вставки (`Ctrl+V`);
  удержание предыдущего меша и GPU-буфера (`VAO/VBO/EBO`) детали при пересборке отверстий/пазов на той же позе
  без мигания детали в сплошной AABB-параллелепипед.
- **Пакет 2 улучшений 3D-движка — «Сечение 3D-вида (`GL_CLIP_DISTANCE0`) + Режим Призраков окружения (`Isolate / Ghost Others`)»** (`core/glmath.py`, `ui/viewport.py`, `ui/main_window.py`):
  аппаратное 3D-сечение сцены на уровне вершинного шейдера (`GL_CLIP_DISTANCE0`, `uClipPlane`) с выбором оси (`X / Y / Z`),
  реверсом направления (`⇄`), ползунком глубины (`0..100%` габарита изделия или `Alt + Колесо мыши`), янтарной рамкой секущей плоскости
  и подсветкой внутренних стенок распила (`!gl_FrontFacing`);
  фильтрация точек привязки и 3D-луча выбора (`point_passes_clip_plane`) по активной плоскости сечения — отсечённые фасад или боковина
  пропускают клик и рулетку прямо к внутренним полкам и каналам сверления;
  режим **«Призраки окружения» (`I`)**: двухпроходная отрисовка, при которой невыделенные детали становятся полупрозрачными (`alpha=0.18`,
  `glDepthMask(GL_FALSE)`) и пропускают луч выбора сквозь внешние стенки корпуса.
- **Умные поля ввода с формулами + «Тянуть грань в 3D» (Direct Face Push-Pull)** (`core/formula.py`, `ui/panels/properties_panel.py`, `ui/dialogs.py`, `ui/main_window.py`, `ui/viewport.py`):
  безопасный AST-вычислитель выражений (`eval_math_expression`, `SmartDoubleSpinBox`) во всех числовых полях инспектора свойств,
  верхней панели координат `X / Y / Z` и диалогов создания панели и сверления: поддержка формул (`600 - 32`, `720 / 3`, `(800 - 3*16)/2`),
  относительных приращений (`+= 50`, `-= 32`, `*= 2`, `/= 2`) и переменных текущей детали (`w`, `h`, `d`, `t`, `x`, `y`, `z`, `cur`);
  в режиме масштабирования (`S`) на рабочих торцах детали отображаются круглые 3D-хэндлы **«Тянуть грань»** (`+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z`)
  с подсветкой контура грани, 3D-стрелкой нормали и магнитным прилипанием (`Snap`) к боковинам/полкам соседних деталей при неподвижной противоположной грани.
- **Живая подсветка коллизий в 3D + Зеркальная копия / Линейный массив деталей** (`core/array_mirror.py`, `core/glmath.py`, `core/undo.py`, `ui/dialogs.py`, `ui/main_window.py`, `ui/viewport.py`):
  быстрый детектор пересечений в реальном времени (`find_live_panel_collisions`, `compute_aabb_intersection_box`, `Alt+C`) с кэшированием по `pose_key()`
  мгновенно подсвечивает врезающиеся друг в друга панели алым оттенком, рисует 3D-каркас объёма врезания с диагоналями и выводит бейдж `⚡ Врезание ... мм` прямо во время перетаскивания (`G`), растяжения грани (`S`) или правки координат;
  **Зеркальная копия (`Ctrl+M`, `MirrorPanelDialog`)** отражает деталь по оси `X / Y / Z` относительно центра корпуса, собственного торца или произвольной координаты с автоматическим зеркалированием кромок (`left ↔ right`, `top ↔ bottom`), пазов и отверстий сверловки;
  **Линейный массив (`Ctrl+Shift+A`, `LinearArrayDialog`, `AddMultiplePanelsCommand`)** размножает полки и перегородки вдоль оси `X / Y / Z` в 3 режимах: фиксированный шаг от торца до торца, чистый просвет «в свету» между деталями или автоматическое деление внутреннего проёма шкафа на `N+1` равных ниш (с поддержкой формул в `SmartDoubleSpinBox` и единым шагом `Undo/Redo`).
- **Системная тема UI** (`ui/theme.py`): светлая и тёмная в духе VS Code,
  переключение по схеме ОС (`colorSchemeChanged`), палитра + stylesheet.
- **Справка → Что нового…**: список версий слева, текст изменений справа
  из `CHANGELOG.md` (`core/changelog.py`, `ui/whats_new_dialog.py`).
- Иконки инструментов левой панели (крепёж, дублировать, переместить, рулетка…);
  подписи убраны, остались tooltip.
- Детальная иконка **«Крепёж по стыку»** (`ui/icons/tool_fastener.svg`) на левой панели и в меню «Инструменты».
- Современные шевроны для `QComboBox` / `QSpinBox` и крестик закрытия вкладки.

### Changed
- Светлая тема: разные фоны зон (окно / тулбары / доки / контент) и более
  заметные границы — панели не сливаются в один белый фон.
- «О программе»: убран путь к лог-файлу (есть **Справка → Открыть папку логов…**).

### Fixed
- **Единый ремаппинг `joint_uid` при `Ctrl+C` / `Ctrl+V`** (`core/clipboard.py`):
  предварительное резервирование новых UID стыков (`_prepopulate_joint_uids`) синхронизирует `JointRecord.uid`,
  ключи и элементы `panel.joint_hole_map` и 7-е поле `hole_joint_uid` в `panel.holes`, исключая дублирование отверстий
  при повторном `apply_joints`; при копировании одиночной просверленной панели без ответной детали осиротевшие
  стыковые отверстия переводятся в ручные (6 полей).
- **Учёт `center_offset` в `compute_joint_record_points`** (`core/joint.py`) и маркировка `tag_joint_hole` в `Viewport3D._place_fastener_at_preview`.
- **Чистота кода и тестов ревизии 0.0.19**: удалены неиспользуемые импорты, заменены тихие `except Exception: pass`
  на `_log.debug(...)` в `core/changelog.py` и `ui/theme.py`, расширен `numpy`-стаб в `tests/conftest.py`.
- B-Rep с пазами/отверстиями: синхронная сборка на UI-потоке, в заливке
  видны реальные вырезы (не только контур AABB).
- OCC/mesh: в UI передаётся только копия mesh, без solid из worker-потока.

## \[0.0.18\] - 2026-10-31


### Fixed — ревизия 4 §1.7 caplog / get_logger
- `get_logger`: явно `propagate=True` (записи доходят до file handler и caplog).
- `test_get_controller_1_5`: проверка имени `nestcraft.panel` + сообщения об ошибке.


### Fixed — ревизия 4 §1.6 гигиена архива
- `scripts/pack_src.sh`: zip без `__pycache__`, `.pyc`, `.pytest_cache`, `.ruff_cache`, `*.log`, DB каталога.
- `.gitignore`: `.ruff_cache/`, `.mypy_cache/`.


### Fixed — ревизия 4 §1.5 линтер ui/
- E702: разбиты строки с `;` в wireframe отверстий.
- F841: удалены мёртвые переменные палитры snap.
- F403/F405: `from OpenGL.GL import *` → явный список имён в `viewport.py`.
- per-file-ignores для ui: только BLE001.


### Added — ревизия 4 §1.4 реальный probe PID + Windows CI
- `test_probe_does_not_kill_live_process`: subprocess.sleep, assert poll is None.
- CI job `windows-pid` на `windows-latest` для test_pid_alive / test_pid_start.


### Fixed — ревизия 4 §1.3 WinAPI types + process_start
- `OpenProcess`/`GetExitCodeProcess`/`CloseHandle`/`GetProcessTimes`: argtypes/restype.
- `autosave_meta.process_start` + `is_same_process` против переиспользования PID.
- Без зависимости от psutil (WinAPI / Linux `/proc`).


### Fixed — ревизия 4 §1.2 без _Dummy в issues
- Удалены `_is_dummy_solid` и ветка AABB-fallback по имени `_Dummy` в `check_collisions_in_blocks`.
- Коллизии только через `CADKernel.find_scene_collisions` (как в UI).
- Тест: нет `_Dummy` в core/models/ui.


### Fixed — ревизия 4 §1.1 ручные отверстия + стыки
- При наличии `JointRecord` ручные отверстия **ремапятся** под новые габариты (`_remap_holes`),
  а не остаются на старых координатах; стыковые пересчитывает `apply_joints`.


### Fixed — ревизия 3 §1.6 линтер и mypy
- BLE001 активен для `models/` и `core/joint.py`; границы помечены `# noqa: BLE001`.
- per-file-ignores сужены до интеграции (OpenGL/Qt/SQLite/IO).
- CI: `mypy core models` с `continue-on-error: true`.


### Fixed — ревизия 3 §1.5 Panel._get_controller
- `ImportError` → тихий None (headless).
- Прочие исключения → `log.exception`, затем None (не маскируем сбой каталога).


### Fixed — ревизия 3 §1.4 тестовый код вне продакшена
- Удалена ветка `_Dummy` из `CADKernel.check_collision`.
- Stub в `conftest.py`: AABB-пересечение через `__and__` / `volume`.
- Headless Qt: единый `core/_qt_compat.py` (geometry_service, background_tasks).


### Added — ревизия 3 §1.7 CI slow + build123d matrix
- Job `slow` в `.github/workflows/tests.yml`: матрица `build123d==0.9.0` и `latest`.
- Проверка `Extrinsic.XYZ` перед `pytest -m slow`.
- Основной job по-прежнему `not slow and not gui`.


### Fixed — ревизия 3 §1.3 разорванный стык в «Проблемах»
- `check_broken_joints_in_blocks`: `joint_broken` (не касаются) и `joint_panel_missing`.
- Панель «Стыки»: разорванные записи помечаются ⚠ и красным.


### Fixed — ревизия 3 §1.2 joint_uid на отверстиях стыка
- Отверстия стыка: 7-й элемент кортежа = `joint_uid` (формат **0.0.8**).
- `extract_manual_holes` сначала смотрит метку, затем legacy `joint_hole_map`.
- Миграция `0.0.7 → 0.0.8` проставляет метки по карте.
- CADKernel по-прежнему берёт `hole[:6]`.


### Fixed — ревизия 3 §1.1 is_pid_running на Windows
- `_pid_alive_native`: на `win32` — `OpenProcess` + `GetExitCodeProcess` (STILL_ACTIVE),
  без `os.kill` (который на Windows завершает процесс).
- Linux/macOS по-прежнему `os.kill(pid, 0)`.
- Тесты: `tests/test_pid_alive_1_1.py`.

### Added & Improved — Единый механизм фоновых операций и снимков (ревизия 2, п. 2.4 и 1.11)
- **`core/background_tasks.py`, `core/project_io.py`, `core/cad_kernel.py`, `ui/main_window.py`**:
  - Введён единый менеджер фоновых задач `BackgroundTaskManager` на базе `QThreadPool` и `BackgroundTaskRunnable` с общими сигналами `task_started`, `task_progress`, `task_finished`, `task_failed` и отображением прогресса в строке состояния главного окна.
  - **Фоновый анализ коллизий по снимкам (`CollisionPanelSnapshot`)**: воркер больше не обращается к живым объектам `Panel` и их `solid` из другого потока, а строит B-Rep тела из неизменяемых снимков (`uid`, габариты, координаты, поворот, пазы, отверстия) с последующим сопоставлением результатов по `uid`.
  - **Фоновое автосохранение с изоляцией по PID**: снимок словаря сцены формируется на UI-потоке (`create_autosave_snapshot`), а сериализация JSON и атомарная запись на диск выполняются в `QRunnable` (`write_autosave_snapshot`). В имя файла автосохранения добавлен PID процесса (`autosave_recovery_<pid>.b3d`) с проверкой активности процесса (`is_pid_running`), благодаря чему параллельно запущенные экземпляры не перезаписывают и не удаляют файлы друг друга.
  - **Фоновая загрузка больших файлов (`ProjectDataSnapshot`)**: чтение файла, разбор JSON и прогон цепочки миграций вынесены в `QRunnable` (`read_project_snapshot`), а материализация блоков и панелей выполняется по сигналу завершения (`materialize_project_snapshot`).
  - Покрыто модульными тестами в `tests/test_background_tasks_2_4.py`.

### Added & Improved — Единое окно «Проблемы» и реестр проверок модели (ревизия 2, п. 2.2 и 3.8)
- **`core/issues.py`, `ui/panels/history_panel.py`, `ui/main_window.py`, `core/undo.py`**:
  - Введён единый класс замечания `Issue(severity, panel_uid, code, message)` и реестр проверок `ISSUE_CHECKS` (`check(blocks) -> list[Issue]`, `check_scene_issues(blocks)`).
  - Реализованы и объединены в общий список проверки модели и технологичности: отсутствующий материал (`missing_material`) и деталь без материала (`no_material`), отсутствующая кромка (`missing_edge`), ширина кромки меньше толщины детали (`edge_width_too_small`), несовместимость толщины детали с крепежом (`fastener_thickness_min` / `fastener_thickness_max`), отверстие ближе минимального отступа от края (`hole_near_edge`), попадание отверстия в паз (`hole_in_groove`), пересечение отверстий между собой (`holes_intersect`), превышение размера стандартного листа (`oversized_panel`), 3D-пересечение деталей (`panel_collision`) и сбой проверки пересечений (`collision_check_failed`).
  - Разрозненные предупреждения при открытии/восстановлении файла, правке свойств, установке присадки и анализе коллизий сведены в док-панель «Проблемы» (`AnalysisDock`); двойной клик по замечанию выделяет соответствующую деталь в сцене по её `uid` (`select_panel_by_uid`).
  - Покрыто модульными тестами в `tests/test_issues_2_2.py`.

### Refactored — Разделение модели `Panel` и сервисов через `SceneController` (ревизия 2, п. 2.1)
- **`models/panel.py`, `core/scene_controller.py`, `core/geometry_service.py`, `core/project_io.py`, `core/undo.py`, `tests/conftest.py`**:
  - Класс `Panel` переведён на `@dataclass(eq=False)` без прямых импортов `CatalogService`, `GeometryService` и `CADKernel`.
  - Создан менеджер сцены `SceneController` (`core/scene_controller.py`), связывающий чистую модель `Panel` с `CatalogService` (разрешение и назначение материалов, толщина плиты, кромки и контроль удалённых ссылок) и `GeometryService` (пересборка геометрии панелей и блоков).
  - В `GeometryService` добавлен безопасный headless-режим без `PyQt6`, благодаря чему `tests/conftest.py` больше не подменяет `core.geometry_service` и `core.cad_kernel` в `sys.modules`.
  - Покрыто модульными тестами в `tests/test_scene_controller_2_1.py`.

### Added & Improved — Качество кода: линтер, типизация и очистка импортов (ревизия 2, п. 2.3)
- **`pyproject.toml`, `.pre-commit-config.yaml`, `requirements-dev.txt`, `core/`, `models/`, `ui/`**:
  - Настроены `ruff` (`E`, `F`, `S110`, `BLE001`) и `mypy` (статическая проверка типов для пакетов `core/` и `models/`) в `pyproject.toml`, а также хуки `.pre-commit-config.yaml`.
  - Вычищены все неиспользуемые импорты в `core/`, `models/` и `ui/`.
  - Добавлен модульный тест `tests/test_code_quality_2_3.py`, контролирующий отсутствие мёртвых импортов и наличие конфигураций качества кода.

### Fixed & Improved — Тесты, CI и очистка архива от кэш-артефактов (ревизия 2, п. 1.9)
- **`.gitignore`, `.github/workflows/tests.yml`, `tests/test_performance_2_5.py`, `tests/test_cad_kernel_real_b123d.py`, `tests/conftest.py`**:
  - Из дерева проекта и архивов поставки исключены `.pytest_cache/`, `__pycache__/`, `*.pyc`, `*.log`, `build/`, `dist/`.
  - В `test_scene_gpu_ids_and_line_batching()` (`tests/test_performance_2_5.py`) добавлен `pytest.importorskip("PyQt6")`, чтобы тест корректно пропускался в headless-окружениях без `PyQt6`.
  - Добавлен модуль `tests/test_cad_kernel_real_b123d.py` с маркером `@pytest.mark.slow` для проверки реальных булевых операций `CADKernel` на `build123d` (вычитание отверстий и пазов, проверка пересечений `check_collision`).
  - Настроен CI-воркфлоу `.github/workflows/tests.yml` (Python 3.12, `pip install -r requirements-dev.txt`, `ruff check`, `pytest -m "not slow and not gui"` с `QT_QPA_PLATFORM: offscreen`).

### Fixed — Устранение глухих `except Exception: pass` и настройка линтера (ревизия 2, п. 1.10)
- **`core/`, `models/`, `ui/`, `pyproject.toml`, `tests/test_no_silent_except_1_10.py`**:
  - Во всех модулях `core/` (`core/catalog/db.py`, `core/joint.py`, `core/project_io.py`, `core/undo.py`, `core/issues.py`, `core/logging_setup.py`), `models/panel.py` и `ui/` (`ui/viewport.py`, `ui/main_window.py`, `ui/panels/properties_panel.py`, `ui/catalog_browser.py`, `ui/dialogs.py`) устранены глухие перехваты `except ...: pass`: непредвиденные сбои записываются через `_log.exception(...)`, а ожидаемые граничные состояния (отключение ещё не привязанных сигналов Qt, очистка временных файлов, ограничения драйвера GL Core Profile) логируются через `_log.debug(...)` с поясняющими комментариями.
  - Добавлен `pyproject.toml` с конфигурацией `ruff` (`S110` `try-except-pass`, `BLE001` `blind-except`) и AST-тест `tests/test_no_silent_except_1_10.py`, предотвращающий появление новых глухих обработчиков исключений.

### Fixed — Сбор и отображение несовместимости крепежа с толщиной детали в списке «Проблемы» (ревизия 2, п. 1.8)
- **`core/issues.py`, `core/joint.py`, `ui/viewport.py`, `ui/panels/history_panel.py`, `ui/main_window.py`**: добавлен класс `Issue(severity, panel_uid, code, message)` и реестр проверок `check_scene_issues(blocks)`. При нарушении ограничений `min_panel_thickness` / `max_panel_thickness` крепежа замечание не только пишется в `nestcraft.log`, но и сохраняется как `Issue`, выводится в строке состояния при установке крепежа и попадает в панель «Проблемы и анализ модели» (`AnalysisDock`) с переходом к детали по двойному клику (`select_panel_by_uid`). Покрыто тестом `test_fastener_thickness_incompatibility_collected_as_issue`.

### Fixed — Определение толщины детали в стыках через `panel.get_thickness()` вместо `min(width, height, depth)` (ревизия 2, п. 1.7)
- **`is_face_drilling`, `_hole_dims_for_fastener` (`core/joint.py`) и `Panel` (`models/panel.py`)**: в функциях расчёта присадки стыков и пазов вместо `min(width, height, depth)` используется `panel.get_thickness()` с учётом `thickness_axis`. У узких планок/царг (например, `16×10×500` мм из плиты 16 мм) сверление в пласть и глубина отверстий определяются по реальной толщине плиты (16 мм), а не по узкому габариту (10 мм). Покрыто модульным тестом `test_narrow_strip_16x10x500_uses_get_thickness`.

### Fixed — Исключение ошибочного кэширования сбоев при проверке коллизий (ревизия 2, п. 1.6)
- **`CADKernel.check_collision`, `CADKernel.find_scene_collisions` (`core/cad_kernel.py`), `MainWindow` (`ui/main_window.py`)**: при исключении во время построения `solid` или булева пересечения `solid_a & solid_b` ошибка логируется через `get_logger("cad_kernel").exception("collision failed")`, а результат `0.0` больше не записывается в `CADKernel._COLLISION_CACHE`. В пакетном анализе пересечений такие пары возвращаются с `vol=None` и отображаются в панели «Анализ пересечений» как `«⚠️ Не удалось проверить: …»` без заморозки кэша сцены.

### Fixed — Прямой импорт `build123d` без молчаливой подмены на `None` (ревизия 2, п. 1.5)
- **`core/cad_kernel.py`, `main.py`, `requirements.txt`, `core/version.py`**: из продакшен-кода `core/cad_kernel.py` убран блок `try/except ImportError: Box = Cylinder = ... = None` (заглушка `build123d` оставлена только в `tests/conftest.py`). В `main.py` при отсутствии или несовместимой версии `build123d` перехватывается `ImportError` с выводом понятного сообщения `«Установите build123d версии >= 0.9.0…»`; минимальная версия в `requirements.txt` поднята до `build123d>=0.9.0`.

### Fixed — Реальный прогрев ядра B-Rep на splash-экране (ревизия 2, п. 1.4)
- **`CADKernel.warmup()` (`core/cad_kernel.py`, `main.py`)**: на этапе «Прогрев ядра B-Rep (build123d)» вместо чисто питоновского `make_aabb_mesh` выполняется реальная сборка твердотельной детали с булевым вычитанием отверстия (`build_panel_solid_data(0, 0, 0, 16, 100, 100, holes=[(8, 50, 50, 3.5, 16, 'X')])`) и её триангуляция (`get_render_mesh`), что прогревает конвейер OpenCASCADE/build123d до создания главного окна.

### Fixed — Валидация параметров корпуса внутри `EditPropertyCommand` (ревизия 2, п. 1.3)
- **`EditPropertyCommand._apply_value` (`core/undo.py`) и `ValidationError` (`core/validation.py`)**: перед изменением структурных параметров `ParametricCabinet` (`width`, `height`, `depth`, `thickness`, `shelves_count`) вызывается `validate_cabinet_params(**cabinet_params_from_obj(obj, {attr: value}))`. При нарушении ограничений (например, `width=30`) команда выбрасывает `ValidationError` без модификации корпуса и его деталей и без записи шага в стек отмены; `MainWindow._on_property_applied` отображает причину отклонения в строке состояния.

### Fixed — Пропорциональное растягивание рядов присадки при изменении габаритов корпуса (ревизия 2, п. 1.2)
- **`ParametricCabinet._remap_holes` (`models/panel.py`)**: отверстия группируются по одной линии сверления `(drill_axis, поперечные координаты)`; для групп из $\ge 2$ отверстий вдоль изменившегося габарита координаты растягиваются между крайними точками (`_stretch_coord`) с сохранением отступов от краёв (средние отверстия остаются равноудалёнными, а не залипают у левого/нижнего ребра). Одиночные отверстия по-прежнему привязываются к ближайшему ребру (`_remap_local_coord`).

### Fixed — Индикатор несохранённых изменений после слияния команд (ревизия 2, п. 1.1)
- **`UndoStack.push` (`core/undo.py`)**: команда с `merge=True` (сдвиг детали стрелками или мышью, растягивание за ручку, быстрое редактирование свойства) больше не сливается в команду, являющуюся точкой сохранения (`self._clean_top`). Сдвиг после `Ctrl+S` теперь гарантированно переводит `is_clean()` в `False` (появляется `*` в заголовке окна, срабатывает защита при закрытии), а `Ctrl+Z` отменяет только изменения, сделанные после сохранения.

### Added & Improved — Устойчивость проекта и данных (п. 2.8 плана)
- **Автосохранение и восстановление после сбоя (`core/project_io.py`, `ui/main_window.py`)**:
  - Автоматическая запись несохранённых изменений во временный файл `AppDataLocation/autosave/autosave_recovery.b3d` (по таймеру и при модификации сцены).
  - При штатном сохранении, закрытии, создании нового или открытии другого проекта временный файл очищается (`clear_autosave`).
  - При запуске после нештатного завершения программа обнаруживает резервную копию и предлагает восстановить проект со всеми деталями, именем и исходным путём сохранения.
- **Список недавних файлов (`core/project_io.py`, `ui/main_window.py`)**:
  - Хранение до 10 недавних проектов в `AppDataLocation/recent_files.json` (`add_recent_file`, `load_recent_files`, `remove_recent_file`, `clear_recent_files`).
  - Подменю **«Файл → Недавние файлы»** для быстрого открытия проектов и очистки списка.
- **Цепочка миграций формата `.b3d` (`core/project_io.py`)**:
  - Последовательная миграция словаря проекта через цепочку шагов `v0.0.1 → v0.0.2 → v0.0.3 → v0.0.4 → v0.0.5 → v0.0.6` (`MIGRATION_STEPS`, `migrate_project_dict`) с автоматическим выводом `thickness_axis`, `role`, `edges`, `rx/ry/rz` и генерацией `uid`.
- **Контроль удалённых кромок при загрузке (`models/panel.py`, `core/project_io.py`, `ui/panels/properties_panel.py`)**:
  - При открытии `.b3d` проверяются ссылки на кромки всех 4 торцов (`top`, `bottom`, `left`, `right`) в каталоге; отсутствующие кромки сохраняются в `panel.missing_edges` (не теряются при пересохранении), выводятся в предупреждении при загрузке (`collect_missing_edges`) и помечаются в списке свойств детали как `⚠ Не найдена в каталоге (...)`.

### Fixed & Improved — Полная поддержка поворота деталей через OBB (п. 1.5 плана)
- **Модель панели (`models/panel.py`)**:
  - Добавлен метод `Panel.obb() -> (center, axes, half_extents)` (мировой центр, 3 ортонормированные оси в мировых координатах, полуразмеры).
  - Добавлены `Panel.world_to_local`, `Panel.rotate_vector`, `Panel.unrotate_vector`, `Panel.world_center`.
- **Стыки и присадка (`core/joint.py`)**:
  - `find_joint` поддерживает повёрнутые панели (`rx`, `ry`, `rz`) через OBB (проекции на нормали граней и касательную плоскость стыка).
  - `world_to_local_hole` и `make_joint_holes` переводят мировые координаты и направление сверления в локальную систему координат детали (кэш отверстий и пазы проверяются в локальных осях каждой панели).
- **3D-вьюпорт (`ui/viewport.py`)**:
  - Точки привязки (`_collect_panel_snap_points`) и пересечение луча с деталью (`_intersect_ray_panel`) работают в OBB через `local_to_world` / `world_to_local`.
  - Контуры отверстий (`_draw_panel_hole_wire`, `_draw_cylinder_wire`, `_draw_hole_marker`, `_draw_joint_and_preview`) ориентируются по повернутым осям детали и вектору сверления.
  - Фантом перетаскивания (`_draw_ghost_panel`) рисует повернутый каркас детали, пазов и отверстий.
  - Рамка выделения (`_select_panels_in_rect`) проверяет `p.world_corners()`.
  - Ручки масштабирования (`_panel_corners`, `_apply_corner_resize`) отображаются в реальных мировых углах детали и растягивают панель вдоль её локальных осей относительно фиксированного противоположного мирового угла.
  - Прилипание гранью к грани (`_face_to_face_snap`) учитывает `world_aabb()` и коллинеарные нормали OBB-граней.

### Improved — Производительность (п. 2.5 плана)
- **Меш (`CADKernel.get_render_mesh`, `Viewport3D._ensure_panel_gl_arrays`)**: полная векторизация разворачивания треугольников и расчёта нормалей на `numpy` без питоновских циклов `for tri in tris:`.
- **Батчинг линий (`Viewport3D`)**: контуры панелей, пазов и отверстий собираются по цветам (`_begin_line_batch` / `_flush_line_batch`) и рисуются одним вызовом `glBufferData` + `glDrawArrays(GL_LINES, ...)` на цвет в обычном режиме и в X-Ray.
- **Коллизии (`CADKernel` и `MainWindow`)**:
  - Broad-phase отсечение переведено на `world_aabb()` (корректно учитывает повернутые панели `rx`/`ry`/`rz`).
  - Результаты `CADKernel.check_collision` кэшируются по паре `(uid, geometry_generation, world_aabb)`.
  - Расчёт пересечений вынесен из UI-потока в фоновый `QRunnable` (`_CollisionWorker` в `QThreadPool`).
  - Если у деталей `geometry_pending == True`, выводится явный статус `«⏳ Геометрия ещё строится…»`.
- **Принадлежность панели сцене (`Viewport3D._panel_belongs_here`)**: $O(1)$ проверка через множество `_scene_gpu_ids` вместо обхода всех блоков и панелей на каждый сигнал `panel_geometry_updated`.

### Fixed — Восстановление удалённых панелей при Undo rebuild корпуса (п. 1.8)
- `EditPropertyCommand` сохраняет снимки структурных панелей корпуса перед `rebuild()` и при `undo()` передаёт их в `ParametricCabinet.rebuild(restore_by_role=...)` — возвращаются `uid`, имя, кромка, материал, цвет, поворот и присадка удалённых полок/фасадов/задней стенки.

### Fixed — Права доступа файла при сохранении проекта (п. 1.9)
- `save_project` в `core/project_io.py` сохраняет права существующего файла (`shutil.copymode`) или выставляет `0o666 & ~umask` для нового файла вместо `0600` от `NamedTemporaryFile`.

### Fixed — Консистентность версий и мелкие правки (п. 1.10)
- Единый источник версий `core/version.py` (`APP_VERSION`, `FORMAT_VERSION`, `MIN_SUPPORTED_VERSION`).
- Реальный прогрев B-Rep меша на сплэше вместо холостого шага.
- Убран магический сдвиг `self.x % 600` в `Panel.add_back_groove`.
- Дефолтная вкладка названа `«Новый проект»`; удаление по `Backspace` ограничено macOS (`sys.platform == "darwin"`).

### Added — Splash / экран загрузки
- Adobe-style splash при старте (`ui/splash.py` + макет `ui/icons/splash.svg`).
- Прогресс-бар (белый трек, оранжевая заливка), статус загрузки и актуальная версия `v0.0.18`.
- Этапы: OpenGL → CAD-ядро → каталог → CNC toolpaths → главное окно.
- Бесрамочное окно по центру экрана; после готовности splash закрывается и активируется MainWindow.

### Fixed — Undo / rebuild модулей (пункт 1 разбора v0.0.13)

- `EditPropertyCommand` больше **не вызывает** `rebuild()` / `rebuild_geometry()` для метаданных (`name`, `pos_num`, `code`).
- Переименование модуля или панели не уничтожает присадку, кромку, материалы и ручные сдвиги.
- Смена позиции корпуса (`x`/`y`/`z`) **сдвигает существующие панели**, а не пересоздаёт их через `panels.clear()`.
- Полный `ParametricCabinet.rebuild()` вызывается только при изменении структурных параметров: габариты, толщина, число полок, фасад, `has_groove`.
- Для обычной `Panel` геометрия пересобирается только при изменении размеров / координат / поворота / материала.

### Fixed — умный diff-rebuild корпуса

- У `Panel` появилось поле `role` (`left` / `right` / `bottom` / `top` / `shelf_N` / `facade` / …).
- `ParametricCabinet.rebuild()` больше не делает `panels.clear()`: сопоставляет панели по `role`, обновляет геометрию и структурные пазы, **сохраняет** holes, edges, material, color, rx/ry/rz, selected и пользовательское имя.
- Лишние роли (например, полки при уменьшении `shelves_count`) удаляются; ручные панели без role остаются в блоке.
- Для старых проектов без `role` — эвристика по имени детали.
- `role` сохраняется/загружается в `.b3d`.
- При смене габаритов корпуса отверстия **пересчитываются с привязкой к ближайшему ребру** (стыковая присадка на дне/полке едет вместе с боковинами, а не залипает на старых координатах).


### Fixed — крепёж / стыки (пункт 2 разбора v0.0.13)
- `_overlap_1d`: стык только при **строго положительной** длине перекрытия (ребро/угол больше не стык).
- `make_joint_holes`: парный расчёт; сдвиг от паза применяется к **обеим** панелям в мировых координатах (соосность сохраняется).
- Защита от паза работает по всем осям, с повторной проверкой.
- `CADKernel`: overshoot цилиндра отверстия **с обоих концов** (устраняет копланарность на выходе сквозной пласти).


### Fixed — поворот (пункт 3 приоритетов / баг 6 разбора)
- Поворот B-Rep вокруг **геометрического центра** панели (не min-corner).
- `Panel.local_to_world` / `world_corners` / `world_aabb` / `has_rotation`.
- Пикинг луча использует world-AABB (оболочка OBB).
- Контур и пазы рисуются по повёрнутым углам (`_draw_oriented_box_wireframe`).
- AABB-превью (`make_aabb_mesh`) учитывает rx/ry/rz.
- `check_collision` prefilter — по world-AABB.
- `find_joint` для повёрнутых панелей пока возвращает `None` (OBB-стык — отдельно).


### Fixed — надёжность файлов (пункт 4 приоритетов)
- Флаг `is_modified` + `*` в заголовке; вопрос при «Новый» / «Открыть» / закрытии окна.
- Атомарное сохранение: temp + `os.replace` (нет битого `.b3d` при сбое).
- Проверка версии файла при открытии (предупреждение о будущей/слишком старой).
- Предупреждение о материалах, отсутствующих в каталоге.
- «Открыть» больше не кладёт сцену в undo (Ctrl+Z не подменяет файл под новым путём).


### Fixed — GPU-ресурсы viewport (пункт 5 приоритетов)
- Удаление VAO/VBO только при текущем GL-контексте: очередь `_gpu_delete_queue` + flush в `paintGL`.
- Стабильный `panel._gpu_id` вместо `id(panel)` (нет коллизий после GC).
- `_reconcile_panel_gpu`: сироты после Undo добавления / ReplaceBlocks.
- `_free_all_panel_gpu` при открытии проекта, очистке сцены, закрытии вкладки.
- `GeometryService.panel_geometry_updated` обрабатывается только для панелей **своей** сцены.


### Fixed — дублирование Ctrl+D (пункт 6 / баг 5 разбора)
- Копия получает **rx/ry/rz**, **edges**, thickness_axis, material, holes, grooves.
- Имена: «Стол (Копия)», «Стол (Копия 2)» — без «(Копия) (Копия)…».
- Уникальный `pos_num` внутри блока.
- `Panel.clone()` — единый метод полной копии (role сбрасывается).


### Fixed — валидация ввода (пункт 7 / баг 10 разбора)
- Панель свойств: отклоняются `nan`/`inf`, нулевые и отрицательные габариты, пустые числа.
- Диапазоны: размеры 1…10000 мм, координаты ±50000, углы ±360°, полки 0…50.
- Невалидный ввод откатывает ячейку к прежнему значению (модель не меняется).
- Верхние поля X/Y/Z — та же проверка.
- `EditPropertyCommand` — финальный барьер sanitize перед `setattr`.


### Fixed — клавиша Delete (пункт 8 / баг 11 разбора)
- QAction «Удалить» с `WindowShortcut` — работает, даже если фокус не во viewport.
- Delete/Backspace не сносят деталь, пока фокус в поле ввода (свойства, координаты, таблица).
- После удаления фокус возвращается во viewport.


### Fixed — thickness_axis в .b3d (баг 8 разбора)
- `thickness_axis` пишется и читается в проекте (формат **0.0.5**).
- Старые файлы без поля: ось по-прежнему выводится из минимального габарита.


### Fixed — 1.1 missing material + 1.2 dirty/clean (план v0.0.18)
- При загрузке неизвестный `material_id` сохраняется в `panel.missing_material_id`; предупреждение и запись в .b3d работают.
- `UndoStack.mark_clean()` / `is_clean()`: «Новый» / «Открыть» / «Сохранить» не оставляют `*` из-за `clear()`; Undo до clean снимает dirty.


### Fixed — 1.3 валидация корпуса (план v0.0.18)
- `core/validation.py`: минимумы ширины (2t+50), высоты (3t+50), глубины (140), толщина 1…100, полки vs высота.
- Панель свойств отклоняет недопустимые габариты корпуса, откатывает ячейку, пишет причину в statusBar.
- Толщина плиты у обычной панели по-прежнему только из материала (не редактируется).


### Fixed — 1.6 overshoot только на гранях (план v0.0.18)
- Цилиндр отверстия удлиняется на 0.5 мм лишь у конца, лежащего на грани панели.
- Сквозные: вылет с обоих концов (анти-копланарность OCC).
- Глухие: вылет только у входа — глубина сверления соответствует заданной.


### Fixed — 1.4 порядок углов Extrinsic.XYZ (план v0.0.18)
- B-Rep: `Rotation(rx,ry,rz, ordering=Extrinsic.XYZ)` вместо `Rot()` (Intrinsic.XYZ).
- Согласовано с `Panel.rotation_matrix` (Rz@Ry@Rx): превью, контур, пикинг и solid совпадают при нескольких углах.


### Fixed — 1.8 сохранение данных удалённых панелей при Undo (план v0.0.18)
- `EditPropertyCommand` перед структурным `ParametricCabinet.rebuild()` сохраняет словари удаляемых панелей (`_panel_to_dict` по `role`), включая склейку шагов `merge_with`.
- `ParametricCabinet.rebuild(restore_by_role=...)` восстанавливает ранее удалённые панели (полки, фасад, царги) со всей их присадкой, кромкой, материалом, цветом, `uid` и пользовательским именем.
- Исправлена проверка авто-имени в `_update_panel_from_spec`: пользовательские имена вида «Полка средняя кастом» больше не затираются при пересборке.


### Fixed — 1.9 права файла после сохранения (план v0.0.18)
- `save_project` больше не оставляет права `0600` от `tempfile.mkstemp`: для нового файла выставляется `0o666 & ~umask`, а для существующего копируются прежние права через `shutil.copymode`.


### Fixed — 1.10 мелочи и консистентность (план v0.0.18)
- Создан единый модуль `core/version.py` (`APP_VERSION`, `FORMAT_VERSION`, `MIN_SUPPORTED_VERSION`), подключён в `main.py`, `ui/splash.py`, `ui/main_window.py` (окно «О программе») и `core/project_io.py`.
- Фиктивный этап splash-экрана `Loading CNC toolpaths…` заменён реальным прогревом ядра B-Rep (`CADKernel`).
- Из `Panel.add_back_groove` убран хак `self.x % 600`; сторона паза передаётся явно (`right`/`left`/`top`/`bottom`).
- Заглушки `UFA004KUH2026` в `main_window.py`, `properties_panel.py` и `viewport.py` заменены на «Новый проект».
- Удаление клавишей `Backspace` ограничено macOS (на Windows/Linux работает только `Delete`); удалена недостижимая ветка в `_focus_is_text_input`.
- Обновлена структура проекта и версия `.b3d` в `README.md`.


### Added — 2.1 логирование (план v0.0.18)
- `core/logging_setup.py`: RotatingFileHandler в AppData/logs, stderr для WARNING+.
- `sys.excepthook`: трассировка в лог + диалог с путём к файлу.
- `log.exception` в каталоге, GeometryService, project_io, GPU-delete, open/save.


### Added — 2.2 автотесты (план v0.0.18)
- `tests/` + `pytest.ini` + `requirements-dev.txt`.
- `conftest.py`: stub build123d / GeometryService до импорта models.
- Покрыто: saw_dimensions, find_joint/holes/array, Panel.clone, .b3d round-trip,
  EditPropertyCommand, cabinet rebuild (role), validation, undo clean-point.
- Запуск: `pytest` из корня проекта (19 tests).


### Added — 2.7 стабильные uid (план v0.0.18)
- `Panel.uid` / `Block.uid` (uuid4); формат .b3d **0.0.6**.
- Старые файлы без uid получают новый при загрузке.
- `Panel.clone()` всегда с новым uid (не делит id с оригиналом).


### Fixed — 2.4 сверление из каталога (план v0.0.18)
- `make_joint_holes(..., fastener_id=)` / `_hole_dims_for_fastener` берут
  `drill_face_*`, `drill_edge_*`, `drill_through` из `Fastener`.
- min/max_panel_thickness → warning в лог.
- Пресеты — только раскладка; диаметры/глубины больше не угадываются по `≈7.0`.
- Fallback legacy, если каталог недоступен.


### Changed — 2.3 каталог в AppData (план v0.0.18)
- Рабочая БД: `AppDataLocation/catalog/nestcraft_catalog.db` (не Program Files).
- Встроенный `data/catalog/nestcraft_catalog.db` — seed, копируется при первом запуске.
- Перед миграцией схемы — `.bak` (хранятся последние 5).


### Fixed — 2.6 API каталога (план v0.0.18)
- `insert_material` / `update_material` / `delete_material` с инвалидацией кэша.
- `insert_fastener` / `update_fastener` / `delete_fastener`.
- `_edge_cache` создаётся в `__init__` (без `hasattr`).
- UI `catalog_browser` больше не трогает `_materials` / `_mat_cache`.

## \[0.0.17\] - 2026-10-30

### Added — дерево групп в библиотеке материалов

- Слева в **Инструменты → Библиотека…** — панель групп (как структура модели).
- Разделы: **Листовые материалы**, **Кромочные материалы**, **Фурнитура** + подгруппы.
- Кнопки: **+ Группа**, **+ Подгруппа**, **Переименовать**, **Удалить**.
- Схема БД v2 (`catalog_groups`, `group_id`); миграция + автопривязка seed-материалов.
- Сетка / привязка 2D, viewport и main_window из 0.0.13 **не откатывались**.

## \[0.0.13\] - 2026-10-28

### Changed

- Сетка только в 2D-видах (спереди, сверху, сбоку). В изометрии её нет.
- Кнопка «Сетка» включает и выключает сетку. Шаг сетки: 1 / 10 / 16 / 32 / 50 / 100 мм.
- При включённой сетке перенос панели (G и стрелки) привязывается к узлам сетки в плоскости текущего вида. Стык «грань к грани» приоритетнее сетки.

## \[0.0.12\] - 2026-10-27

### Fixed

- **Устранение копланарных артефактов булевых операций в B-Rep ядре (**`core/cad_kernel.py`**)**:
  - Добавлен гарантированный вылет (overshoot = 0.5 мм) цилиндров отверстий за пределы наружных граней детали.
  - Предотвращено появление микроплёнок и сбоев OpenCASCADE при вычитании сквозных и торцевых отверстий, копланарных граням панели.
- **Технологическая защита от пробития паза задней стенки (ХДФ)**:
  - Метод `Panel.check_hole_groove_collision` выполняет прецизионную проверку пересечения цилиндров присадки с пазами детали.
  - В `core/joint.py` алгоритм расстановки крепежа автоматически сдвигает отверстия из опасной зоны паза в безопасную зону с гарантированным отступом.

### Added

- **Полноценная система кромкооблицовки (Edge Banding) и расчёт пильных размеров**:
  - В класс `Panel` добавлена структура `edges` для всех 4 торцов (`top`, `bottom`, `left`, `right`).
  - Методы `Panel.set_edge(side, edge_id)`, `Panel.get_edge_thickness(side)` с интеграцией с SQLite каталогом кромок.
  - Метод `Panel.get_saw_dimensions()`: автоматический расчёт технологических размеров под раскрой ($L\_{\\text{saw}} = L - T\_{\\text{left}} - T\_{\\text{right}}$) по ГОСТ и стандартам Базис-Мебельщик.
  - В панель свойств `PropertiesDock` добавлены 4 интерактивных выпадающих списка с кромками из каталога и отображение расчётного пильного размера детали.
  - Добавлен специализированный диалог `EdgeBandEditDialog` (`ui/edge_dialog.py`) для создания и редактирования кромочных лент с выбором цвета/декора, толщины, ширины и цены.
  - В библиотеку каталога (`ui/catalog_browser.py`) добавлены фильтры по толщине кромок, CRUD операции (+ Новая, ✎ Изменить, ✕ Удалить) с фиксацией в SQLite и кнопки быстрого нанесения кромки на все 4 стороны или выбранный торец детали.
  - В `core/undo.py` команды `EditPropertyCommand` поддерживают независимую отмену/повтор нанесения кромки на отдельный торец (`edge_<side>`) или на все стороны сразу (`edges_all`).
- **Поддержка пространственной ориентации детали (Rotation Rx, Ry, Rz)**:
  - В класс `Panel`, `CADKernel` и фоновый сервис `GeometryService` добавлена поддержка углов поворота `(rx, ry, rz)`.
  - Возможность редактирования углов в панели свойств и сохранение ориентации в формат проекта.
- **Обновление формата проекта** `.b3d` **v0.0.4**:
  - Сохранение и загрузка углов поворота `rx, ry, rz` и структуры кромкооблицовки `edges` с полной обратной совместимостью для старых версий файлов.

## \[0.0.11\] - 2026-10-27

### Added

- **Каталог материалов и крепежа (SQLite)**:
  - Полноценная БД `data/catalog/nestcraft_catalog.db` с версионированной схемой и миграциями.
  - Модуль `core/catalog/`: models, db, material_repo, fastener_repo, catalog_service, seed.
  - Сущности: материалы (ЛДСП/МДФ/ХДФ), кромка, крепёж, типы крепежа, категории, поставщики.
  - Правила сверления крепежа (пласт / торец, диаметры, глубины) хранятся в БД.
  - Стартовый набор: 11 материалов, 6 кромок, 6 позиций крепежа (конфирмат, шкант, минификс, полкодержатель).
  - `CatalogService` — синглтон с кэшем, поиском и удобным API.
  - Задел на будущее: цены, поставщики, пользовательские материалы, миграции схемы.
- **Привязка панелей к каталогу**:
  - `Panel.material_id` — каноническая ссылка на запись в БД; `material` — display name.
  - Авторезолв цвета и имени из каталога при создании панели.
  - `Panel.apply_material(id)` для смены материала с обновлением цвета.
  - Формат `.b3d` v0.0.3: сохраняется `material_id` + `material`.
  - Обратная совместимость: старые проекты без `material_id` подбирают материал по имени.
  - Правка «Материал» в свойствах ищет в каталоге и обновляет id/цвет (с Undo).
- **Выпадающий список материалов в панели свойств**:
  - Для выделенной панели поле «Материал» — `QComboBox` из каталога.
  - Подписи вида `ЛДСП · Дуб Сонома 16 мм`, сортировка по типу и толщине.
  - Смена материала обновляет `material_id`, display name и цвет (с полной поддержкой Undo).
- **Присадка из каталога крепежа**:
  - `HoleDialog` загружает шаблоны из `CatalogService` (диаметры/глубины пласть и торец).
  - Показ правил сверления: пласть / торец / рекомендуемый шаг.
  - Пресеты стыка (`Ctrl+H` / Tab) берут Ø и глубину из каталога через `get_fastener_preset()`.
  - Связь пресетов с `fastener_id` (fst_conf_7x50, fst_dowel_8x30, …).
- **Библиотека материалов и крепежа** (`ui/catalog_browser.py`):
  - Окно с вкладками: Материалы / Кромка / Крепёж.
  - Поиск, фильтры по типу и толщине, цветовые превью в таблице.
  - Карточка свойств выбранной позиции (сверление, цены, артикулы).
  - Меню: Инструменты → Библиотека материалов и крепежа… (`Ctrl+Shift+M`).
  - Кнопка **«Назначить на выделенную панель»** и двойной клик по материалу — применяют материал к панели в сцене (с Undo и обновлением цвета).
  - Кнопка **«+ Новый материал»** и форма (`ui/material_dialog.py`): название, тип, толщина, цвет (пипетка), цена, сверление; сохранение в локальный каталог (`is_builtin=False`).
  - Кнопки **«Изменить»** и **«Удалить»** для выбранного материала (с подтверждением; встроенные тоже можно удалить из локальной БД).

## \[0.0.10\] - 2026-10-27

### Added

- Иконки для кнопок построения панелей на левой панели инструментов:
  - Вертикальная панель (`ui/icons/vertical_panel.svg`)
  - Горизонтальная панель (`ui/icons/horizontal_panel.svg`)
  - Фронтальная панель (`ui/icons/frontal_panel.svg`)
- Кнопки отображаются как иконки 32×32 с подсказками при наведении.

## \[0.0.9\] - 2026-10-26

### Added

- **Универсальное глобальное примагничивание по** `[Ctrl]` **(Global Always-On Magnetic Snapping)**:
  - **Работает всегда в 3D пространстве**: при зажатии `Ctrl` в любом режиме (включая стандартный режим моделирования без рулетки) курсор мгновенно примагничивается к характерным геометрическим точкам сцены.
  - **Без предварительного выделения детали**: кандидаты привязки автоматически ищутся по абсолютно всем деталям и блокам сцены.
  - **Силовой эластичный луч притяжения (Rubber-Band Tether Line)**: при наведении курсора рядом с характерной точкой отображается динамическая нить магнитного притяжения, наглядно соединяющая физический курсор с примагниченной 3D-точкой на экране.
  - **Усиленный захват по клавише** `Ctrl`:
    - Увеличение радиуса захвата более чем в 2 раза (до 54px).
    - Приоритетное притягивание к точным углам (вершинам) и серединам рёбер.
    - Динамический HUD-бейдж `🧲 {dist}px` прямо на середине луча притяжения.
    - Ореол силового поля притяжения (внешнее кольцо захвата 16px с заливкой и внутреннее кольцо фиксации).
    - Верхний HUD-баннер: `🧲 [Ctrl] МАГНИТНЫЙ ЗАХВАТ: {точка} | ЛКМ — выделить деталь`.
  - **Быстрое выделение детали по магнитному клику**: клик ЛКМ с зажатым `Ctrl` по примагниченной точке моментально делает соответствующую деталь активной и обновляет координаты в статус-панели и инспекторе.
  - **Лаконичная визуальная индикация привязки (чистый экран без назойливых плашек)**:
    - **Оранжевый ромбик без заливки**: при наведении и нажатии `Ctrl` точка привязки отмечается аккуратным контурным оранжевым ромбиком (hollow orange diamond, без глухой заливки), не перекрывающим детали мебели и рёбра.
    - **Удалены загромождающие экран текстовые карточки**: убраны назойливые всплывающие плашки вида `левая боковина: левый нижний угол`, которые перекрывали обзор и мешали работе.
    - **Тонкая эластичная нить магнита**: мягкий оранжевый пунктирный луч от курсора к примагниченной точке наглядно показывает вектор зацепа.
  - **Мгновенная реакция клавиатуры**: отслеживание нажатия и отпускания `Ctrl` через `keyPressEvent` / `keyReleaseEvent` с моментальной перерисовкой экрана без необходимости шевелить мышь.
- **Перемещение детали кликом мыши по базовой точке (G → Клик точки зацепа → Следование за курсором → Клик фиксации)**:
  - **Чёткий и удобный порядок перемещения**:
    1. **Выделили деталь и нажали** `G` (или кнопку «🎯 Переместить (G)» на панели): включается режим выбора точки зацепа. На детали подсвечиваются углы, середины рёбер, торцы и центр.
    2. **Однократный клик ЛКМ по точке, за которую будете тащить панель**: один клик ЛКМ фиксирует точку зацепа $P\_{\\text{base}}$.
    3. **Панель сразу начинает следовать за курсором (без зажатия ЛКМ!)**: пользователь свободно водит мышью без нажатия кнопок (активен `setMouseTracking(True)`). Деталь следует за курсором именно выбранным местом в виде 3D фантома, соединяясь вектором смещения и показывая бейдж $\\Delta X, \\Delta Y, \\Delta Z$ и $L$.
    4. **Магнитный захват по \[Ctrl\]**: при удержании `Ctrl` радиус притяжения к углам, рёбрам и отверстиям других деталей увеличивается до 54px со световым лучом `🧲 {dist}px`.
    5. **Второй однократный клик ЛКМ**: надёжно фиксирует деталь в целевом месте тем местом, которое выбрали ($P\_{\\text{dest}} = P\_{\\text{target}}$).
    6. **Отмена**: клавиша `Esc` или клик правой кнопкой мыши (`ПКМ`) мгновенно возвращает деталь на исходные координаты.
  - Полная поддержка истории изменений `Undo / Redo (Ctrl+Z / Ctrl+Y)` через `MovePanelCommand`.
- **Инструмент «Рулетка / Размерные линии и углы» (Tape Measure & Angle Dimension)**:
  - Горячая клавиша `M` (или кнопка на верхней и левой панелях инструментов).
  - **Вычисление углов по 3 точкам (2 отрезкам)**: при клике 3 точек рулетка вычисляет угол в градусах $\\theta \\in \[0^\\circ, 180^\\circ\]$ между лучами $P_1-P_2$ и $P_3-P_2$ в вершине $P_2$.
  - **Отрисовка 3D дуги угла**: адаптивная дуга в плоскости двух отрезков, а для прямых углов 90° ($|\\theta - 90^\\circ| &lt; 0.35^\\circ$) — классический архитектурный квадратный маркер прямого угла.
  - **Информационный бейдж угла**: золотисто-янтарный бейдж `∠ = θ°` (с пометкой `[Прямой]` при 90°), длинами обоих плеч $L_1$ и $L_2$, позиционируемый по направлению биссектрисы угла.
  - Умная привязка (Smart Snapping, до 24px) к характерным точкам деталей: 8 углов AABB, 12 середин ребер, геометрический центр панели, центры отверстий существующей присадки, а также поверхности деталей и плоскость пола (Y=0).
  - 3D размерные линии с засечками (45° архитектурные штрихи) и вспомогательными ортогональными проекционными направляющими по осям X/Y/Z.
  - Высокочеткие векторные 2D HUD-бейджи поверх 3D сцены: отображение реальной длины (`L = ... мм`) и проекций (`ΔX, ΔY, ΔZ`).
  - Фиксация произвольного числа линейных и угловых размеров на сцене и кнопка «Очистить размерные линии».
  - Подсказка курсора при наведении (ромбовидный маркер и бейдж привязки: «Угол детали», «Середина ребра», «Отверстие» и т.д.).

### Fixed

- **Утечка видеопамяти (VRAM)**: реализовано корректное удаление старых VAO/VBO/EBO буферов через `glDeleteVertexArrays` и `glDeleteBuffers` при перестройке геометрии и удалении деталей.
- **Дублирование панели (Ctrl+D)**: исправлена потеря присадки (holes) и кода детали при создании копии.
- **Присадка пласть / торец**: функция `make_joint_holes` теперь математически различает сверление в пласть (сквозное Ø7 под конфирмат / глухое 12 мм под шкант) и в торец (глухое Ø5×38 мм под резьбу конфирмата / 24 мм под шкант) в соответствии со стандартами мебельного крепежа.
- **Паз под заднюю стенку (ХДФ)**: метод `add_back_groove` больше не зависит от абсолютной мировой координаты `x <= 1.0`, корректно позиционируя паз на внутренней стороне боковины и дна.
- **Освещение и нормали B-Rep**: в `CADKernel.get_render_mesh` устранены грязные темные градиенты на прямых углах ЛДСП за счет раздельных нормалей граней.
- **Синхронизация дерева модели**: при нажатии Delete во вьюпорте отправляется сигнал `scene_structure_changed`, дерево модели сразу удаляет узел детали.
- **Отмена правок в свойствах (Undo/Redo)**: изменение параметров в `PropertiesDock` теперь оборачивается в `EditPropertyCommand` и поддерживает откат через Ctrl+Z.
- **Склейка шагов сдвига (Command merging)**: последовательные перемещения детали стрелками клавиатуры объединяются в один шаг UndoStack, предотвращая переполнение стека истории.
- **Лишние фоновые перестройки при открытии .b3d**: `_block_from_dict` больше не пересоздает дефолтные панели корпусов перед загрузкой реальных панелей из файла.

## \[0.0.8\] - 2026-10-26

### Added

- Асинхронный B-Rep rebuild: `GeometryService` + `QThreadPool` / `QRunnable`
- Сразу low-poly AABB-превью (`CADKernel.make_aabb_mesh`), точная сетка в фоне
- `generation_id` отбрасывает устаревшие результаты при быстрых правках
- Сигнал `panel_geometry_updated` → обновление VBO во viewport; pending-панели чуть бледнее

## \[0.0.7\] - 2026-10-25

### Changed

- Переход viewport на **OpenGL 3.3 Core Profile**: убраны `glMatrixMode` / `gluPerspective` / `glLight*` / `glBegin` / display lists / client-state
- Шейдеры GLSL 330: Phong для заливки панелей, простой color для линий
- Панели: VBO + VAO + EBO; сетка: статический VBO; контуры/крепеж: dynamic line VBO
- Матрицы и unproject/project в `core/glmath.py` (numpy); `QSurfaceFormat` Core 3.3 в `main.py`

## \[0.0.6\] - 2026-10-25

### Changed

- Отрисовка заливки панелей: вместо immediate mode (`glBegin`/`glVertex` на каждый треугольник) — client-side vertex arrays + `glDrawElements` (один draw call на панель)
- Сетка пола: OpenGL display list (компиляция один раз в `initializeGL`)
- Кэш `_gl_arrays` (float32 pos/nrm, uint32 indices) на `Panel`, сброс при `rebuild_geometry`

## \[0.0.5\] - 2026-10-25

### Changed

- Крепёж и отверстия присадки рисуются каркасными цилиндрами по диаметру отверстия (как шкант), а не крестом/линиями
- Превью крепежа на стыке — полный цилиндр, уходящий в обе панели

## \[0.0.4\] - 2026-10-25

### Added

- Крепёж по стыку двух панелей: Shift+ЛКМ выбрать вторую → Ctrl+H → превью вдоль стыка → ЛКМ поставить
- Превью ограничено пределами стыка; Esc — выход из режима
- Оранжевые маркеры существующих отверстий присадки

## \[0.0.3\] - 2026-10-25

### Added

- Сохранение / открытие проекта в формате `.b3d` (JSON): панели, пазы, присадка, корпуса
- Диалог присадки (Ctrl+H): шаблоны евровинт, шкант, минификс; вычитание отверстия в B-Rep
- Маркеры осей отверстий в 3D

## \[0.0.2\] - 2026-10-25

### Added

- Освещение OpenGL (LIGHT0) и вершинные нормали из B-Rep mesh
- Стек Undo/Redo (Ctrl+Z / Ctrl+Y): сдвиг, удаление, добавление, дублирование, очистка, модули
- Док «История» показывает стек отмены

### Fixed

- (ранее) зелёная рамка выделения справа налево

## \[0.0.1\] - 2026-10-25

### Added

- Прототип CAD для корпусной мебели (PyQt6 + OpenGL + build123d/OpenCASCADE)
- Параметрический корпус (`ParametricCabinet`): боковины, дно, крышка/царги, полки, фасад
- Пазы под ХДФ, проверка пересечений B-Rep
- 3D-вьюпорт, структура модели, свойства, шаблоны кухонных модулей

### Fixed

- Рамковое выделение: направление жеста (слева направо / справа налево)
- Сигналы 3D-вьюпорта при смене и создании вкладок
- Дубликат `mouseMoveEvent` в `viewport.py`
- Опечатка `panel_queries_emit` при удалении
- Мусор Google Docs в `ui/__init__.py` и `ui/panels/__init__.py`
- Пазы от реальной толщины панели (не хардкод 16 мм)
- Коллизии используют кэш `panel.solid`
- Дублирование панели в тот же блок, где оригинал
- Синхронизация выделения дерево ↔ 3D (`highlight_object`)
- Откат неверного значения в панели свойств