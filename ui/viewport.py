from PyQt6.QtWidgets import QMenu, QTabWidget
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtGui import QSurfaceFormat, QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal
from OpenGL.GL import (
    GL_ALIASED_LINE_WIDTH_RANGE,
    GL_ALWAYS,
    GL_ARRAY_BUFFER,
    GL_BACK,
    GL_BLEND,
    GL_CCW,
    GL_COLOR_BUFFER_BIT,
    GL_CLIP_DISTANCE0,
    GL_COMPILE_STATUS,
    GL_CULL_FACE,
    GL_DECR_WRAP,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_STENCIL_ATTACHMENT,
    GL_DEPTH_TEST,
    GL_DRAW_FRAMEBUFFER,
    GL_DRAW_FRAMEBUFFER_BINDING,
    GL_DYNAMIC_DRAW,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE,
    GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE,
    GL_FRONT,
    GL_GREATER,
    GL_INCR_WRAP,
    GL_KEEP,
    GL_LEQUAL,
    GL_LESS,
    GL_LINES,
    GL_LINK_STATUS,
    GL_MULTISAMPLE,
    GL_NONE,
    GL_NOTEQUAL,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_POLYGON_OFFSET_FILL,
    GL_PROGRAM_POINT_SIZE,
    GL_SCISSOR_TEST,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_STENCIL,
    GL_STENCIL_ATTACHMENT,
    GL_STENCIL_BUFFER_BIT,
    GL_STENCIL_TEST,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNSIGNED_INT,
    GL_VERTEX_SHADER,
    glAttachShader,
    glBindBuffer,
    glBindVertexArray,
    glBlendFunc,
    glBufferData,
    glClear,
    glClearColor,
    glClearStencil,
    glColorMask,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glCullFace,
    glDeleteBuffers,
    glDeleteProgram,
    glDeleteShader,
    glDeleteVertexArrays,
    glDepthFunc,
    glDepthMask,
    glDisable,
    glDrawArrays,
    glDrawElements,
    glEnable,
    glEnableVertexAttribArray,
    glFrontFace,
    glGenBuffers,
    glGenVertexArrays,
    glGetFloatv,
    glGetFramebufferAttachmentParameteriv,
    glGetIntegerv,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLineWidth,
    glLinkProgram,
    glPolygonOffset,
    glShaderSource,
    glStencilFunc,
    glStencilMask,
    glStencilOp,
    glStencilOpSeparate,
    glUniform1f,
    glUniform2f,
    glUniform3f,
    glUniform4f,
    glUniformMatrix4fv,
    glUseProgram,
    glVertexAttribPointer,
    glViewport,
)
import numpy as np
import ctypes
import math
from models.panel import Panel, Block, ParametricCabinet
from core.undo import UndoStack, DeleteItemsCommand, MovePanelCommand, PlaceJointFastenerCommand, ResizePanelCommand, PasteBlocksCommand
from core.clipboard import (
    capture_selection,
    set_anchor,
    materialize,
    ClipboardPayload,
    panel_dict_preview_corners,
)
from core.joint import (
    find_joint, clamp_joint_point, make_joint_holes, joint_array_points,
    FASTENER_PRESET_ORDER, JointRecord, get_fastener_preset,
    tag_joint_hole, hole_joint_uid,
)
from core.hole_nav import (
    HoleHit,
    collect_owner_holes,
    describe_hole_hit,
    pick_hole_at_ray,
)
from core.cad_kernel import CADKernel
from core.geometry_service import GeometryService
from core.scene_controller import SceneController
from core.logging_setup import get_logger
from ui.theme import current_theme

_log = get_logger("viewport")
from core import glmath
from core.dimension import (
    DimensionAngle,
    DimensionLine,
    MeasureTarget,
    build_measure_target,
    compute_smart_measurement,
)


# --- GLSL 330 Core ---
_SOLID_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
uniform mat4 uMVP;
uniform vec4 uClipPlane;
out vec3 vNormal;
out vec3 vPos;
void main() {
    vPos = aPos;
    vNormal = aNormal;
    gl_Position = uMVP * vec4(aPos, 1.0);
    gl_ClipDistance[0] = dot(vec4(aPos, 1.0), uClipPlane);
}
"""

_SOLID_FS = """
#version 330 core
in vec3 vNormal;
in vec3 vPos;
uniform vec3 uColor;
uniform vec3 uLightDir;
uniform vec3 uKeyDir;
uniform vec3 uFillDir;
uniform vec3 uViewDir;
uniform vec4 uClipPlane;
uniform float uAlpha;
out vec4 fragColor;
void main() {
    // Стабилизация плоских граней через аналитическую производную (dFdx/dFdy),
    // чтобы исключить артефакты интерполяции нормалей на острых 90° рёбрах панелей
    vec3 geomN = cross(dFdx(vPos), dFdy(vPos));
    vec3 n = normalize(vNormal);
    if (dot(geomN, geomN) > 1e-8) {
        vec3 gn = normalize(geomN);
        // Для плоских граней (где вершинная нормаль близка к геометрической) фиксируем плоскую нормаль,
        // сохраняя гладкий шейдинг на цилиндрах отверстий
        if (abs(dot(n, gn)) > 0.96) {
            n = (dot(n, gn) >= 0.0) ? gn : -gn;
        }
    }

    vec3 baseColor = uColor;
    // При активном сечении подсвечиваем внутренние стенки распила (!gl_FrontFacing) тёплым древесным тоном
    if (dot(uClipPlane.xyz, uClipPlane.xyz) > 1e-6 && !gl_FrontFacing) {
        baseColor = mix(uColor, vec3(0.92, 0.68, 0.36), 0.42);
        n = -n;
    }

    // Двухточечный асимметричный студийный риг (Key + Fill), привязанный к камере:
    // гарантирует, что любые 3 взаимно перпендикулярные грани детали всегда имеют разный тон
    vec3 keyL = (dot(uKeyDir, uKeyDir) > 1e-4) ? normalize(uKeyDir) : normalize(uLightDir);
    vec3 fillL = (dot(uFillDir, uFillDir) > 1e-4) ? normalize(uFillDir) : normalize(vec3(-uLightDir.x, uLightDir.y * 0.5, -uLightDir.z));
    vec3 viewV = (dot(uViewDir, uViewDir) > 1e-4) ? normalize(uViewDir) : keyL;

    float keyDiff = max(dot(n, keyL), 0.0) + 0.14 * max(dot(-n, keyL), 0.0);
    float fillDiff = max(dot(n, fillL), 0.0) + 0.10 * max(dot(-n, fillL), 0.0);

    vec3 ambient = 0.28 * baseColor;
    vec3 diffuse = (0.62 * keyDiff + 0.16 * fillDiff) * baseColor;

    vec3 halfV = normalize(keyL + viewV);
    float ndh = max(dot(n, halfV), 0.0);
    float spec = pow(ndh, 28.0) * 0.09;

    fragColor = vec4(clamp(ambient + diffuse + vec3(spec), 0.0, 1.0), uAlpha);
}
"""

_LINE_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uMVP;
uniform vec4 uClipPlane;
void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    gl_ClipDistance[0] = dot(vec4(aPos, 1.0), uClipPlane);
}
"""

_LINE_FS = """
#version 330 core
uniform vec3 uColor;
out vec4 fragColor;
void main() {
    fragColor = vec4(uColor, 1.0);
}
"""

_SECTION_MASK_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uMVP;
uniform vec4 uClipPlane;
void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    gl_ClipDistance[0] = dot(vec4(aPos, 1.0), uClipPlane);
}
"""

_SECTION_MASK_FS = """
#version 330 core
void main() {
}
"""

_SECTION_CAP_VS = """
#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 uMVP;
out vec3 vPos;
void main() {
    vPos = aPos;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

_SECTION_CAP_FS = """
#version 330 core
in vec3 vPos;
uniform vec3 uCapColor;
uniform vec3 uHatchColor;
uniform vec3 uCapNormal;
uniform vec3 uHatchAxisU;
uniform vec3 uHatchAxisV;
uniform vec2 uHatchDir;
uniform float uHatchSpacing;
uniform vec3 uKeyDir;
uniform vec3 uFillDir;
out vec4 fragColor;
void main() {
    // Мировые 2D-координаты на плоскости сечения (мм)
    vec2 uv = vec2(dot(vPos, uHatchAxisU), dot(vPos, uHatchAxisV));
    float spacing = max(uHatchSpacing, 1.0);
    float coord = dot(uv, uHatchDir) / spacing;

    // Аналитический градиент (Евклидов, точнее Manhattan fwidth на диагоналях) + адаптивная октава при отдалении
    float fw = max(length(vec2(dFdx(coord), dFdy(coord))), 1e-4);
    if (fw > 0.38) {
        coord *= 0.5;
        fw *= 0.5;
    }
    float phase = abs(fract(coord) - 0.5);
    float halfWidth = clamp(max(0.16, fw * 0.75), 0.16, 0.34);
    float aa = max(fw * 0.85, 0.015);
    float lineMask = 1.0 - smoothstep(halfWidth - aa, halfWidth + aa, phase);
    float antiMoire = 1.0 - smoothstep(0.45, 0.85, fw);
    float hatch = lineMask * antiMoire;

    vec3 baseColor = mix(uCapColor, uHatchColor, hatch * 0.92);

    // Мягкое студийное освещение среза, согласованное с _SOLID_FS
    vec3 n = normalize(uCapNormal);
    vec3 keyL = (dot(uKeyDir, uKeyDir) > 1e-4) ? normalize(uKeyDir) : normalize(vec3(0.4, 0.9, 0.6));
    vec3 fillL = (dot(uFillDir, uFillDir) > 1e-4) ? normalize(uFillDir) : normalize(vec3(-0.4, 0.3, -0.6));
    float keyDiff = max(dot(n, keyL), 0.0) + 0.18 * max(dot(-n, keyL), 0.0);
    float fillDiff = max(dot(n, fillL), 0.0) + 0.12 * max(dot(-n, fillL), 0.0);
    float shade = 0.42 + 0.46 * keyDiff + 0.14 * fillDiff;

    fragColor = vec4(clamp(baseColor * shade, 0.0, 1.0), 1.0);
}
"""


def _compile_shader(src: str, stype: int) -> int:
    sid = glCreateShader(stype)
    glShaderSource(sid, src)
    glCompileShader(sid)
    if not glGetShaderiv(sid, GL_COMPILE_STATUS):
        log = glGetShaderInfoLog(sid)
        glDeleteShader(sid)
        raise RuntimeError(f"Shader compile error: {log}")
    return sid


def _link_program(vs_src: str, fs_src: str) -> int:
    vs = _compile_shader(vs_src, GL_VERTEX_SHADER)
    fs = _compile_shader(fs_src, GL_FRAGMENT_SHADER)
    prog = glCreateProgram()
    glAttachShader(prog, vs)
    glAttachShader(prog, fs)
    glLinkProgram(prog)
    glDeleteShader(vs)
    glDeleteShader(fs)
    if not glGetProgramiv(prog, GL_LINK_STATUS):
        log = glGetProgramInfoLog(prog)
        glDeleteProgram(prog)
        raise RuntimeError(f"Program link error: {log}")
    return prog


_GPU_ID_SEQ = 1
_GL_ARRAYS_SEQ = 1


class Viewport3D(QOpenGLWidget):
    panel_clicked = pyqtSignal(object)
    coordinates_changed = pyqtSignal(float, float, float)
    fastener_message = pyqtSignal(str)
    scene_structure_changed = pyqtSignal()
    measurement_updated = pyqtSignal(str)
    hole_navigated = pyqtSignal(object, str, str, object)  # (block, kind, owner_uid, panel)
    hole_edit_requested = pyqtSignal(object, str, str, object)  # (block, kind, owner_uid, panel)

    def __init__(self, title="Модель"):
        super().__init__()
        # Core Profile 3.3+ (дополнительно к setDefaultFormat в main)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)
        self.setFormat(fmt)

        self.title = title
        self.blocks: list[Block] = []

        # Параметры камеры
        self.rot_x = 25.0
        self.rot_y = -35.0
        self.zoom = -1800.0
        self.pan_x = -300.0
        self.pan_y = -350.0

        self.is_ortho = False
        self._ortho_blend: float = 0.0
        self._focus_pivot: tuple[float, float, float] | None = None
        self.view_name = "iso"
        # ViewCube (правый верхний угол) + плавная анимация камеры и вращение перетаскиванием куба
        self._viewcube_drawable = None
        self._viewcube_hover: tuple[str, str] | None = None
        self._vc_press_pos: QPoint | None = None
        self._vc_press_hit: tuple[str, str] | None = None
        self._vc_dragging: bool = False
        self._vc_pivot: tuple[float, float, float] | None = None
        self._view_anim: dict | None = None
        self._view_anim_timer = QTimer(self)
        self._view_anim_timer.setInterval(16)
        self._view_anim_timer.timeout.connect(self._on_view_anim_tick)
        self._middle_press_pos: QPoint | None = None
        self._middle_did_drag = False
        self.wireframe_only = False
        # solid | wireframe | xray (прозрачный + серые скрытые рёбра)
        self.display_mode = "solid"
        self.move_step = 50.0
        # Сетка только в 2D-видах (как в Базисе): вкл/выкл и шаг привязки
        self.grid_enabled = True
        self.grid_step = 50.0
        self._grid_cache_key = None
        self._grid_cache_pts = None

        # Пакет 2: Аппаратное 3D-сечение (GL_CLIP_DISTANCE0) и режим «Призраки окружения» (Isolate / Ghost Others)
        self.section_enabled: bool = False
        self.section_axis: str = "Z"
        self.section_ratio: float = 0.5
        self.section_flip: bool = False
        self.section_cap_enabled: bool = True
        self._has_stencil_buffer: bool = False
        self._stencil_checked_fbo: int = -1
        self.ghost_others_mode: bool = False
        self.ghost_alpha: float = 0.18
        self._clip_plane_active: bool = False

        # Пункт 3: Живая подсветка 3D-коллизий в реальном времени
        self.live_collision_mode: bool = True
        self._live_collision_cache_key: tuple | None = None
        self._live_collision_hits: list[tuple[Panel, Panel, tuple[float, float, float, float, float, float], float]] = []
        self._live_colliding_panels: set[Panel] = set()

        # Состояния мыши и рамки выделения
        self.last_mouse_pos = QPoint()
        self.press_pos = QPoint()
        self.is_dragging = False
        self.selecting_rect: QRect | None = None
        self.selection_crossing = False

        # Режим крепежа по стыку
        self.fastener_mode = False
        self.fastener_pick_second = False
        self.fastener_anchor = None
        self.fastener_joint = None
        self.fastener_preview = None
        self.fastener_diameter = 7.0
        self.fastener_depth = 42.0
        # Массив крепежа вдоль стыка + пресет (шаг / отступы)
        self.fastener_count = 3
        self.fastener_margin = 50.0
        self.fastener_pitch: float | None = None  # None = равномерно по count
        self.fastener_preset_id = "confirmat_3"
        self.fastener_preview_points: list | None = None
        self._last_fastener_params: dict | None = None
        self.assoc_preview_point: tuple[float, float, float] | None = None
        # Навигация от отверстия в 3D к стыку / ассоциации
        self._hovered_hole: HoleHit | None = None
        self._active_hole_owner: tuple[object, str, str] | None = None
        self._right_press_pos: QPoint | None = None
        self._right_did_drag: bool = False
        # Магнитная привязка (🧲) при перемещении (G), вставке и растягивании граней/углов
        self.face_snap_enabled = True
        self.drag_face_snap_desc = ""

        # Инструмент «Рулетка / Размерные линии и углы»
        self.measure_mode = False
        self.measure_pt1: np.ndarray | None = None
        self.measure_pt2: np.ndarray | None = None
        self.measure_current_pt: np.ndarray | None = None
        self.measure_target1: MeasureTarget | None = None
        self.measure_current_target: MeasureTarget | None = None
        self.measure_preview_dim: DimensionLine | None = None
        self.measure_preview_angle: DimensionAngle | None = None
        self.measure_snap_info: tuple[np.ndarray, str] | None = None
        self.measure_mouse_pos: tuple[int, int] | None = None
        self.measure_snap_screen_pos: tuple[int, int] | None = None
        self.measure_is_magnetic: bool = False
        self.measure_snap_category: str = "space"
        self.measure_snap_dist_px: float = 0.0
        self.ctrl_held: bool = False
        self.dimensions: list[DimensionLine] = []
        self.angles: list[DimensionAngle] = []

        # Интерактивное перемещение мышкой по базовой точке (G)
        self.drag_mode = False
        self.drag_stage = 0  # 0: выкл, 1: выбор базовой точки на детали, 2: перемещение превью
        # Ctrl+C / Ctrl+V
        self.clipboard: ClipboardPayload | None = None
        self.clipboard_await_anchor = False  # после Ctrl+C ждём клик точки привязки
        self.paste_mode = False  # после Ctrl+V: превью и клик размещения
        self.paste_target_point: np.ndarray | None = None
        self.drag_panel: Panel | None = None
        self.drag_orig_pos: tuple[float, float, float] | None = None
        self.drag_base_point: np.ndarray | None = None
        self.drag_base_desc: str = ""
        self.drag_target_point: np.ndarray | None = None
        self.drag_target_desc: str = ""
        self.drag_hover_point: np.ndarray | None = None
        self.drag_hover_desc: str = ""
        # Фиксация оси при Grab: None | "X" | "Y" | "Z"
        self.drag_axis_lock: str | None = None

        # Растягивание за углы и вытягивание торцов в 3D (Direct Face Push-Pull)
        self.resize_mode = False
        self.resize_panel: Panel | None = None
        self.resize_corner: tuple[int, int, int] | None = None  # (sx,sy,sz) 0=min 1=max
        self.resize_face: tuple[int, int] | None = None  # (axis_idx 0|1|2, side 0=min|1=max)
        self.resize_orig_box: tuple | None = None  # x,y,z,w,h,d
        self.resize_hover_corner: tuple[int, int, int] | None = None
        self.resize_hover_face: tuple[int, int] | None = None
        self.resize_face_snap_desc: str = ""
        self.resize_handle_px = 9.0

        # Core Profile ресурсы
        self._prog_solid = 0
        self._prog_line = 0
        self._prog_section_mask = 0
        self._prog_section_cap = 0
        self._cap_vao = 0
        self._cap_vbo = 0
        self._grid_vao = 0
        self._grid_vbo = 0
        self._grid_count = 0
        self._line_vao = 0
        self._line_vbo = 0
        # stable panel._gpu_id -> {vao, vbo, ebo, count, arrays_token}
        self._panel_gpu: dict[int, dict] = {}
        # Множество _gpu_id панелей текущей сцены для O(1) проверки в _panel_belongs_here
        self._scene_gpu_ids: set[int] = set()
        self._scene_gpu_ids_token: tuple | None = None
        # Батчинг линий кадра по цвету: (r, g, b) -> list[np.ndarray]
        self._line_batch_active: bool = False
        self._line_batches: dict[tuple[float, float, float], list[np.ndarray]] = {}
        # Отложенное удаление GL-объектов (только при текущем контексте в paintGL)
        self._gpu_delete_queue: list[dict] = []
        self._gl_ready = False
        self._mvp = glmath.identity()
        self._view = glmath.identity()
        self._proj = glmath.identity()
        self._vp_size = (0, 0, 1, 1)  # x, y, w, h
        self._light_dir = np.array([0.4, 0.9, 0.6], dtype=np.float32)
        # Core Profile: часто только width=1.0; кэш диапазона из драйвера
        self._line_width_range = (1.0, 1.0)

        self.undo_stack = UndoStack(limit=50)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # Гарантируем привязку SceneController до создания дефолтной сцены
        SceneController.instance()

        # Async B-Rep: когда worker закончил — обновить VBO и перерисовать
        svc = GeometryService.instance()
        svc.panel_geometry_updated.connect(self._on_panel_geometry_updated)
        self.scene_structure_changed.connect(self._rebuild_scene_gpu_ids)

        self._init_default_scene()
        self._rebuild_scene_gpu_ids()

    def _apply_axis_lock(self, delta: np.ndarray) -> np.ndarray:
        """Обнуляет компоненты смещения вне зафиксированной оси (Grab) или вне плоскости 2D-вида."""
        is_ortho = bool(getattr(self, "is_ortho", False))
        n_ax = self._view_plane_normal_axis() if is_ortho else None
        cam_fwd = self._camera_axes()[2] if (is_ortho and n_ax is None) else None
        return glmath.constrain_drag_delta_to_view(
            delta,
            axis_lock=self.drag_axis_lock,
            is_ortho=is_ortho,
            normal_axis=n_ax,
            camera_forward=cam_fwd,
        )

    def _view_plane_axes(self) -> tuple[int, int] | None:
        """Оси плоскости текущего 2D-вида: 0=X, 1=Y, 2=Z."""
        name = getattr(self, "view_name", "iso")
        if name in ("front", "back"):
            return (0, 1)
        if name in ("left", "right"):
            return (2, 1)
        if name in ("top", "bottom"):
            return (0, 2)
        if getattr(self, "is_ortho", False):
            rx = float(getattr(self, "rot_x", 0.0)) % 360.0
            ry = float(getattr(self, "rot_y", 0.0)) % 360.0
            if rx > 180.0:
                rx -= 360.0
            if ry > 180.0:
                ry -= 360.0
            if abs(abs(rx) - 90.0) < 1e-2:
                return (0, 2)
            if abs(rx) < 1e-2:
                if abs(ry) < 1e-2 or abs(abs(ry) - 180.0) < 1e-2:
                    return (0, 1)
                if abs(abs(ry) - 90.0) < 1e-2:
                    return (2, 1)
        return None

    def _view_plane_normal_axis(self) -> int | None:
        axes = self._view_plane_axes()
        if axes is None:
            return None
        return ({0, 1, 2} - set(axes)).pop()

    def _intersect_ray_with_view_plane(self, origin: np.ndarray, direction: np.ndarray) -> np.ndarray | None:
        """Пересечение луча с плоскостью 2D-вида, проходящей через 0."""
        n_ax = self._view_plane_normal_axis()
        if n_ax is None:
            return None
        d = float(direction[n_ax])
        o = np.asarray(origin, dtype=float)
        if abs(d) < 1e-12:
            pt = o.copy()
            pt[n_ax] = 0.0
            return pt
        t = (0.0 - float(o[n_ax])) / d
        return o + t * np.asarray(direction, dtype=float)

    def _visible_plane_bounds(self) -> tuple[float, float, float, float] | None:
        """
        Мировые границы видимой области на плоскости вида (ax_a, ax_b).
        Углы экрана → unproject → пересечение с плоскостью. Сетка покрывает всё окно.
        """
        axes = self._view_plane_axes()
        if axes is None:
            return None
        ax_a, ax_b = axes
        w = max(1, self.width())
        h = max(1, self.height())
        # Небольшой запас за краями, чтобы при панораме не мелькало
        margin = 0.05
        samples = [
            (-margin * w, -margin * h),
            ((1.0 + margin) * w, -margin * h),
            ((1.0 + margin) * w, (1.0 + margin) * h),
            (-margin * w, (1.0 + margin) * h),
            (0.5 * w, 0.5 * h),
        ]
        vals_a = []
        vals_b = []
        for sx, sy in samples:
            origin, direction = self._mouse_ray(int(sx), int(sy))
            pt = self._intersect_ray_with_view_plane(origin, direction)
            if pt is None:
                continue
            vals_a.append(float(pt[ax_a]))
            vals_b.append(float(pt[ax_b]))
        if not vals_a:
            return None
        return min(vals_a), max(vals_a), min(vals_b), max(vals_b)

    def _snap_point_to_grid(self, pt: np.ndarray) -> np.ndarray:
        """Привязка точки к узлам сетки в плоскости 2D-вида. В 3D и при выкл. сетке — без изменений."""
        if not (self.grid_enabled and self.is_ortho):
            return np.asarray(pt, dtype=float)
        axes = self._view_plane_axes()
        if not axes:
            return np.asarray(pt, dtype=float)
        step = max(0.1, float(self.grid_step))
        out = np.asarray(pt, dtype=float).copy()
        for ax in axes:
            out[ax] = round(float(out[ax]) / step) * step
        return out

    def _find_magnetic_snap_point(
        self,
        mx: int,
        my: int,
        exclude_panel: Panel | None = None,
        base_radius: float = 20.0,
    ) -> tuple[np.ndarray | None, str]:
        """Ищет ближайшую к курсору `(mx, my)` магнитную точку привязки (`🧲`) на других деталях сцены.

        Управляется переключателем `self.face_snap_enabled` (кнопка «🧲 Магнит» на верхней панели)
        или временным удержанием клавиши `[Ctrl]`.
        """
        is_ctrl = bool(getattr(self, "ctrl_held", False))
        if not (bool(getattr(self, "face_snap_enabled", True)) or is_ctrl):
            return None, ""

        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp
        snap_radius = 52.0 if is_ctrl else float(base_radius)
        plane = self.current_section_plane()

        best_pt: np.ndarray | None = None
        best_desc = ""
        min_d = snap_radius

        for block in self.blocks:
            for other in block.panels:
                if other is exclude_panel:
                    continue
                if not self._panel_within_screen_radius(other, mx, my, snap_radius, mvp, vp, dpr):
                    continue
                for item in self._collect_panel_snap_points(other, label_prefix=other.name):
                    pt, desc = item[0], item[1]
                    if plane is not None and not glmath.point_passes_clip_plane(
                        float(pt[0]), float(pt[1]), float(pt[2]), plane
                    ):
                        continue
                    try:
                        wx, wy, wz = glmath.project(pt[0], pt[1], pt[2], mvp, vp)
                        if wz < 0.0 or wz > 1.0:
                            continue
                        sx = wx / dpr
                        sy = (vp[3] - wy) / dpr
                        dist = math.hypot(sx - mx, sy - my)
                        if dist < min_d:
                            min_d = dist
                            best_pt = np.asarray(pt, dtype=float).copy()
                            best_desc = desc
                    except Exception as exc:
                        _log.debug("Ошибка проекции точки магнитной привязки: %s", exc)

        if best_pt is not None:
            prefix = "🧲 [Ctrl] " if is_ctrl else "🧲 "
            return best_pt, f"{prefix}{best_desc}"
        return None, ""

    def _check_panel_collisions(self, panel: Panel, vol_eps: float = 0.1) -> list[tuple]:
        """Список (other_panel, volume_mm3) пересечений с panel."""
        hits = []
        for b in self.blocks:
            for p in b.panels:
                if p is panel:
                    continue
                try:
                    vol = CADKernel.check_collision(panel, p)
                except Exception:
                    _log.exception("Ошибка проверки коллизии панелей %s и %s", panel.name, p.name)
                    vol = 0.0
                if vol > vol_eps:
                    hits.append((p, float(vol)))
        return hits

    def _init_default_scene(self):
        from ui.viewcube import pan_for_pivot

        b1 = ParametricCabinet(
            name="Блок1 (Тумба 600)", x=0, y=100, z=0,
            width=600, height=720, depth=560,
            shelves_count=1, has_facade=False, is_upper=False,
            pos_num="1", code="01.00"
        )
        custom_block = Block("Пользовательские панели", "2", "02.00")
        self.blocks.extend([b1, custom_block])
        cx, cy, cz, _r = self._scene_center_and_radius()
        self._focus_pivot = (cx, cy, cz)
        self.pan_x, self.pan_y = pan_for_pivot(self.rot_x, self.rot_y, self._focus_pivot)

    def _focus_reference_point(self) -> tuple[float, float, float]:
        """Опорная 3D-точка для вращения камеры: центр выделенных деталей или центр всей сцены."""
        sel = self.get_selected_panels()
        if sel:
            min_x = min(float(p.x) for p in sel)
            min_y = min(float(p.y) for p in sel)
            min_z = min(float(p.z) for p in sel)
            max_x = max(float(p.x) + float(p.width) for p in sel)
            max_y = max(float(p.y) + float(p.height) for p in sel)
            max_z = max(float(p.z) + float(p.depth) for p in sel)
            return (0.5 * (min_x + max_x), 0.5 * (min_y + max_y), 0.5 * (min_z + max_z))
        if self._focus_pivot is not None:
            scx, scy, scz, srad = self._scene_center_and_radius()
            dist = math.hypot(
                math.hypot(self._focus_pivot[0] - scx, self._focus_pivot[1] - scy),
                self._focus_pivot[2] - scz,
            )
            if dist <= srad * 1.35:
                return self._focus_pivot
        cx, cy, cz, _r = self._scene_center_and_radius()
        return (cx, cy, cz)

    def set_Standard_view(self, view_name: str, *, animate: bool = True):
        from ui.viewcube import pan_for_pivot, pivot_from_pan

        views = {
            "iso":    (25.0, -35.0, False),
            "front":  (0.0, 0.0, True),
            "back":   (0.0, 180.0, True),
            "left":   (0.0, 90.0, True),
            "right":  (0.0, -90.0, True),
            "top":    (90.0, 0.0, True),
            "bottom": (-90.0, 0.0, True),
        }
        if view_name not in views:
            return
        self.view_name = view_name
        rx, ry, ortho = views[view_name]
        if animate:
            self.animate_camera_to(rx, ry, is_ortho=ortho)
        else:
            ref_pt = self._focus_reference_point()
            cur_piv = pivot_from_pan(self.rot_x, self.rot_y, self.pan_x, self.pan_y, ref_pt)
            scx, scy, scz, srad = self._scene_center_and_radius()
            dist = math.hypot(math.hypot(cur_piv[0] - scx, cur_piv[1] - scy), cur_piv[2] - scz)
            piv = cur_piv if dist <= srad * 1.35 else ref_pt
            self._focus_pivot = piv
            self.rot_x, self.rot_y, self.is_ortho = rx, ry, ortho
            self._ortho_blend = 1.0 if ortho else 0.0
            self.pan_x, self.pan_y = pan_for_pivot(rx, ry, piv)
            self.update()

    def animate_camera_to(
        self,
        rot_x: float,
        rot_y: float,
        *,
        is_ortho: bool | None = None,
        pan_x: float | None = None,
        pan_y: float | None = None,
        zoom: float | None = None,
        target_pivot: tuple[float, float, float] | None = None,
        duration_ms: int = 150,
    ) -> None:
        """Плавный перелёт камеры (~150 мс) с удержанием 3D-точки вращения (pivot) и гладким переходом Ortho <-> Perspective."""
        import time as _time

        from ui.viewcube import ANIM_MS, pan_for_pivot, pivot_from_pan

        dur = max(1, int(duration_ms if duration_ms is not None else ANIM_MS))
        rx0, ry0 = float(self.rot_x), float(self.rot_y)
        rx1, ry1 = float(rot_x), float(rot_y)
        ortho1 = bool(self.is_ortho if is_ortho is None else is_ortho)
        ortho_b0 = float(getattr(self, "_ortho_blend", 1.0 if self.is_ortho else 0.0))
        ortho_b1 = 1.0 if ortho1 else 0.0

        ref_pt = self._focus_reference_point()
        # Точка pivot0 даёт точное совпадение с текущими (pan_x, pan_y) при t=0 (без рывка на старте)
        pivot0 = pivot_from_pan(rx0, ry0, float(self.pan_x), float(self.pan_y), ref_pt)

        if target_pivot is not None:
            pivot1 = (float(target_pivot[0]), float(target_pivot[1]), float(target_pivot[2]))
            px1, py1 = pan_for_pivot(rx1, ry1, pivot1)
        elif pan_x is not None or pan_y is not None:
            px1 = float(self.pan_x if pan_x is None else pan_x)
            py1 = float(self.pan_y if pan_y is None else pan_y)
            pivot1 = pivot_from_pan(rx1, ry1, px1, py1, ref_pt)
        else:
            # Смена ракурса без явного pan: вращаемся вокруг текущей 3D-точки взгляда (или центра сцены, если улетели далеко)
            scx, scy, scz, srad = self._scene_center_and_radius()
            dist = math.hypot(math.hypot(pivot0[0] - scx, pivot0[1] - scy), pivot0[2] - scz)
            pivot1 = pivot0 if dist <= srad * 1.35 else ref_pt
            px1, py1 = pan_for_pivot(rx1, ry1, pivot1)

        self._focus_pivot = pivot1
        self._view_anim = {
            "t0": _time.perf_counter(),
            "dur": dur / 1000.0,
            "rx0": rx0,
            "ry0": ry0,
            "rx1": rx1,
            "ry1": ry1,
            "ortho1": ortho1,
            "ob0": ortho_b0,
            "ob1": ortho_b1,
            "piv0": pivot0,
            "piv1": pivot1,
            "px0": float(self.pan_x),
            "py0": float(self.pan_y),
            "pz0": float(self.zoom),
            "px1": px1,
            "py1": py1,
            "pz1": float(self.zoom if zoom is None else zoom),
        }
        if not self._view_anim_timer.isActive():
            self._view_anim_timer.start()

    def _on_view_anim_tick(self) -> None:
        import time as _time

        from ui.viewcube import pan_for_pivot

        anim = self._view_anim
        if not anim:
            self._view_anim_timer.stop()
            return
        t = (_time.perf_counter() - anim["t0"]) / max(anim["dur"], 1e-6)
        if t >= 1.0:
            self.rot_x = anim["rx1"]
            self.rot_y = anim["ry1"]
            self.is_ortho = anim["ortho1"]
            self._ortho_blend = anim["ob1"]
            self.pan_x = anim["px1"]
            self.pan_y = anim["py1"]
            self.zoom = anim["pz1"]
            self._view_anim = None
            self._view_anim_timer.stop()
            self.update()
            return
        # smoothstep
        u = t * t * (3.0 - 2.0 * t)
        self.rot_x = anim["rx0"] + (anim["rx1"] - anim["rx0"]) * u
        # кратчайший путь по yaw
        d_ry = anim["ry1"] - anim["ry0"]
        while d_ry > 180.0:
            d_ry -= 360.0
        while d_ry < -180.0:
            d_ry += 360.0
        self.rot_y = anim["ry0"] + d_ry * u

        # Удерживаем 3D-точку вращения (piv_u) в центре экрана на каждом шаге дуги поворота
        p0 = anim["piv0"]
        p1 = anim["piv1"]
        piv_u = (
            p0[0] + (p1[0] - p0[0]) * u,
            p0[1] + (p1[1] - p0[1]) * u,
            p0[2] + (p1[2] - p0[2]) * u,
        )
        self.pan_x, self.pan_y = pan_for_pivot(self.rot_x, self.rot_y, piv_u)
        self.zoom = anim["pz0"] + (anim["pz1"] - anim["pz0"]) * u
        self._ortho_blend = anim["ob0"] + (anim["ob1"] - anim["ob0"]) * u
        self.is_ortho = self._ortho_blend >= 0.5
        self.update()

    def go_home_view(self, *, animate: bool = True) -> None:
        """Изометрия + точный автофокус по 3D-центру и габариту сцены."""
        from ui.viewcube import pan_for_pivot

        cx, cy, cz, radius = self._scene_center_and_radius()
        piv = (float(cx), float(cy), float(cz))
        self._focus_pivot = piv
        zoom = -max(800.0, float(radius) * 2.35)
        if animate:
            self.view_name = "iso"
            self.animate_camera_to(25.0, -35.0, is_ortho=False, target_pivot=piv, zoom=zoom)
        else:
            self.view_name = "iso"
            self.rot_x, self.rot_y, self.is_ortho = 25.0, -35.0, False
            self._ortho_blend = 0.0
            self.pan_x, self.pan_y = pan_for_pivot(25.0, -35.0, piv)
            self.zoom = zoom
            self.update()

    def _scene_center_and_radius(self) -> tuple[float, float, float, float]:
        """Точный 3D-центр и радиус охватывающей сферы по габаритным боксам всех видимых панелей."""
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        found = False
        for b in getattr(self, "blocks", ()) or []:
            for p in getattr(b, "panels", ()) or []:
                if not getattr(p, "visible", True):
                    continue
                found = True
                x0, y0, z0 = float(p.x), float(p.y), float(p.z)
                x1 = x0 + float(p.width)
                y1 = y0 + float(p.height)
                z1 = z0 + float(p.depth)
                min_x = min(min_x, x0, x1)
                min_y = min(min_y, y0, y1)
                min_z = min(min_z, z0, z1)
                max_x = max(max_x, x0, x1)
                max_y = max(max_y, y0, y1)
                max_z = max(max_z, z0, z1)
        if not found:
            return 300.0, 350.0, 280.0, 800.0
        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)
        cz = 0.5 * (min_z + max_z)
        radius = 0.5 * math.hypot(math.hypot(max_x - min_x, max_y - min_y), max_z - min_z)
        return cx, cy, cz, max(radius, 350.0)

    @staticmethod
    def _panel_gpu_key(panel) -> int:
        """Стабильный ключ GPU-кэша (не id(), который переиспользуется GC)."""
        global _GPU_ID_SEQ
        gid = getattr(panel, "_gpu_id", None)
        if gid is None:
            gid = _GPU_ID_SEQ
            _GPU_ID_SEQ += 1
            try:
                panel._gpu_id = gid
            except Exception as exc:
                _log.debug("Не удалось сохранить _gpu_id на объекте панели: %s", exc)
        return int(gid)

    def _queue_gl_delete(self, entry: dict) -> None:
        """Кладёт VAO/VBO/EBO в очередь; реальное glDelete — в paintGL с контекстом."""
        if not entry:
            return
        self._gpu_delete_queue.append({
            "vao": entry.get("vao") or 0,
            "vbo": entry.get("vbo") or 0,
            "ebo": entry.get("ebo") or 0,
        })

    def _flush_gpu_deletes(self) -> None:
        """Удаляет накопленные GL-буферы. Вызывать только при текущем GL-контексте."""
        if not self._gpu_delete_queue:
            return
        queue = self._gpu_delete_queue
        self._gpu_delete_queue = []
        for entry in queue:
            try:
                vao = int(entry.get("vao") or 0)
                vbo = int(entry.get("vbo") or 0)
                ebo = int(entry.get("ebo") or 0)
                if vao:
                    glDeleteVertexArrays(1, [vao])
                if vbo:
                    glDeleteBuffers(1, [vbo])
                if ebo:
                    glDeleteBuffers(1, [ebo])
            except Exception:
                _log.exception("glDelete of panel GPU buffers failed")

    def _free_panel_gpu(self, p_or_id) -> None:
        """Снимает запись из кэша и ставит буферы в очередь на удаление."""
        if isinstance(p_or_id, int):
            key = p_or_id
        else:
            key = self._panel_gpu_key(p_or_id)
        entry = self._panel_gpu.pop(key, None)
        if entry is not None:
            self._queue_gl_delete(entry)

    def _free_all_panel_gpu(self) -> None:
        """Освобождает все панельные GPU-ресурсы этого вьюпорта."""
        for key in list(self._panel_gpu.keys()):
            entry = self._panel_gpu.pop(key, None)
            if entry is not None:
                self._queue_gl_delete(entry)
        # Попробуем удалить сразу, если контекст уже есть
        if self._gl_ready:
            try:
                self.makeCurrent()
                self._flush_gpu_deletes()
                self.doneCurrent()
            except Exception as exc:
                _log.debug("Контекст GL недоступен при немедленном освобождении GPU-буферов: %s", exc)

    def _compute_scene_blocks_token(self) -> tuple:
        blocks = getattr(self, "blocks", None) or ()
        return tuple(
            (
                id(b),
                tuple(id(p) for p in (getattr(b, "panels", None) or ())),
            )
            for b in blocks
        )

    def _rebuild_scene_gpu_ids(self) -> set[int]:
        """Обновляет множество _gpu_id всех панелей сцены."""
        live: set[int] = set()
        for block in getattr(self, "blocks", None) or ():
            for p in getattr(block, "panels", None) or ():
                live.add(self._panel_gpu_key(p))
        self._scene_gpu_ids = live
        self._scene_gpu_ids_token = self._compute_scene_blocks_token()
        return live

    def _reconcile_panel_gpu(self) -> None:
        """Удаляет GPU-записи панелей, которых больше нет в сцене (undo add и т.п.)."""
        live = self._rebuild_scene_gpu_ids()
        for key in list(self._panel_gpu.keys()):
            if key not in live:
                entry = self._panel_gpu.pop(key, None)
                if entry is not None:
                    self._queue_gl_delete(entry)

    def _panel_belongs_here(self, panel) -> bool:
        if panel is None:
            return False
        key = self._panel_gpu_key(panel)
        if not hasattr(self, "_scene_gpu_ids"):
            self._rebuild_scene_gpu_ids()
        if key in self._scene_gpu_ids:
            # Быстрая O(1) проверка; если структура блоков менялась без сигнала — сверим токен
            if getattr(self, "_scene_gpu_ids_token", None) == self._compute_scene_blocks_token():
                return True
            return key in self._rebuild_scene_gpu_ids()
        if getattr(self, "_scene_gpu_ids_token", None) != self._compute_scene_blocks_token():
            self._rebuild_scene_gpu_ids()
            return key in self._scene_gpu_ids
        return False

    def _on_panel_geometry_updated(self, panel: Panel):
        """Точная сетка готова — пометить GPU-запись на бесшовное обновление VBO/EBO и перерисовать.

        GeometryService — синглтон: реагируем только на панели своей сцены.
        Не вызываем _free_panel_gpu(), чтобы сохранить действующий VAO/VBO/EBO
        до загрузки нового меша в _upload_panel_gpu() без моргания детали в AABB.
        """
        if panel is None or not self._panel_belongs_here(panel):
            return
        if hasattr(panel, "invalidate_spatial_caches"):
            panel.invalidate_spatial_caches()
        key = self._panel_gpu_key(panel)
        entry = self._panel_gpu.get(key)
        if entry is not None:
            entry["dirty"] = True
        if hasattr(panel, "_gl_arrays") and not getattr(panel, "geometry_pending", False):
            panel._gl_arrays = None
        self.update()

    # ------------------------------------------------------------------ OpenGL
    def initializeGL(self):
        self._gl_ready = True
        glClearColor(1.0, 1.0, 1.0, 1.0)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glEnable(GL_PROGRAM_POINT_SIZE)
        # MSAA если есть
        glEnable(GL_MULTISAMPLE)

        self._prog_solid = _link_program(_SOLID_VS, _SOLID_FS)
        self._prog_line = _link_program(_LINE_VS, _LINE_FS)
        self._prog_section_mask = _link_program(_SECTION_MASK_VS, _SECTION_MASK_FS)
        self._prog_section_cap = _link_program(_SECTION_CAP_VS, _SECTION_CAP_FS)

        # В OpenGL 3.3 Core GL_STENCIL_BITS удалён (GL_INVALID_ENUM), а внутренний FBO
        # QOpenGLWidget привязывается в paintGL — проверяем через GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE
        self._stencil_checked_fbo = -1
        self._detect_stencil_buffer()

        # В Core Profile wide lines не обязательны — обычно [1, 1]
        try:
            rng = glGetFloatv(GL_ALIASED_LINE_WIDTH_RANGE)
            lo = float(rng[0]) if rng is not None else 1.0
            hi = float(rng[1]) if rng is not None else 1.0
            if hi < lo:
                lo, hi = 1.0, 1.0
            self._line_width_range = (max(1.0, lo), max(1.0, hi))
        except Exception as exc:
            _log.debug("Не удалось запросить GL_ALIASED_LINE_WIDTH_RANGE: %s", exc)
            self._line_width_range = (1.0, 1.0)

        # Динамический буфер линий (оси, сетка, контуры, цилиндры, превью)
        self._line_vao = glGenVertexArrays(1)
        self._line_vbo = glGenBuffers(1)
        glBindVertexArray(self._line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._line_vbo)
        glBufferData(GL_ARRAY_BUFFER, 4 * 3 * 4096, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glBindVertexArray(0)

        # Динамический квад заглушки сечения (6 вершин × vec3)
        self._cap_vao = glGenVertexArrays(1)
        self._cap_vbo = glGenBuffers(1)
        glBindVertexArray(self._cap_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._cap_vbo)
        glBufferData(GL_ARRAY_BUFFER, 4 * 3 * 6, None, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glBindVertexArray(0)

    def _detect_stencil_buffer(self) -> bool:
        """Определяет наличие аппаратного stencil-буфера в текущем FBO (OpenGL 3.3 Core).

        В Core 3.3 старый `glGetIntegerv(GL_STENCIL_BITS)` удалён и вызывает `GL_INVALID_ENUM`.
        Кроме того, `QOpenGLWidget` рендерит в собственный FBO, который создаётся/меняется при
        перерисовке и ресайзе — поэтому результат кэшируется по `GL_DRAW_FRAMEBUFFER_BINDING`.
        """
        def _as_int(raw) -> int:
            return int(raw[0]) if hasattr(raw, "__len__") else int(raw)

        def _query_fbo_attachment(attachment: int, pname: int) -> int:
            buf = (ctypes.c_int * 1)(0)
            try:
                res = glGetFramebufferAttachmentParameteriv(
                    GL_DRAW_FRAMEBUFFER, attachment, pname, buf
                )
            except TypeError:
                res = glGetFramebufferAttachmentParameteriv(
                    GL_DRAW_FRAMEBUFFER, attachment, pname
                )
                return _as_int(res)
            val = int(buf[0])
            if val == 0 and res is not None and res is not buf:
                try:
                    val = _as_int(res)
                except (TypeError, ValueError, IndexError) as exc:
                    _log.debug("Не удалось распаковать ответ glGetFramebufferAttachmentParameteriv: %s", exc)
            return val

        def _attachment_stencil_bits(attachment: int) -> int:
            obj_type = _query_fbo_attachment(attachment, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE)
            if obj_type == int(GL_NONE):
                return 0
            return _query_fbo_attachment(attachment, GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE)

        fbo = -1
        try:
            fbo = _as_int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
        except Exception as exc:
            _log.debug("Не удалось запросить GL_DRAW_FRAMEBUFFER_BINDING: %s", exc)

        if fbo >= 0 and fbo == self._stencil_checked_fbo:
            return self._has_stencil_buffer

        sbits = 0
        queried_ok = False
        try:
            if fbo > 0:
                sbits = _attachment_stencil_bits(GL_STENCIL_ATTACHMENT)
                queried_ok = True
                if sbits <= 0:
                    try:
                        sbits = _attachment_stencil_bits(GL_DEPTH_STENCIL_ATTACHMENT)
                    except Exception as exc:
                        _log.debug("Запрос GL_DEPTH_STENCIL_ATTACHMENT FBO=%s отклонён: %s", fbo, exc)
            elif fbo == 0:
                sbits = _attachment_stencil_bits(GL_STENCIL)
                queried_ok = True
        except Exception as exc:
            _log.debug("Не удалось запросить размер stencil-буфера FBO=%s: %s", fbo, exc)

        if sbits <= 0 and not queried_ok:
            # Резервная проверка формата Qt-контекста (если драйвер отклонил запрос FBO)
            try:
                ctx = self.context()
                if ctx is not None and ctx.format().stencilBufferSize() > 0:
                    sbits = int(ctx.format().stencilBufferSize())
                elif self.format().stencilBufferSize() > 0:
                    sbits = int(self.format().stencilBufferSize())
            except Exception as exc:
                _log.debug("Не удалось прочитать stencilBufferSize из QSurfaceFormat: %s", exc)

        self._has_stencil_buffer = sbits > 0
        if fbo >= 0:
            self._stencil_checked_fbo = fbo
        _log.debug(
            "Определение stencil-буфера: FBO=%s, stencil_bits=%s, enabled=%s",
            fbo,
            sbits,
            self._has_stencil_buffer,
        )
        return self._has_stencil_buffer

    def _rotation_matrix(self) -> np.ndarray:
        """Rx * Ry — поворот сцены (world → view без панорамирования)."""
        return glmath.mul(glmath.rotate_x(self.rot_x), glmath.rotate_y(self.rot_y))

    def _camera_axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Возвращает мировые ортонормированные оси камеры `(right, up, forward)`."""
        R3 = self._rotation_matrix()[:3, :3].T
        right = np.asarray(R3 @ np.array([1.0, 0.0, 0.0], dtype=float), dtype=float)
        up = np.asarray(R3 @ np.array([0.0, 1.0, 0.0], dtype=float), dtype=float)
        forward = np.asarray(R3 @ np.array([0.0, 0.0, -1.0], dtype=float), dtype=float)
        out = []
        for vec in (right, up, forward):
            n = float(np.linalg.norm(vec))
            out.append(vec / n if n > 1e-12 else vec)
        return out[0], out[1], out[2]

    @property
    def panels(self) -> list[Panel]:
        """Плоский список всех панелей во всех блоках сцены."""
        return [
            p
            for b in getattr(self, "blocks", ())
            for p in getattr(b, "panels", ())
        ]

    def _scene_bounding_radius(self) -> float:
        """Оценка радиуса охвата сцены вокруг опорной точки камеры для z_near / z_far."""
        blocks = getattr(self, "blocks", None)
        if not blocks:
            return 2000.0
        # Опорная точка на оси взгляда в мировых координатах: R^T @ (-pan_x, -pan_y, 0)
        R3 = self._rotation_matrix()[:3, :3]
        px, py = -float(self.pan_x), -float(self.pan_y)
        cx = float(R3[0, 0]) * px + float(R3[1, 0]) * py
        cy = float(R3[0, 1]) * px + float(R3[1, 1]) * py
        cz = float(R3[0, 2]) * px + float(R3[1, 2]) * py
        max_r = 0.0
        for b in blocks:
            for p in getattr(b, "panels", ()):
                if not getattr(p, "visible", True):
                    continue
                if hasattr(p, "world_aabb"):
                    mn, mx = p.world_aabb()
                    mn_x, mn_y, mn_z = float(mn[0]), float(mn[1]), float(mn[2])
                    mx_x, mx_y, mx_z = float(mx[0]), float(mx[1]), float(mx[2])
                    pcx = 0.5 * (mn_x + mx_x)
                    pcy = 0.5 * (mn_y + mx_y)
                    pcz = 0.5 * (mn_z + mx_z)
                    half_diag = 0.5 * (
                        (mx_x - mn_x) ** 2 + (mx_y - mn_y) ** 2 + (mx_z - mn_z) ** 2
                    ) ** 0.5
                else:
                    w, h, d = float(p.width), float(p.height), float(p.depth)
                    pcx = float(p.x) + w * 0.5
                    pcy = float(p.y) + h * 0.5
                    pcz = float(p.z) + d * 0.5
                    half_diag = 0.5 * (w * w + h * h + d * d) ** 0.5
                dx, dy, dz = pcx - cx, pcy - cy, pcz - cz
                r = (dx * dx + dy * dy + dz * dz) ** 0.5 + half_diag
                if r > max_r:
                    max_r = r
        return max(1000.0, max_r) if max_r > 0.0 else 2000.0

    def _scene_view_depth_bounds(
        self,
        view_matrix,
        is_ortho: bool,
    ) -> tuple[float, float] | None:
        """Точный интервал глубин `[d_min, d_max]` видимой сцены (и активных превью) вдоль оси взгляда."""
        blocks = getattr(self, "blocks", None)
        if not blocks:
            return None
        panels = [
            p
            for b in blocks
            for p in getattr(b, "panels", ()) or ()
            if getattr(p, "visible", True)
        ]
        if not panels:
            return None

        extra_aabbs: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        sx0 = sy0 = sz0 = float("inf")
        sx1 = sy1 = sz1 = float("-inf")
        for p in panels:
            if hasattr(p, "world_aabb"):
                mn, mx = p.world_aabb()
                mn_x, mn_y, mn_z = float(mn[0]), float(mn[1]), float(mn[2])
                mx_x, mx_y, mx_z = float(mx[0]), float(mx[1]), float(mx[2])
            else:
                mn_x, mn_y, mn_z = float(p.x), float(p.y), float(p.z)
                mx_x = mn_x + float(p.width)
                mx_y = mn_y + float(p.height)
                mx_z = mn_z + float(p.depth)
            if mn_x < sx0:
                sx0 = mn_x
            if mn_y < sy0:
                sy0 = mn_y
            if mn_z < sz0:
                sz0 = mn_z
            if mx_x > sx1:
                sx1 = mx_x
            if mx_y > sy1:
                sy1 = mx_y
            if mx_z > sz1:
                sz1 = mx_z

        # Включаем мировые 3D-оси [0..300]^3, если они в пределах 3 м от сцены
        dx_ax = max(0.0, sx0 - 300.0, -sx1)
        dy_ax = max(0.0, sy0 - 300.0, -sy1)
        dz_ax = max(0.0, sz0 - 300.0, -sz1)
        if (dx_ax * dx_ax + dy_ax * dy_ax + dz_ax * dz_ax) <= 3000.0 * 3000.0:
            extra_aabbs.append(((0.0, 0.0, 0.0), (300.0, 300.0, 300.0)))

        # В 2D-ортографии сетка рисуется в плоскости через (0, 0, 0) — не даём ей обрезаться
        if is_ortho and getattr(self, "grid_enabled", False):
            extra_aabbs.append(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))

        # Активный предпросмотр перемещения (G) — включаем смещённый бокс фантома
        if (
            getattr(self, "drag_mode", False)
            and getattr(self, "drag_stage", 0) == 2
            and getattr(self, "drag_panel", None) is not None
            and getattr(self, "drag_base_point", None) is not None
            and getattr(self, "drag_target_point", None) is not None
        ):
            dp = self.drag_panel
            delta = self.drag_target_point - self.drag_base_point
            ddx, ddy, ddz = float(delta[0]), float(delta[1]), float(delta[2])
            if hasattr(dp, "world_aabb"):
                dmn, dmx = dp.world_aabb()
                extra_aabbs.append((
                    (float(dmn[0]) + ddx, float(dmn[1]) + ddy, float(dmn[2]) + ddz),
                    (float(dmx[0]) + ddx, float(dmx[1]) + ddy, float(dmx[2]) + ddz),
                ))

        # Активный предпросмотр вставки (Ctrl+V) и ассоциативной точки
        pt_paste = getattr(self, "paste_target_point", None) if getattr(self, "paste_mode", False) else None
        if pt_paste is not None and len(pt_paste) >= 3:
            pp = (float(pt_paste[0]), float(pt_paste[1]), float(pt_paste[2]))
            extra_aabbs.append((pp, pp))

        pt_assoc = getattr(self, "assoc_preview_point", None)
        if pt_assoc is not None and len(pt_assoc) >= 3:
            pa = (float(pt_assoc[0]), float(pt_assoc[1]), float(pt_assoc[2]))
            extra_aabbs.append((pa, pa))

        return glmath.compute_scene_view_depth_bounds(
            panels, view_matrix, extra_aabbs=extra_aabbs
        )

    def _rebuild_matrices(self, w: int, h: int):
        from ui.viewcube import ORTHO_HALF_TAN, blend_projection_matrices

        aspect = w / max(1, h)
        # Камера: T * Rx * Ry (считаем до проекции, чтобы точно обжать z_near / z_far по глубине сцены)
        self._view = glmath.mul(
            glmath.translate(self.pan_x, self.pan_y, self.zoom),
            self._rotation_matrix(),
        )
        # Если is_ortho переключён напрямую (например, из тулбара/тестов без анимации), синхронизируем _ortho_blend
        if self._view_anim is None:
            self._ortho_blend = 1.0 if self.is_ortho else 0.0

        scene_radius = self._scene_bounding_radius()
        scale = abs(self.zoom) * ORTHO_HALF_TAN
        if self._ortho_blend <= 1e-4:
            depth_bounds = self._scene_view_depth_bounds(self._view, is_ortho=False)
            z_near, z_far = glmath.compute_adaptive_clip_planes(
                self.zoom, False, scene_radius, view_depth_bounds=depth_bounds
            )
            self._proj = glmath.perspective(45.0, aspect, z_near, z_far)
        elif self._ortho_blend >= 1.0 - 1e-4:
            depth_bounds = self._scene_view_depth_bounds(self._view, is_ortho=True)
            z_near, z_far = glmath.compute_adaptive_clip_planes(
                self.zoom, True, scene_radius, view_depth_bounds=depth_bounds
            )
            self._proj = glmath.ortho(
                -scale * aspect, scale * aspect, -scale, scale, z_near, z_far
            )
        else:
            depth_p = self._scene_view_depth_bounds(self._view, is_ortho=False)
            depth_o = self._scene_view_depth_bounds(self._view, is_ortho=True)
            z_near_p, z_far_p = glmath.compute_adaptive_clip_planes(
                self.zoom, False, scene_radius, view_depth_bounds=depth_p
            )
            z_near_o, z_far_o = glmath.compute_adaptive_clip_planes(
                self.zoom, True, scene_radius, view_depth_bounds=depth_o
            )
            proj_p = glmath.perspective(45.0, aspect, z_near_p, z_far_p)
            proj_o = glmath.ortho(
                -scale * aspect, scale * aspect, -scale, scale, z_near_o, z_far_o
            )
            self._proj = blend_projection_matrices(proj_p, proj_o, self._ortho_blend, self.zoom)

        self._mvp = glmath.mul(self._proj, self._view)
        self._vp_size = (0, 0, max(1, w), max(1, h))

    def _sync_viewport_matrices(self):
        """Актуальные MVP под текущий размер виджета (для пикинга/зума вне paintGL)."""
        w, h = max(1, self.width()), max(1, self.height())
        dpr = float(self.devicePixelRatioF())
        pw, ph = int(w * dpr), int(h * dpr)
        self._rebuild_matrices(pw, ph)
        self._vp_size = (0, 0, pw, ph)

    def _pan_speed_per_pixel(self) -> float:
        """Скорость панорамы: 1 px мыши ≈ 1 px сцены на текущем зуме."""
        from ui.viewcube import ORTHO_HALF_TAN

        h = max(1, self.height())
        view_h = abs(self.zoom) * 2.0 * ORTHO_HALF_TAN
        return view_h / h

    def _cursor_focus_point(self, mx: int, my: int) -> np.ndarray:
        """Точная 3D-точка под курсором для фокуса по СКМ: сначала проверяем пересечение луча
        с видимыми деталями сцены, а при клике в пустой фон — плоскость через опорный центр сцены.
        """
        origin, direction = self._mouse_ray(mx, my)
        plane = self.current_section_plane()
        focus_set = self._get_focus_panels_set() if self.ghost_others_mode else set()
        has_ghosts = bool(self.ghost_others_mode and focus_set)

        min_t_opaque = float("inf")
        min_t_ghost = float("inf")
        for block in getattr(self, "blocks", ()) or []:
            for p in getattr(block, "panels", ()) or []:
                if not getattr(p, "visible", True):
                    continue
                t_hit = self._intersect_ray_panel(origin, direction, p)
                if t_hit is None:
                    continue
                hit_pt = origin + t_hit * direction
                if plane is not None and not glmath.point_passes_clip_plane(
                    float(hit_pt[0]), float(hit_pt[1]), float(hit_pt[2]), plane
                ):
                    continue
                if has_ghosts and p not in focus_set:
                    if t_hit < min_t_ghost:
                        min_t_ghost = t_hit
                else:
                    if t_hit < min_t_opaque:
                        min_t_opaque = t_hit

        best_t = min_t_opaque if math.isfinite(min_t_opaque) else min_t_ghost
        if math.isfinite(best_t):
            return origin + best_t * direction

        R = self._rotation_matrix()
        # В view space камера смотрит −Z; в world: Rᵀ * (0,0,−1)
        forward = R[:3, :3].T @ np.array([0.0, 0.0, -1.0], dtype=float)
        fn = float(np.linalg.norm(forward))
        if fn > 1e-12:
            forward = forward / fn
        rx, ry, rz = self._focus_reference_point()
        focus = np.array([rx, ry, rz], dtype=float)
        denom = float(np.dot(direction, forward))
        if abs(denom) < 1e-8:
            return origin + direction * max(abs(self.zoom), 100.0)
        t = float(np.dot(focus - origin, forward)) / denom
        if t < 10.0:
            t = max(abs(self.zoom), 100.0)
        return origin + direction * t

    def resizeGL(self, w, h):
        glViewport(0, 0, w, max(1, h))
        self._rebuild_matrices(w, max(1, h))

    def paintGL(self):
        # Контекст текущий — безопасно чистим отложенные VAO/VBO и осиротевшие записи
        self._reconcile_panel_gpu()
        self._flush_gpu_deletes()

        w, h = max(1, self.width()), max(1, self.height())
        # devicePixelRatio для HiDPI
        dpr = float(self.devicePixelRatioF())
        glViewport(0, 0, int(w * dpr), int(h * dpr))
        self._rebuild_matrices(int(w * dpr), int(h * dpr))
        # для unproject/project используем logical? Win coords in Qt are logical;
        # glViewport is physical. Store physical viewport, convert mouse with dpr.
        self._vp_size = (0, 0, int(w * dpr), int(h * dpr))

        # Сброс состояния GL после QPainter оверлея / предыдущих проходов
        glFrontFace(GL_CCW)
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
        glDepthMask(GL_TRUE)
        glStencilMask(0xFF)
        glDisable(GL_SCISSOR_TEST)
        glDisable(GL_STENCIL_TEST)
        glDisable(GL_BLEND)
        glDisable(GL_CULL_FACE)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glClearColor(1.0, 1.0, 1.0, 1.0)
        glClearStencil(0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        self._detect_stencil_buffer()

        self.draw_grid()
        self.draw_axes()

        # Активируем аппаратную плоскость сечения GL_CLIP_DISTANCE0 для геометрии деталей
        if self.section_enabled:
            glEnable(GL_CLIP_DISTANCE0)
            self._clip_plane_active = True
        else:
            glDisable(GL_CLIP_DISTANCE0)
            self._clip_plane_active = False

        # Обновляем быстрый список живых 3D-коллизий по текущим позам панелей
        if self.live_collision_mode:
            self._refresh_live_collisions()
        else:
            self._live_collision_hits = []
            self._live_colliding_panels = set()

        if self.display_mode == "xray":
            self._draw_scene_xray()
        else:
            focus_set = self._get_focus_panels_set() if self.ghost_others_mode else set()
            has_ghosts = bool(self.ghost_others_mode and focus_set)

            if self.display_mode == "solid" and not self.wireframe_only:
                glDepthMask(GL_TRUE)
                glDepthFunc(GL_LESS)
                glDisable(GL_BLEND)
                opaque_panels: list[tuple[Panel, bool]] = []
                # 1-й проход: непрозрачные (фокусные или все) панели
                for block in self.blocks:
                    for panel in block.panels:
                        if has_ghosts and panel not in focus_set:
                            continue
                        is_selected = panel.selected or block.selected
                        self._draw_panel_solid(panel, is_selected, alpha=1.0)
                        opaque_panels.append((panel, is_selected))

                # 1.5-й проход: «мясистая» stencil-заглушка среза с индивидуальной штриховкой каждой детали
                if (
                    self.section_enabled
                    and self.section_cap_enabled
                    and self._has_stencil_buffer
                    and opaque_panels
                ):
                    self._draw_section_caps(opaque_panels)

                # 2-й проход: полупрозрачные «призраки окружения» без записи в буфер глубины
                if has_ghosts:
                    glEnable(GL_BLEND)
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                    glDepthMask(GL_FALSE)
                    for block in self.blocks:
                        for panel in block.panels:
                            if panel in focus_set:
                                continue
                            self._draw_panel_solid(panel, False, alpha=self.ghost_alpha)
                    glDepthMask(GL_TRUE)
                    glDisable(GL_BLEND)

            glDepthFunc(GL_LEQUAL)
            self._begin_line_batch()
            try:
                colliding_set = self._live_colliding_panels
                for block in self.blocks:
                    for panel in block.panels:
                        if has_ghosts and panel not in focus_set:
                            self._draw_panel_edges(panel, (0.72, 0.75, 0.80), include_features=False)
                        else:
                            is_selected = panel.selected or block.selected
                            if panel in colliding_set:
                                color = (0.98, 0.08, 0.16)
                            elif is_selected:
                                color = (0.95, 0.1, 0.1)
                            else:
                                color = (0.15, 0.15, 0.15)
                            self._draw_panel_edges(panel, color, include_features=True)
            finally:
                self._flush_line_batch()
            glDepthFunc(GL_LESS)

        # Отключаем клиппинг для вспомогательных гизмо, превью крепежа и размерных линий
        glDisable(GL_CLIP_DISTANCE0)
        self._clip_plane_active = False

        if self.section_enabled:
            self._draw_section_plane_gizmo()

        if self.live_collision_mode and self._live_collision_hits:
            self._draw_live_collision_zones()

        if self.fastener_mode and self.fastener_joint is not None:
            self._draw_joint_and_preview()

        if self.assoc_preview_point is not None:
            self._draw_assoc_preview()

        if self._hovered_hole is not None or self._active_hole_owner is not None:
            self._draw_highlighted_holes()

        self._draw_dimensions()

        if self.paste_mode:
            self._draw_paste_preview()
        if self.drag_mode:
            self._draw_drag_preview()

        glBindVertexArray(0)
        glUseProgram(0)
        glDepthMask(GL_TRUE)
        glDepthFunc(GL_LESS)
        glDisable(GL_BLEND)

    def _set_line_color(self, r, g, b):
        loc = glGetUniformLocation(self._prog_line, "uColor")
        glUniform3f(loc, float(r), float(g), float(b))

    def _begin_line_batch(self) -> None:
        """Включает накопление сегментов GL_LINES по цвету для пакетной отрисовки."""
        self._line_batch_active = True
        self._line_batches = {}

    def _flush_line_batch(self) -> None:
        """Отправляет накопленные линии в GPU одним вызовом glBufferData+glDrawArrays на цвет."""
        batches = getattr(self, "_line_batches", None)
        self._line_batch_active = False
        self._line_batches = {}
        if not batches:
            return
        for color_key, chunks in batches.items():
            if not chunks:
                continue
            merged = chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)
            self._draw_lines_immediate(merged, color_key)

    def _draw_lines_immediate(self, arr: np.ndarray, color) -> None:
        """Непосредственная отрисовка массива сегментов GL_LINES (N, 3) float32."""
        if arr is None or len(arr) < 2:
            return
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        glUseProgram(self._prog_line)
        mvp_loc = glGetUniformLocation(self._prog_line, "uMVP")
        glUniformMatrix4fv(mvp_loc, 1, GL_TRUE, self._mvp)  # row-major upload
        self._apply_clip_plane_uniform(self._prog_line)
        self._set_line_color(*color)
        # Единственное гарантированное значение в Core Profile
        try:
            glLineWidth(1.0)
        except Exception as exc:
            # На некоторых драйверах Core Profile glLineWidth может генерировать ошибку
            _log.debug("Вызов glLineWidth(1.0) отклонён драйвером GL: %s", exc)
        glBindVertexArray(self._line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._line_vbo)
        glBufferData(GL_ARRAY_BUFFER, arr.nbytes, arr, GL_DYNAMIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glDrawArrays(GL_LINES, 0, len(arr))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)
        glUseProgram(0)

    def _draw_lines(self, pts: np.ndarray, color, width: float = 1.0):
        """pts: (N,3) float32, N чётное для GL_LINES.

        При активном батчинге складывает сегменты в буфер по цвету;
        иначе рисует немедленно.
        """
        if pts is None or len(pts) < 2:
            return
        arr = np.ascontiguousarray(pts, dtype=np.float32).reshape(-1, 3)
        if getattr(self, "_line_batch_active", False):
            ckey = (round(float(color[0]), 4), round(float(color[1]), 4), round(float(color[2]), 4))
            self._line_batches.setdefault(ckey, []).append(arr)
            return
        self._draw_lines_immediate(arr, color)

    def draw_axes(self):
        pts = np.array([
            [0, 0, 0], [300, 0, 0],
            [0, 0, 0], [0, 300, 0],
            [0, 0, 0], [0, 0, 300],
        ], dtype=np.float32)
        # три цвета — три вызова
        self._draw_lines(pts[0:2], (0.9, 0.1, 0.1), 2.5)
        self._draw_lines(pts[2:4], (0.1, 0.8, 0.1), 2.5)
        self._draw_lines(pts[4:6], (0.1, 0.3, 0.9), 2.5)

    def _grid_pixels_per_step(self, step: float) -> float:
        """Сколько пикселей экрана приходится на один шаг сетки (по высоте вида)."""
        h = max(1, self.height())
        view_h = abs(float(self.zoom)) * 0.9  # ±scale, scale=|z|*0.45
        if view_h < 1e-6:
            return 1e6
        return float(step) * h / view_h

    def _build_view_grid_pts(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """
        «Бесконечная» сетка: покрывает весь видимый экран (углы → плоскость вида).
        Линии всегда k * grid_step через начало координат.
        LOD: если шаг мельче ~4–8 px — рисуем каждый N-й узел; если < 2 px — не рисуем.
        """
        axes = self._view_plane_axes()
        if axes is None:
            return None, None
        bounds = self._visible_plane_bounds()
        if bounds is None:
            return None, None
        lo_a, hi_a, lo_b, hi_b = bounds
        ax_a, ax_b = axes
        step = max(0.1, float(self.grid_step))

        px = self._grid_pixels_per_step(step)
        # Слишком мелко — рябь, сетку не показываем
        if px < 2.0:
            return None, None

        # Подбираем кратный шаг, чтобы линии были ≥ ~7 px
        min_px = 7.0
        if px >= min_px:
            mult = 1
        else:
            mult = max(1, int(math.ceil(min_px / max(px, 1e-9))))
        draw_step = step * mult

        # После огрубления всё ещё слишком плотно (огромный зум-аут)
        if self._grid_pixels_per_step(draw_step) < 2.0:
            return None, None

        key = (
            self.view_name,
            round(step, 4),
            mult,
            round(lo_a, 0),
            round(hi_a, 0),
            round(lo_b, 0),
            round(hi_b, 0),
            round(float(self.zoom), 1),
        )
        if self._grid_cache_key == key and isinstance(self._grid_cache_pts, tuple):
            return self._grid_cache_pts

        def indices(lo, hi, st):
            i0 = int(math.ceil(lo / st - 1e-12))
            i1 = int(math.floor(hi / st + 1e-12))
            # защита от взрыва
            if i1 - i0 > 4000:
                mid = (i0 + i1) // 2
                half = 2000
                i0, i1 = mid - half, mid + half
            return range(i0, i1 + 1)

        minor: list[float] = []
        major: list[float] = []
        # major ≈ каждые 10 исходных шагов сетки
        major_every = max(1, int(math.ceil(10.0 / mult)))

        def add_line(pts_list, va, axis_const, lo_t, hi_t, axis_t):
            p0 = [0.0, 0.0, 0.0]
            p1 = [0.0, 0.0, 0.0]
            p0[axis_const] = va
            p1[axis_const] = va
            p0[axis_t] = lo_t
            p1[axis_t] = hi_t
            pts_list.extend(p0)
            pts_list.extend(p1)

        for i in indices(lo_a, hi_a, draw_step):
            va = i * draw_step
            bucket = major if (i % major_every == 0) else minor
            add_line(bucket, va, ax_a, lo_b, hi_b, ax_b)
        for j in indices(lo_b, hi_b, draw_step):
            vb = j * draw_step
            bucket = major if (j % major_every == 0) else minor
            add_line(bucket, vb, ax_b, lo_a, hi_a, ax_a)

        minor_arr = np.asarray(minor, dtype=np.float32).reshape(-1, 3) if minor else None
        major_arr = np.asarray(major, dtype=np.float32).reshape(-1, 3) if major else None
        self._grid_cache_key = key
        self._grid_cache_pts = (minor_arr, major_arr)
        return minor_arr, major_arr

    def draw_grid(self):
        """Сетка только в ортогональном виде и только если включена."""
        if not self.is_ortho or not self.grid_enabled:
            return
        minor, major = self._build_view_grid_pts()
        if minor is None and major is None:
            return
        glDisable(GL_DEPTH_TEST)
        if minor is not None and len(minor) >= 2:
            self._draw_lines(minor, (0.88, 0.89, 0.91), 1.0)
        if major is not None and len(major) >= 2:
            self._draw_lines(major, (0.72, 0.74, 0.78), 1.0)
        glEnable(GL_DEPTH_TEST)

    def _ensure_panel_gl_arrays(self, p: Panel):
        """CPU float32 pos/nrm + uint32 indices (сброс в rebuild_geometry)."""
        global _GL_ARRAYS_SEQ
        cache = getattr(p, "_gl_arrays", None)
        if cache is not None and len(cache) == 3 and cache[0] is not None:
            return cache
        if p.mesh_data is None:
            p.rebuild_geometry()
        mesh = p.mesh_data
        if (
            mesh is None
            or len(mesh) < 2
            or mesh[0] is None
            or len(mesh[0]) == 0
            or mesh[1] is None
            or len(mesh[1]) == 0
        ):
            mesh = CADKernel.make_aabb_mesh(
                p.x, p.y, p.z, p.width, p.height, p.depth,
                float(getattr(p, "rx", 0.0)),
                float(getattr(p, "ry", 0.0)),
                float(getattr(p, "rz", 0.0)),
            )
            p.mesh_data = mesh
        if mesh is None or len(mesh) < 2:
            return (None, None, None)
        if len(mesh) == 3:
            verts, tris, normals = mesh
        else:
            verts, tris = mesh
            normals = None
        if verts is None or len(verts) == 0 or tris is None or len(tris) == 0:
            return (None, None, None)
        pos = np.ascontiguousarray(verts, dtype=np.float32)
        tris_arr = np.asarray(tris, dtype=np.int64)
        if normals is not None and len(normals) == len(verts):
            nrm = np.ascontiguousarray(normals, dtype=np.float32)
        else:
            nrm = np.zeros_like(pos)
            if len(tris_arr) > 0:
                v0 = pos[tris_arr[:, 0]]
                v1 = pos[tris_arr[:, 1]]
                v2 = pos[tris_arr[:, 2]]
                fn = np.cross(v1 - v0, v2 - v0)
                fl = np.linalg.norm(fn, axis=1, keepdims=True)
                fn = np.divide(fn, np.maximum(fl, 1e-12))
                np.add.at(nrm, tris_arr[:, 0], fn)
                np.add.at(nrm, tris_arr[:, 1], fn)
                np.add.at(nrm, tris_arr[:, 2], fn)
            lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
            lengths = np.maximum(lengths, 1e-12)
            nrm = np.ascontiguousarray(nrm / lengths, dtype=np.float32)
        idx = np.ascontiguousarray(tris_arr.ravel(), dtype=np.uint32)
        p._gl_arrays = (pos, nrm, idx)
        p._gl_arrays_seq = _GL_ARRAYS_SEQ
        _GL_ARRAYS_SEQ += 1
        return p._gl_arrays

    def _upload_panel_gpu(self, p: Panel):
        """Создаёт/обновляет VAO+VBO+EBO панели. Вершины уже в мировых координатах."""
        key = self._panel_gpu_key(p)
        entry = self._panel_gpu.get(key)
        pending = bool(getattr(p, "geometry_pending", False))
        pose = p.pose_key() if hasattr(p, "pose_key") else None

        # Если идёт пересборка на той же позе и в GPU уже есть готовый меш —
        # удерживаем предыдущий VAO/VBO без мигания в AABB до прихода нового B-Rep меша
        if (
            pending
            and entry is not None
            and entry.get("count", 0) > 0
            and pose is not None
            and entry.get("pose") == pose
        ):
            return entry

        pos, nrm, idx = self._ensure_panel_gl_arrays(p)
        if pos is None or idx is None or len(idx) == 0:
            return entry if (entry is not None and entry.get("count", 0) > 0) else None
        seq = int(getattr(p, "_gl_arrays_seq", 0))
        gen = int(getattr(p, "geometry_generation", 0))
        count = int(idx.size)
        if (
            entry is not None
            and not entry.get("dirty", False)
            and entry.get("seq") == seq
            and entry.get("gen") == gen
            and entry.get("pending") == pending
            and entry.get("count") == count
        ):
            return entry

        # interleaved pos+normal
        interleaved = np.empty((len(pos), 6), dtype=np.float32)
        interleaved[:, 0:3] = pos
        interleaved[:, 3:6] = nrm
        flat = np.ascontiguousarray(interleaved.ravel())

        if entry is None:
            vao = int(glGenVertexArrays(1))
            vbo = int(glGenBuffers(1))
            ebo = int(glGenBuffers(1))
        else:
            vao, vbo, ebo = entry["vao"], entry["vbo"], entry["ebo"]

        glBindVertexArray(vao)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, flat.nbytes, flat, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        entry = {
            "vao": vao, "vbo": vbo, "ebo": ebo,
            "count": count, "token": seq, "seq": seq,
            "gen": gen, "pending": pending,
            "pose": pose, "dirty": False,
        }
        self._panel_gpu[key] = entry
        return entry

    def _draw_panel_solid(self, p: Panel, is_selected: bool = False, alpha: float = 1.0):
        """Заливка панели (VBO). alpha < 1 — полупрозрачность (X-Ray)."""
        if p.mesh_data is None:
            p.rebuild_geometry()
        gpu = self._upload_panel_gpu(p)
        if gpu is None:
            return
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.5, 2.0)
        glUseProgram(self._prog_solid)
        mvp_loc = glGetUniformLocation(self._prog_solid, "uMVP")
        glUniformMatrix4fv(mvp_loc, 1, GL_TRUE, self._mvp)
        is_colliding = self.live_collision_mode and (p in self._live_colliding_panels)
        if is_colliding:
            col = (0.98, 0.42, 0.42) if is_selected else (0.96, 0.54, 0.54)
        elif is_selected:
            col = (0.95, 0.72, 0.68)
        else:
            col = tuple(p.color)
        if getattr(p, "geometry_pending", False):
            col = (col[0] * 0.85 + 0.12, col[1] * 0.85 + 0.12, col[2] * 0.85 + 0.15)
        glUniform3f(glGetUniformLocation(self._prog_solid, "uColor"), *col)
        self._apply_studio_light_uniforms(self._prog_solid)
        self._apply_clip_plane_uniform(self._prog_solid)
        aloc = glGetUniformLocation(self._prog_solid, "uAlpha")
        if aloc >= 0:
            glUniform1f(aloc, float(alpha))
        glBindVertexArray(gpu["vao"])
        glDrawElements(GL_TRIANGLES, gpu["count"], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glUseProgram(0)
        glDisable(GL_POLYGON_OFFSET_FILL)

    def _apply_studio_light_uniforms(self, prog: int):
        """Передаёт в шейдер привязанный к камере студийный свет (Key + Fill + View)."""
        glUniform3f(
            glGetUniformLocation(prog, "uLightDir"),
            float(self._light_dir[0]),
            float(self._light_dir[1]),
            float(self._light_dir[2]),
        )
        key_dir, fill_dir, view_dir = glmath.compute_camera_studio_lights(
            self.rot_x, self.rot_y
        )
        kloc = glGetUniformLocation(prog, "uKeyDir")
        if kloc >= 0:
            glUniform3f(kloc, *key_dir)
        floc = glGetUniformLocation(prog, "uFillDir")
        if floc >= 0:
            glUniform3f(floc, *fill_dir)
        vloc = glGetUniformLocation(prog, "uViewDir")
        if vloc >= 0:
            glUniform3f(vloc, *view_dir)

    # ------------------------------------------------------------------ Пакет 2: Сечение 3D-вида + Призраки окружения
    def current_section_bounds(self) -> tuple[float, float]:
        """Возвращает (min_coord, max_coord) сцены вдоль текущей оси сечения."""
        return glmath.compute_scene_axis_bounds(self.panels, self.section_axis)

    def current_section_offset(self) -> float:
        """Текущая мировая координата плоскости сечения (мм) по `section_ratio` (0..1)."""
        lo, hi = self.current_section_bounds()
        r = min(max(float(self.section_ratio), 0.0), 1.0)
        return float(lo + (hi - lo) * r)

    def current_section_plane(self) -> tuple[float, float, float, float] | None:
        """Возвращает 4D-уравнение плоскости сечения `(A, B, C, D)` или None, если сечение выключено."""
        if not getattr(self, "section_enabled", False):
            return None
        return glmath.compute_section_clip_plane(
            self.section_axis,
            self.current_section_offset(),
            bool(getattr(self, "section_flip", False)),
        )

    def _apply_clip_plane_uniform(self, prog: int, active_override: bool | None = None) -> None:
        """Передаёт `uClipPlane` в шейдер (`prog`). Если клиппинг выключен — `(0, 0, 0, 1)`."""
        cloc = glGetUniformLocation(prog, "uClipPlane")
        if cloc < 0:
            return
        is_active = self._clip_plane_active if active_override is None else bool(active_override)
        plane = self.current_section_plane() if is_active else None
        if plane is not None:
            glUniform4f(cloc, float(plane[0]), float(plane[1]), float(plane[2]), float(plane[3]))
        else:
            glUniform4f(cloc, 0.0, 0.0, 0.0, 1.0)

    def _get_focus_panels_set(self) -> set[Panel]:
        """Возвращает набор фокусных (непрозрачных) деталей для режима «Призраки окружения»."""
        focus: set[Panel] = set()
        for block in self.blocks:
            for p in block.panels:
                if p.selected or block.selected:
                    focus.add(p)
        if self.fastener_anchor is not None:
            focus.add(self.fastener_anchor)
        if self.fastener_joint is not None:
            if getattr(self.fastener_joint, "panel_a", None) is not None:
                focus.add(self.fastener_joint.panel_a)
            if getattr(self.fastener_joint, "panel_b", None) is not None:
                focus.add(self.fastener_joint.panel_b)
        if self.drag_panel is not None:
            focus.add(self.drag_panel)
        return focus

    def _is_panel_ghosted(self, p: Panel, focus_set: set[Panel] | None = None) -> bool:
        """True, если деталь должна рисоваться полупрозрачным призраком и пропускаться при обычном клике."""
        if not getattr(self, "ghost_others_mode", False):
            return False
        fset = self._get_focus_panels_set() if focus_set is None else focus_set
        if not fset:
            return False
        return p not in fset

    def toggle_section_mode(self, enabled: bool | None = None) -> bool:
        """Включает/выключает аппаратное 3D-сечение сцены (`GL_CLIP_DISTANCE0`)."""
        if enabled is None:
            self.section_enabled = not bool(self.section_enabled)
        else:
            self.section_enabled = bool(enabled)
        if self.section_enabled:
            off = self.current_section_offset()
            sign_str = "≥" if self.section_flip else "≤"
            self.fastener_message.emit(
                f"🔪 Сечение ВКЛ: ось {self.section_axis} {sign_str} {off:.0f} мм "
                f"({self.section_ratio * 100:.0f}%) | Alt+колесо — сдвиг плоскости"
            )
        else:
            self.fastener_message.emit("🔪 Сечение ВЫКЛ")
        self.update()
        return self.section_enabled

    def set_section_axis(self, axis: str) -> None:
        """Задаёт ось плоскости сечения ('X', 'Y' или 'Z')."""
        ax = str(axis or "Z").upper().strip()
        if ax not in ("X", "Y", "Z"):
            ax = "Z"
        self.section_axis = ax
        if self.section_enabled:
            off = self.current_section_offset()
            self.fastener_message.emit(
                f"🔪 Ось сечения: {self.section_axis} ({off:.0f} мм, {self.section_ratio * 100:.0f}%)"
            )
        self.update()

    def set_section_ratio(self, ratio: float) -> None:
        """Задаёт положение плоскости сечения в долях габарита сцены (0.0 .. 1.0)."""
        self.section_ratio = min(max(float(ratio), 0.0), 1.0)
        if self.section_enabled:
            off = self.current_section_offset()
            self.fastener_message.emit(
                f"🔪 Плоскость сечения {self.section_axis}: {off:.0f} мм ({self.section_ratio * 100:.0f}%)"
            )
        self.update()

    def flip_section_plane(self) -> bool:
        """Инвертирует направление отсечения (какую половину изделия скрывать)."""
        self.section_flip = not bool(self.section_flip)
        if self.section_enabled:
            off = self.current_section_offset()
            sign_str = "≥" if self.section_flip else "≤"
            self.fastener_message.emit(
                f"🔪 Направление сечения: оставляем {self.section_axis} {sign_str} {off:.0f} мм"
            )
        self.update()
        return self.section_flip

    def toggle_section_cap(self, enabled: bool | None = None) -> bool:
        """Включает/выключает сплошную stencil-заглушку среза со штриховкой деталей."""
        if enabled is None:
            self.section_cap_enabled = not bool(self.section_cap_enabled)
        else:
            self.section_cap_enabled = bool(enabled)
        if self.section_enabled:
            if self.section_cap_enabled and self._gl_ready and not self._has_stencil_buffer:
                self.fastener_message.emit(
                    "▤ Заглушка сечения недоступна: драйвер OpenGL не выделил stencil-буфер (активен полый срез)"
                )
            else:
                state_str = "ВКЛ (штриховка)" if self.section_cap_enabled else "ВЫКЛ (полый срез)"
                self.fastener_message.emit(f"▤ Заглушка сечения: {state_str}")
        self.update()
        return self.section_cap_enabled

    def _draw_section_caps(self, opaque_panels: list[tuple[Panel, bool]]) -> None:
        """Рисует сплошные «мясистые» заглушки сечения по stencil-буферу с индивидуальной штриховкой.

        Двухпроходный алгоритм на каждую разрезанную панель:
        1. Маска (GL_CLIP_DISTANCE0 ВКЛ, DEPTH_TEST ВЫКЛ, COLOR/DEPTH MASK = FALSE):
           задние грани +1 (GL_INCR_WRAP), передние -1 (GL_DECR_WRAP). Внутри материала
           на плоскости среза stencil != 0, а внутри отверстий/пазов — ровно 0.
        2. Заглушка (GL_CLIP_DISTANCE0 ВЫКЛ, DEPTH_TEST LEQUAL, DEPTH_MASK = TRUE,
           CULL_FACE = BACK, STENCIL != 0): рисует квад в плоскости среза с процедурной
           антиалиасинговой штриховкой (fwidth) и записывает точную глубину среза в Z-буфер.
        """
        if (
            not self._prog_section_mask
            or not self._prog_section_cap
            or not self._cap_vao
            or not self._cap_vbo
        ):
            return
        plane = self.current_section_plane()
        if plane is None:
            return

        axis = str(self.section_axis or "Z").upper()
        offset = self.current_section_offset()
        flip = bool(self.section_flip)
        key_dir, fill_dir, _view_dir = glmath.compute_camera_studio_lights(
            self.rot_x, self.rot_y
        )

        # Кэшируем uniform-локации до цикла по панелям
        mask_mvp_loc = glGetUniformLocation(self._prog_section_mask, "uMVP")
        mask_clip_loc = glGetUniformLocation(self._prog_section_mask, "uClipPlane")

        cap_mvp_loc = glGetUniformLocation(self._prog_section_cap, "uMVP")
        cap_color_loc = glGetUniformLocation(self._prog_section_cap, "uCapColor")
        cap_hatch_loc = glGetUniformLocation(self._prog_section_cap, "uHatchColor")
        cap_norm_loc = glGetUniformLocation(self._prog_section_cap, "uCapNormal")
        cap_u_loc = glGetUniformLocation(self._prog_section_cap, "uHatchAxisU")
        cap_v_loc = glGetUniformLocation(self._prog_section_cap, "uHatchAxisV")
        cap_dir_loc = glGetUniformLocation(self._prog_section_cap, "uHatchDir")
        cap_sp_loc = glGetUniformLocation(self._prog_section_cap, "uHatchSpacing")
        cap_key_loc = glGetUniformLocation(self._prog_section_cap, "uKeyDir")
        cap_fill_loc = glGetUniformLocation(self._prog_section_cap, "uFillDir")

        colliding_set = self._live_colliding_panels if self.live_collision_mode else set()

        try:
            glEnable(GL_STENCIL_TEST)
            glDisable(GL_BLEND)
            for idx, (panel, is_selected) in enumerate(opaque_panels):
                if not glmath.panel_intersects_section_plane(panel, axis, offset):
                    continue
                gpu = self._panel_gpu.get(self._panel_gpu_key(panel))
                if gpu is None or not gpu.get("count"):
                    continue

                if hasattr(panel, "world_aabb"):
                    mn, mx = panel.world_aabb()
                else:
                    x0, y0, z0 = float(panel.x), float(panel.y), float(panel.z)
                    mn = (x0, y0, z0)
                    mx = (x0 + float(panel.width), y0 + float(panel.height), z0 + float(panel.depth))

                verts_6, cap_normal, u_axis, v_axis = glmath.compute_section_cap_quad(
                    axis, offset, flip, mn, mx, pad=20.0
                )
                style = glmath.compute_section_cap_style(
                    panel,
                    panel_index=idx,
                    is_selected=is_selected,
                    is_colliding=(panel in colliding_set),
                )

                # --- Проход 1: заполнение stencil-маски для текущей панели ---
                glFrontFace(GL_CCW)
                glStencilMask(0xFF)
                glClearStencil(0)
                glClear(GL_STENCIL_BUFFER_BIT)
                glEnable(GL_CLIP_DISTANCE0)
                glDisable(GL_DEPTH_TEST)
                glDisable(GL_CULL_FACE)
                glDisable(GL_POLYGON_OFFSET_FILL)
                glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
                glDepthMask(GL_FALSE)
                glStencilFunc(GL_ALWAYS, 0, 0xFF)
                glStencilOpSeparate(GL_BACK, GL_KEEP, GL_KEEP, GL_INCR_WRAP)
                glStencilOpSeparate(GL_FRONT, GL_KEEP, GL_KEEP, GL_DECR_WRAP)

                glUseProgram(self._prog_section_mask)
                glUniformMatrix4fv(mask_mvp_loc, 1, GL_TRUE, self._mvp)
                glUniform4f(
                    mask_clip_loc,
                    float(plane[0]),
                    float(plane[1]),
                    float(plane[2]),
                    float(plane[3]),
                )
                glBindVertexArray(gpu["vao"])
                glDrawElements(GL_TRIANGLES, gpu["count"], GL_UNSIGNED_INT, None)

                # --- Проход 2: заливка и штриховка заглушки только там, где stencil != 0 ---
                glDisable(GL_CLIP_DISTANCE0)
                glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
                glDepthMask(GL_TRUE)
                glEnable(GL_DEPTH_TEST)
                glDepthFunc(GL_LEQUAL)
                glEnable(GL_CULL_FACE)
                glCullFace(GL_BACK)
                glEnable(GL_POLYGON_OFFSET_FILL)
                glPolygonOffset(1.0, 1.5)
                glStencilMask(0x00)
                glStencilFunc(GL_NOTEQUAL, 0, 0xFF)
                glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP)

                cap_arr = np.ascontiguousarray(verts_6, dtype=np.float32)
                glUseProgram(self._prog_section_cap)
                glUniformMatrix4fv(cap_mvp_loc, 1, GL_TRUE, self._mvp)
                glUniform3f(cap_color_loc, *style["cap_color"])
                glUniform3f(cap_hatch_loc, *style["hatch_color"])
                glUniform3f(cap_norm_loc, *cap_normal)
                glUniform3f(cap_u_loc, *u_axis)
                glUniform3f(cap_v_loc, *v_axis)
                glUniform2f(cap_dir_loc, *style["hatch_dir"])
                glUniform1f(cap_sp_loc, float(style["hatch_spacing_mm"]))
                glUniform3f(cap_key_loc, *key_dir)
                glUniform3f(cap_fill_loc, *fill_dir)

                glBindVertexArray(self._cap_vao)
                glBindBuffer(GL_ARRAY_BUFFER, self._cap_vbo)
                glBufferData(GL_ARRAY_BUFFER, cap_arr.nbytes, cap_arr, GL_DYNAMIC_DRAW)
                glDrawArrays(GL_TRIANGLES, 0, 6)
        finally:
            glDisable(GL_STENCIL_TEST)
            glStencilMask(0xFF)
            glStencilFunc(GL_ALWAYS, 0, 0xFF)
            glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP)
            glDisable(GL_CULL_FACE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDepthMask(GL_TRUE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            if self.section_enabled:
                glEnable(GL_CLIP_DISTANCE0)
            glBindVertexArray(0)
            glUseProgram(0)

    def toggle_ghost_others_mode(self, enabled: bool | None = None) -> bool:
        """Включает/выключает режим «Призраки окружения» (Isolate / Ghost Others)."""
        if enabled is None:
            self.ghost_others_mode = not bool(self.ghost_others_mode)
        else:
            self.ghost_others_mode = bool(enabled)
        if self.ghost_others_mode:
            fset = self._get_focus_panels_set()
            if fset:
                self.fastener_message.emit(
                    f"👁 Призраки окружения ВКЛ: в фокусе деталей — {len(fset)} (остальные прозрачны и пропускают клик)"
                )
            else:
                self.fastener_message.emit(
                    "👁 Призраки окружения ВКЛ: выделите деталь или стык, чтобы приглушить остальные панели"
                )
        else:
            self.fastener_message.emit("👁 Призраки окружения ВЫКЛ")
        self.update()
        return self.ghost_others_mode

    def _draw_section_plane_gizmo(self) -> None:
        """Рисует янтарную габаритную рамку плоскости сечения в 3D."""
        if not self.section_enabled:
            return
        x_lo, x_hi = glmath.compute_scene_axis_bounds(self.panels, "X")
        y_lo, y_hi = glmath.compute_scene_axis_bounds(self.panels, "Y")
        z_lo, z_hi = glmath.compute_scene_axis_bounds(self.panels, "Z")
        pad = 35.0
        x0, x1 = x_lo - pad, x_hi + pad
        y0, y1 = y_lo - pad, y_hi + pad
        z0, z1 = z_lo - pad, z_hi + pad
        off = self.current_section_offset()
        ax = self.section_axis.upper()
        if ax == "X":
            corners = [(off, y0, z0), (off, y1, z0), (off, y1, z1), (off, y0, z1)]
        elif ax == "Y":
            corners = [(x0, off, z0), (x1, off, z0), (x1, off, z1), (x0, off, z1)]
        else:
            corners = [(x0, y0, off), (x1, y0, off), (x1, y1, off), (x0, y1, off)]
        pts = []
        for i in range(4):
            pts.append(corners[i])
            pts.append(corners[(i + 1) % 4])
        self._draw_lines(np.asarray(pts, dtype=np.float32), (0.96, 0.58, 0.08), 1.5)

    def toggle_live_collision_mode(self, enabled: bool | None = None) -> bool:
        """Включает/выключает живую подсветку 3D-коллизий деталей в реальном времени."""
        if enabled is None:
            self.live_collision_mode = not bool(self.live_collision_mode)
        else:
            self.live_collision_mode = bool(enabled)
        self._live_collision_cache_key = None
        if self.live_collision_mode:
            hits = self._refresh_live_collisions()
            if hits:
                self.fastener_message.emit(
                    f"Живые коллизии ВКЛ: обнаружено пересечений — {len(hits)}"
                )
            else:
                self.fastener_message.emit("Живые коллизии ВКЛ: пересечений не обнаружено")
        else:
            self._live_collision_hits = []
            self._live_colliding_panels = set()
            self.fastener_message.emit("Живые коллизии ВЫКЛ")
        self.update()
        return self.live_collision_mode

    def _refresh_live_collisions(self) -> list[tuple[Panel, Panel, tuple[float, float, float, float, float, float], float]]:
        """Мгновенно обновляет список 3D-коллизий при изменении поз панелей (с кэшированием по pose_key)."""
        panels = self.panels
        key = tuple(
            (id(p), p.pose_key() if hasattr(p, "pose_key") else (p.x, p.y, p.z, p.width, p.height, p.depth))
            for p in panels
            if getattr(p, "visible", True)
        )
        if self._live_collision_cache_key == key:
            return self._live_collision_hits
        self._live_collision_cache_key = key
        hits = glmath.find_live_panel_collisions(panels)
        self._live_collision_hits = hits
        colliding: set[Panel] = set()
        for pa, pb, _box, _vol in hits:
            colliding.add(pa)
            colliding.add(pb)
        self._live_colliding_panels = colliding
        return hits

    def _draw_live_collision_zones(self) -> None:
        """Рисует ярко-красные 3D-боксы зон физического врезания деталей с диагональной штриховкой."""
        if not self._live_collision_hits:
            return
        glDisable(GL_DEPTH_TEST)
        pts: list[tuple[float, float, float]] = []
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
            # Диагонали граней для визуальной штриховки объёма коллизии
            (0, 2), (1, 3), (4, 6), (5, 7),
            (0, 5), (1, 4), (2, 7), (3, 6),
        ]
        for _pa, _pb, box, _vol in self._live_collision_hits:
            x, y, z, w, h, d = box
            x2, y2, z2 = x + w, y + h, z + d
            v = [
                (x, y, z), (x2, y, z), (x2, y2, z), (x, y2, z),
                (x, y, z2), (x2, y, z2), (x2, y2, z2), (x, y2, z2),
            ]
            for a, b in edges:
                pts.append(v[a])
                pts.append(v[b])
        if pts:
            self._draw_lines(np.asarray(pts, dtype=np.float32), (0.98, 0.12, 0.20), 2.0)
        glEnable(GL_DEPTH_TEST)

    def _overlay_palette(self) -> tuple[QColor, QColor, QColor, QColor, QColor, QColor]:
        """Возвращает цвета текущей темы программы для 2D-оверлеев вьюпорта:
        ``(bg, border, text, text_dim, accent, warning)``.
        """
        t = current_theme()
        bg = QColor(t.bg_panel)
        bg.setAlpha(242)
        return (
            bg,
            QColor(t.border),
            QColor(t.text),
            QColor(t.text_dim),
            QColor(t.accent),
            QColor(t.warning),
        )

    def _draw_panel_edges(self, p: Panel, color, include_features: bool = True):
        """Контур панели (с учётом поворота) + опционально пазы и отверстия."""
        if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "world_corners"):
            corners = p.world_corners()
            self._draw_oriented_box_wireframe(corners, color, 1.0)
        else:
            self._draw_box_wireframe(p.x, p.y, p.z, p.width, p.height, p.depth, color, 1.0)
        if not include_features:
            return
        # Пазы/отверстия: при повороте переводим локальные точки в мир
        for gx, gy, gz, gw, gh, gd in getattr(p, "grooves", []):
            if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "local_to_world"):
                # Рисуем AABB паза в локали через 8 углов → мир (упрощённо — box по world-aabb паза)
                locals_g = [
                    (gx, gy, gz), (gx+gw, gy, gz), (gx+gw, gy+gh, gz), (gx, gy+gh, gz),
                    (gx, gy, gz+gd), (gx+gw, gy, gz+gd), (gx+gw, gy+gh, gz+gd), (gx, gy+gh, gz+gd),
                ]
                wc = [p.local_to_world(*c) for c in locals_g]
                self._draw_oriented_box_wireframe(wc, color, 1.0)
            else:
                self._draw_box_wireframe(p.x + gx, p.y + gy, p.z + gz, gw, gh, gd, color, 1.0)
        for hole in getattr(p, "holes", []):
            hx, hy, hz, radius, length, axis = hole[:6]
            self._draw_panel_hole_wire(p, hx, hy, hz, radius, length, axis, segs=16, color=color, width=1.0)

    def _draw_scene_xray(self):
        """
        Прозрачный вид со скрытыми рёбрами:
        1) depth-prepass по заливам
        2) скрытые рёбра (за геометрией) — светло-серые
        3) видимые рёбра — тёмно-серые / чёрные
        """
        panels = []
        for block in self.blocks:
            for panel in block.panels:
                panels.append((panel, panel.selected or block.selected))

        try:
            # --- 1. Depth only ---
            glDisable(GL_BLEND)
            glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
            glDepthMask(GL_TRUE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            for p, sel in panels:
                self._draw_panel_solid(p, sel, alpha=1.0)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

            # --- 2. Hidden edges (behind surface) — grey ---
            glDepthFunc(GL_GREATER)
            glDepthMask(GL_FALSE)
            self._begin_line_batch()
            try:
                for p, sel in panels:
                    hidden = (0.90, 0.55, 0.52) if sel else (0.72, 0.72, 0.74)
                    self._draw_panel_edges(p, hidden, include_features=True)
            finally:
                self._flush_line_batch()

            # --- 3. Visible edges — dark ---
            glDepthFunc(GL_LEQUAL)
            self._begin_line_batch()
            try:
                for p, sel in panels:
                    vis = (0.85, 0.15, 0.12) if sel else (0.12, 0.12, 0.14)
                    self._draw_panel_edges(p, vis, include_features=True)
            finally:
                self._flush_line_batch()
        finally:
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            glDisable(GL_BLEND)

    def draw_panel(self, p: Panel, is_selected: bool = False):
        if p.mesh_data is None:
            p.rebuild_geometry()

        # 1. Заливка — VBO/VAO + Phong shader
        if self.display_mode == "solid" and not self.wireframe_only:
            self._draw_panel_solid(p, is_selected, alpha=1.0)

        # 2. Контур AABB + пазы + отверстия
        if is_selected:
            color = (0.95, 0.1, 0.1)
        else:
            color = (0.15, 0.15, 0.15)
        self._draw_panel_edges(p, color, include_features=True)

    def _draw_oriented_box_wireframe(self, corners, color=(0.15, 0.15, 0.15), width=1.2):
        """Рёбра OBB по 8 углам: 0..3 нижнее основание, 4..7 верхнее."""
        if not corners or len(corners) < 8:
            return
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        pts = []
        for a, b in edges:
            pts.append(corners[a])
            pts.append(corners[b])
        self._draw_lines(np.asarray(pts, dtype=np.float32), color, width)

    def _draw_box_wireframe(self, x, y, z, w, h, d, color=(0.15, 0.15, 0.15), width=1.2):
        x2, y2, z2 = x + w, y + h, z + d
        v = [
            (x, y, z), (x2, y, z), (x2, y2, z), (x, y2, z),
            (x, y, z2), (x2, y, z2), (x2, y2, z2), (x, y2, z2)
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        pts = []
        for a, b in edges:
            pts.append(v[a])
            pts.append(v[b])
        self._draw_lines(np.asarray(pts, dtype=np.float32), color, width)

    def _draw_cylinder_wire(self, cx, cy, cz, radius, length, axis, segs=20,
                            color=(0.95, 0.55, 0.05), axis_vec=None, u_vec=None, v_vec=None, width=2.0):
        r = max(float(radius), 0.5)
        L = float(length)
        if L < 1e-6:
            return

        if axis_vec is not None and u_vec is not None and v_vec is not None:
            ax_x, ax_y, ax_z = float(axis_vec[0]), float(axis_vec[1]), float(axis_vec[2])
            ux, uy, uz = float(u_vec[0]), float(u_vec[1]), float(u_vec[2])
            vx, vy, vz = float(v_vec[0]), float(v_vec[1]), float(v_vec[2])

            def circle(t0):
                bx = cx + ax_x * t0
                by = cy + ax_y * t0
                bz = cz + ax_z * t0
                pts = []
                for i in range(segs):
                    ang = 2.0 * math.pi * i / segs
                    ca, sa = math.cos(ang) * r, math.sin(ang) * r
                    pts.append((
                        bx + ux * ca + vx * sa,
                        by + uy * ca + vy * sa,
                        bz + uz * ca + vz * sa,
                    ))
                return pts

            c0 = circle(0.0)
            c1 = circle(L)
            pts = []
            for i in range(segs):
                j = (i + 1) % segs
                pts.append(c0[i])
                pts.append(c0[j])
                pts.append(c1[i])
                pts.append(c1[j])
            step = max(1, segs // 8)
            for i in range(0, segs, step):
                pts.append(c0[i])
                pts.append(c1[i])
            pts.append((cx, cy, cz))
            pts.append((cx + ax_x * L, cy + ax_y * L, cz + ax_z * L))
            self._draw_lines(np.asarray(pts, dtype=np.float32), color, width)
            return

        def circle(t0):
            pts = []
            for i in range(segs):
                ang = 2.0 * math.pi * i / segs
                ca, sa = math.cos(ang), math.sin(ang)
                if axis == "X":
                    pts.append((cx + t0, cy + r * ca, cz + r * sa))
                elif axis == "Y":
                    pts.append((cx + r * ca, cy + t0, cz + r * sa))
                else:
                    pts.append((cx + r * ca, cy + r * sa, cz + t0))
            return pts

        c0 = circle(0.0)
        c1 = circle(L)
        pts = []
        # торцы как LINE_LOOP → пары сегментов
        for i in range(segs):
            j = (i + 1) % segs
            pts.append(c0[i])
            pts.append(c0[j])
            pts.append(c1[i])
            pts.append(c1[j])
        step = max(1, segs // 8)
        for i in range(0, segs, step):
            pts.append(c0[i])
            pts.append(c1[i])
        # ось
        if axis == "X":
            pts.append((cx, cy, cz))
            pts.append((cx + L, cy, cz))
        elif axis == "Y":
            pts.append((cx, cy, cz))
            pts.append((cx, cy + L, cz))
        else:
            pts.append((cx, cy, cz))
            pts.append((cx, cy, cz + L))
        self._draw_lines(np.asarray(pts, dtype=np.float32), color, width)

    def _draw_panel_hole_wire(self, p: Panel, hx: float, hy: float, hz: float, radius: float,
                              length: float, axis: str, segs: int = 20,
                              color=(0.95, 0.55, 0.05), width: float = 2.0,
                              dx: float = 0.0, dy: float = 0.0, dz: float = 0.0):
        """Отрисовка каркаса отверстия с учётом поворота панели (OBB)."""
        if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "local_to_world") and hasattr(p, "rotate_vector"):
            cx, cy, cz = p.local_to_world(hx, hy, hz)
            cx += dx
            cy += dy
            cz += dz
            if axis == "X":
                axis_vec = p.rotate_vector(1.0, 0.0, 0.0)
                u_vec = p.rotate_vector(0.0, 1.0, 0.0)
                v_vec = p.rotate_vector(0.0, 0.0, 1.0)
            elif axis == "Y":
                axis_vec = p.rotate_vector(0.0, 1.0, 0.0)
                u_vec = p.rotate_vector(1.0, 0.0, 0.0)
                v_vec = p.rotate_vector(0.0, 0.0, 1.0)
            else:
                axis_vec = p.rotate_vector(0.0, 0.0, 1.0)
                u_vec = p.rotate_vector(1.0, 0.0, 0.0)
                v_vec = p.rotate_vector(0.0, 1.0, 0.0)
            self._draw_cylinder_wire(
                cx, cy, cz, radius, length, axis, segs=segs, color=color,
                axis_vec=axis_vec, u_vec=u_vec, v_vec=v_vec, width=width,
            )
        else:
            cx, cy, cz = p.x + dx + hx, p.y + dy + hy, p.z + dz + hz
            self._draw_cylinder_wire(cx, cy, cz, radius, length, axis, segs=segs, color=color, width=width)

    def _draw_hole_marker(self, p: Panel, hole: tuple):
        hx, hy, hz, radius, length, axis = hole[:6]
        self._draw_panel_hole_wire(p, hx, hy, hz, radius, length, axis, segs=24,
                                   color=(0.95, 0.55, 0.05), width=2.0)

    def get_selected_panel(self) -> Panel | None:
        for b in self.blocks:
            for p in b.panels:
                if p.selected:
                    return p
        return None

    def get_selected_panels(self) -> list[Panel]:
        out = []
        for b in self.blocks:
            for p in b.panels:
                if p.selected:
                    out.append(p)
        return out

    def begin_fastener_pick(self, anchor_panel, diameter: float = 7.0, depth: float = 42.0) -> str:
        """Старт: первая панель задана, ждём клик по второй."""
        self.stop_fastener_mode()
        self.fastener_anchor = anchor_panel
        self.fastener_pick_second = True
        self.fastener_diameter = diameter
        self.fastener_depth = depth
        for b in self.blocks:
            for p in b.panels:
                p.selected = (p is anchor_panel)
        anchor_panel.selected = True
        self.update()
        return "OK"

    def start_fastener_mode(self, diameter: float = 7.0, depth: float = 42.0) -> str:
        """Включить режим крепежа по стыку. Нужны 2 выделенные панели."""
        panels = self.get_selected_panels()
        if len(panels) < 2:
            if len(panels) == 1:
                return self.begin_fastener_pick(panels[0], diameter, depth)
            return "Выделите панель, затем Ctrl+H и кликните вторую на стыке"
        return self._activate_joint_mode(panels[0], panels[1], diameter, depth)

    def _activate_joint_mode(self, p1, p2, diameter: float = 7.0, depth: float = 42.0) -> str:
        joint = find_joint(p1, p2)
        if joint is None:
            joint = find_joint(p1, p2, tol=3.0)
        if joint is None:
            return "Стык не найден: панели не касаются (зазор > 3 мм)"
        self.fastener_pick_second = False
        self.fastener_anchor = p1
        self.fastener_mode = True
        self.fastener_joint = joint
        self.fastener_diameter = diameter
        self.fastener_depth = depth
        mid_t = 0.5 * (joint.t_min + joint.t_max)
        mid_s = 0.5 * (joint.s_min + joint.s_max)
        self.fastener_preview = joint.origin + mid_t * joint.slide_dir + mid_s * joint.slide_dir2
        self._refresh_fastener_preview_points(center_t=mid_t)
        p1.selected = True
        p2.selected = True
        preset = get_fastener_preset(self.fastener_preset_id)
        label = preset.get("label", f"×{self.fastener_count}")
        self.fastener_message.emit(
            f"Крепёж: {label} | Tab — пресет, колесо — число, мышь — сдвиг, ЛКМ — поставить, Esc — выход"
        )
        self.update()
        return "OK"

    def apply_fastener_preset(self, preset_id: str) -> None:
        """Применяет пресет (диаметр, глубина, count/pitch, отступ) из каталога."""
        preset = get_fastener_preset(preset_id)
        if not preset:
            return
        self.fastener_preset_id = preset_id
        custom = getattr(self, "_last_fastener_params", None)
        if isinstance(custom, dict) and str(preset_id).startswith("confirmat"):
            self.fastener_diameter = float(custom.get("d1", custom.get("diameter", preset["diameter"])))
            self.fastener_depth = float(custom.get("depth", preset["depth"]))
        else:
            self.fastener_diameter = float(preset["diameter"])
            self.fastener_depth = float(preset["depth"])
        self.fastener_margin = float(preset.get("margin") or 50.0)
        self.fastener_pitch = preset.get("pitch")
        if preset.get("count"):
            self.fastener_count = int(preset["count"])
        center_t = None
        if self.fastener_joint is not None and self.fastener_preview is not None:
            rel = self.fastener_preview - self.fastener_joint.origin
            center_t = float(np.dot(rel, self.fastener_joint.slide_dir))
        self._refresh_fastener_preview_points(center_t=center_t)
        self.fastener_message.emit(f"Пресет: {preset['label']}")
        self.update()

    def cycle_fastener_preset(self, direction: int = 1) -> None:
        order = FASTENER_PRESET_ORDER
        try:
            i = order.index(self.fastener_preset_id)
        except ValueError:
            i = 0
        i = (i + direction) % len(order)
        self.apply_fastener_preset(order[i])

    def _refresh_fastener_preview_points(self, center_t: float | None = None) -> None:
        j = self.fastener_joint
        if j is None:
            self.fastener_preview_points = None
            return
        self.fastener_preview_points = joint_array_points(
            j,
            count=self.fastener_count,
            margin=self.fastener_margin,
            diameter=self.fastener_diameter,
            center_t=center_t,
            pitch=self.fastener_pitch,
        )

    def stop_fastener_mode(self):
        self.fastener_mode = False
        self.fastener_pick_second = False
        self.fastener_anchor = None
        self.fastener_joint = None
        self.fastener_preview = None
        self.fastener_preview_points = None
        self.update()

    def set_assoc_preview_point(self, point: tuple[float, float, float] | None) -> None:
        """Показать/скрыть мировую точку превью ассоциации."""
        if point is None:
            self.assoc_preview_point = None
        else:
            self.assoc_preview_point = (float(point[0]), float(point[1]), float(point[2]))
        self.update()

    def _draw_assoc_preview(self) -> None:
        pt = self.assoc_preview_point
        if pt is None:
            return
        try:
            glDisable(GL_DEPTH_TEST)
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            r = 4.0
            # Крест в трёх осях
            lines = np.asarray(
                [
                    [x - r, y, z],
                    [x + r, y, z],
                    [x, y - r, z],
                    [x, y + r, z],
                    [x, y, z - r],
                    [x, y, z + r],
                ],
                dtype=np.float32,
            )
            self._draw_lines(lines[0:2], (0.15, 0.55, 1.0), 2.5)
            self._draw_lines(lines[2:4], (0.15, 0.55, 1.0), 2.5)
            self._draw_lines(lines[4:6], (0.15, 0.55, 1.0), 2.5)
            glEnable(GL_DEPTH_TEST)
        except Exception as exc:
            _log.debug("Превью ассоциативной точки не отрисовано: %s", exc)

    def set_active_hole_owner(self, block, kind: str = "", owner_uid: str = "") -> None:
        """Подсветить в 3D все отверстия выбранного стыка (joint) или ассоциации (assoc)."""
        uid = str(owner_uid or "").strip()
        if block is None or kind not in ("joint", "assoc") or not uid:
            if self._active_hole_owner is not None:
                self._active_hole_owner = None
                self.update()
            return
        new_owner = (block, kind, uid)
        if self._active_hole_owner != new_owner:
            self._active_hole_owner = new_owner
            self.update()

    def _draw_highlighted_holes(self) -> None:
        """Отрисовка 3D-подсветки отверстий выбранного или наведённого стыка/ассоциации."""
        try:
            glDisable(GL_DEPTH_TEST)
            drawn: set[tuple[int, tuple]] = set()

            # 1. Группа отверстий активного владельца (выбранного в доке «Стыки» / «Ассоциации»)
            if self._active_hole_owner is not None:
                blk, kind, uid = self._active_hole_owner
                color = (0.12, 0.62, 1.0) if kind == "assoc" else (1.0, 0.56, 0.06)
                for panel, hole in collect_owner_holes(blk, kind, uid):
                    key = (id(panel), hole[:6])
                    if key in drawn:
                        continue
                    drawn.add(key)
                    hx, hy, hz, radius, length, axis = hole[:6]
                    self._draw_panel_hole_wire(
                        panel, hx, hy, hz, radius, length, axis,
                        segs=24, color=color, width=2.4,
                    )

            # 2. Наведённое курсором отверстие + все отверстия того же стыка/ассоциации
            hit = self._hovered_hole
            if hit is not None:
                if hit.has_owner:
                    grp_color = (0.18, 0.78, 1.0) if hit.kind == "assoc" else (1.0, 0.72, 0.12)
                    for panel, hole in collect_owner_holes(hit.block, hit.kind, hit.owner_uid):
                        hx, hy, hz, radius, length, axis = hole[:6]
                        self._draw_panel_hole_wire(
                            panel, hx, hy, hz, radius, length, axis,
                            segs=24, color=grp_color, width=2.4,
                        )
                # Акцент на самом отверстии под курсором
                spot_color = (
                    (0.25, 0.88, 1.0)
                    if hit.kind == "assoc"
                    else ((1.0, 0.88, 0.20) if hit.kind == "joint" else (0.95, 0.95, 0.95))
                )
                hx, hy, hz, radius, length, axis = hit.hole[:6]
                self._draw_panel_hole_wire(
                    hit.panel, hx, hy, hz, radius, length, axis,
                    segs=28, color=spot_color, width=3.0,
                )

            glEnable(GL_DEPTH_TEST)
        except Exception as exc:
            _log.debug("Подсветка отверстий не отрисована: %s", exc)

    def _draw_hole_hover_overlay(self, painter: QPainter) -> None:
        """Компактная 2D-подсказка рядом с отверстием под курсором в стиле системной темы."""
        hit = self._hovered_hole
        if hit is None or hit.screen_mid is None:
            return
        text = describe_hole_hit(hit, include_hint=False, compact=True)
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()

        stripe_w = 3
        pad_x, pad_y = 7, 3
        bw = tw + pad_x * 2 + stripe_w
        bh = th + pad_y * 2

        sx, sy = hit.screen_mid
        bx = int(sx + 14)
        by = int(sy - bh - 10)
        vw = max(1, self.width())
        vh = max(1, self.height())
        if bx + bw > vw - 8:
            bx = max(8, int(sx - bw - 14))
        if by < 8:
            by = min(vh - bh - 8, int(sy + 16))
        bx = max(8, min(vw - bw - 8, bx))
        by = max(8, min(vh - bh - 8, by))

        bg, border, text_col, _text_dim, theme_accent, theme_warning = self._overlay_palette()
        if hit.kind == "assoc":
            kind_accent = theme_accent
        elif hit.kind == "joint":
            kind_accent = theme_warning
        else:
            kind_accent = border

        rect = QRect(bx, by, bw, bh)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 3, 3)
        painter.fillRect(QRect(bx + 1, by + 2, 2, max(1, bh - 4)), kind_accent)
        painter.setPen(text_col)
        painter.drawText(
            rect.adjusted(pad_x + stripe_w, 0, -pad_x, 0),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _pick_panel_with_depth(self, origin: np.ndarray, ray_dir: np.ndarray) -> tuple[Panel | None, float | None]:
        """Возвращает ближайшую панель под лучом и параметр глубины ``t`` (с учётом плоскости сечения)."""
        plane = self.current_section_plane()
        focus_set = self._get_focus_panels_set() if self.ghost_others_mode else set()
        has_ghosts = bool(self.ghost_others_mode and focus_set)

        closest_opaque = None
        min_t_opaque = float("inf")
        closest_ghost = None
        min_t_ghost = float("inf")

        for block in self.blocks:
            for p in block.panels:
                if not getattr(p, "visible", True):
                    continue
                t_hit = self._intersect_ray_panel(origin, ray_dir, p)
                if t_hit is None:
                    continue
                hit_pt = origin + t_hit * ray_dir
                if plane is not None and not glmath.point_passes_clip_plane(
                    float(hit_pt[0]), float(hit_pt[1]), float(hit_pt[2]), plane
                ):
                    continue
                if has_ghosts and p not in focus_set and not self.fastener_pick_second:
                    if t_hit < min_t_ghost:
                        min_t_ghost = t_hit
                        closest_ghost = p
                else:
                    if t_hit < min_t_opaque:
                        min_t_opaque = t_hit
                        closest_opaque = p

        if closest_opaque is not None:
            return closest_opaque, float(min_t_opaque)
        if closest_ghost is not None:
            return closest_ghost, float(min_t_ghost)
        return None, None

    def pick_hole_at_screen(self, mx: int, my: int, *, max_screen_px: float = 12.0) -> HoleHit | None:
        """Выбирает ближайшее 3D-отверстие под экранной точкой ``(mx, my)``."""
        if not self.blocks:
            return None
        self._sync_viewport_matrices()
        origin, ray_dir = self._mouse_ray(mx, my)
        front_panel, occluded_t = self._pick_panel_with_depth(origin, ray_dir)
        ignore_occlusion = (
            self.display_mode in ("wireframe", "xray")
            or bool(self.wireframe_only)
        )
        return pick_hole_at_ray(
            self.blocks,
            origin,
            ray_dir,
            mvp=self._mvp,
            viewport=self._vp_size,
            mouse_xy=(float(mx), float(my)),
            dpr=float(self.devicePixelRatioF()),
            max_screen_px=max_screen_px,
            section_plane=self.current_section_plane(),
            occluded_t=occluded_t,
            front_panel=front_panel,
            ignore_occlusion=ignore_occlusion,
        )

    def _can_pick_hole_in_current_mode(self) -> bool:
        return not (
            self.drag_mode
            or self.fastener_mode
            or self.fastener_pick_second
            or self.measure_mode
            or self.resize_mode
            or self.paste_mode
            or self.clipboard_await_anchor
        )

    def _update_hole_hover(self, mx: int, my: int) -> None:
        if (
            not self._can_pick_hole_in_current_mode()
            or self._viewcube_hover is not None
            or self.resize_hover_face is not None
            or self.resize_hover_corner is not None
        ):
            if self._hovered_hole is not None:
                self._hovered_hole = None
                self.update()
            return
        try:
            hit = self.pick_hole_at_screen(mx, my)
        except Exception as exc:
            _log.debug("Hole hover pick failed: %s", exc)
            hit = None

        prev = self._hovered_hole
        changed = (
            (prev is None) != (hit is None)
            or (
                prev is not None
                and hit is not None
                and (prev.panel is not hit.panel or prev.hole_index != hit.hole_index)
            )
        )
        if changed:
            self._hovered_hole = hit
            try:
                if hit is not None and hit.has_owner:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                elif self._viewcube_hover is None:
                    self.unsetCursor()
            except Exception as exc:
                _log.debug("Hole hover cursor update failed: %s", exc)
            self.update()

    def _navigate_to_hole_hit(self, hit: HoleHit) -> bool:
        """Переход от 3D-отверстия к породившему стыку, ассоциации или свойствам детали."""
        if hit.has_owner:
            self._active_hole_owner = (hit.block, hit.kind, hit.owner_uid)
        else:
            self._active_hole_owner = None
        self.hole_navigated.emit(hit.block, hit.kind, hit.owner_uid, hit.panel)
        self.update()
        return True

    def _show_hole_context_menu(self, hit: HoleHit, global_pos) -> None:
        """Контекстное меню по короткому ПКМ на 3D-отверстии."""
        menu = QMenu(self)
        title_act = menu.addAction(describe_hole_hit(hit, include_hint=False, compact=False))
        title_act.setEnabled(False)
        menu.addSeparator()

        act_nav = None
        act_edit = None
        if hit.kind == "joint":
            act_nav = menu.addAction("Перейти к стыку в панели «Стыки»")
        elif hit.kind == "assoc":
            act_nav = menu.addAction("Перейти к ассоциации в панели «Ассоциации»")
            act_edit = menu.addAction("Правка ассоциации…")
        else:
            act_nav = menu.addAction("Выбрать деталь и открыть «Свойства»")

        act_focus = menu.addAction("Сфокусировать камеру на отверстии")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_nav:
            self._navigate_to_hole_hit(hit)
        elif act_edit is not None and chosen is act_edit:
            self._active_hole_owner = (hit.block, hit.kind, hit.owner_uid)
            self.hole_edit_requested.emit(hit.block, hit.kind, hit.owner_uid, hit.panel)
            self.update()
        elif chosen is act_focus:
            self.animate_camera_to(
                float(self.rot_x),
                float(self.rot_y),
                is_ortho=self.is_ortho,
                target_pivot=hit.world_mid,
            )
            self.fastener_message.emit(
                f"Фокус на отверстие ({hit.world_mid[0]:.0f}, {hit.world_mid[1]:.0f}, {hit.world_mid[2]:.0f}) мм"
            )

    def _draw_joint_and_preview(self):
        j = self.fastener_joint
        if j is None:
            return
        glDisable(GL_DEPTH_TEST)

        p0 = j.origin + j.t_min * j.slide_dir + 0.5 * (j.s_min + j.s_max) * j.slide_dir2
        p1 = j.origin + j.t_max * j.slide_dir + 0.5 * (j.s_min + j.s_max) * j.slide_dir2
        self._draw_lines(
            np.asarray([p0, p1], dtype=np.float32),
            (0.1, 0.75, 0.3), 3.0,
        )

        pts = self.fastener_preview_points
        if not pts and self.fastener_preview is not None:
            pts = [self.fastener_preview]
        if pts:
            r = max(self.fastener_diameter / 2.0, 1.0)
            axis = j.drill_axis
            depth = float(self.fastener_depth)
            color = (1.0, 0.55, 0.05)
            d_vec = np.asarray(j.drill_dir, dtype=float)
            dn = float(np.linalg.norm(d_vec))
            if dn > 1e-9:
                d_vec = d_vec / dn
                u_vec = np.asarray(j.slide_dir, dtype=float)
                v_vec = np.asarray(j.slide_dir2, dtype=float)
                for c in pts:
                    c = np.asarray(c, dtype=float)
                    start = c - d_vec * depth
                    self._draw_cylinder_wire(
                        float(start[0]), float(start[1]), float(start[2]),
                        r, 2.0 * depth, axis, segs=20, color=color,
                        axis_vec=d_vec, u_vec=u_vec, v_vec=v_vec,
                    )
            else:
                for c in pts:
                    c = np.asarray(c, dtype=float)
                    if axis == "X":
                        self._draw_cylinder_wire(c[0] - depth, c[1], c[2], r, 2.0 * depth, "X",
                                                 segs=20, color=color)
                    elif axis == "Y":
                        self._draw_cylinder_wire(c[0], c[1] - depth, c[2], r, 2.0 * depth, "Y",
                                                 segs=20, color=color)
                    else:
                        self._draw_cylinder_wire(c[0], c[1], c[2] - depth, r, 2.0 * depth, "Z",
                                                 segs=20, color=color)

        glEnable(GL_DEPTH_TEST)

    # ------------------------------------------------------------------ Инструмент «Рулетка / Размерные линии и углы»
    def start_measure_mode(self):
        """Включает режим умной 3D-рулетки (точки, рёбра, грани в свету, отверстия, углы)."""
        self.stop_fastener_mode()
        self.measure_mode = True
        self.measure_pt1 = None
        self.measure_pt2 = None
        self.measure_current_pt = None
        self.measure_target1 = None
        self.measure_current_target = None
        self.measure_preview_dim = None
        self.measure_preview_angle = None
        self.measure_snap_info = None
        self.measure_mouse_pos = None
        self.measure_snap_screen_pos = None
        self.measure_is_magnetic = False
        self.measure_snap_category = "space"
        self.measure_snap_dist_px = 0.0
        self.ctrl_held = False
        self.setCursor(Qt.CursorShape.CrossCursor)
        msg = (
            "Умная 3D-линейка: наведите на грань, отверстие, ребро или угол | "
            "2 грани → в свету / угол | 2 отверстия → шаг | [Ctrl] — магнит | Esc — выход"
        )
        self.measurement_updated.emit(msg)
        self.fastener_message.emit(msg)
        self.update()

    def stop_measure_mode(self):
        """Выключает режим рулетки."""
        self.measure_mode = False
        self.measure_pt1 = None
        self.measure_pt2 = None
        self.measure_current_pt = None
        self.measure_target1 = None
        self.measure_current_target = None
        self.measure_preview_dim = None
        self.measure_preview_angle = None
        self.measure_snap_info = None
        self.measure_mouse_pos = None
        self.measure_snap_screen_pos = None
        self.measure_is_magnetic = False
        self.measure_snap_category = "space"
        self.measure_snap_dist_px = 0.0
        self.ctrl_held = False
        self.unsetCursor()
        self.measurement_updated.emit("")
        self.update()

    def toggle_measure_mode(self) -> bool:
        """Переключает режим рулетки."""
        if self.measure_mode:
            self.stop_measure_mode()
            return False
        else:
            self.start_measure_mode()
            return True

    def clear_dimensions(self):
        """Удаляет все проставленные размерные линии и углы."""
        self.dimensions.clear()
        self.angles.clear()
        self.measure_pt1 = None
        self.measure_pt2 = None
        self.measure_current_pt = None
        self.measure_target1 = None
        self.measure_current_target = None
        self.measure_preview_dim = None
        self.measure_preview_angle = None
        self.measure_snap_info = None
        self.measure_mouse_pos = None
        self.measure_snap_screen_pos = None
        self.measure_is_magnetic = False
        self.measure_snap_category = "space"
        self.measure_snap_dist_px = 0.0
        self.fastener_message.emit("Размерные линии и углы очищены")
        self.measurement_updated.emit("Размерные линии и углы очищены")
        self.update()

    def _collect_panel_snap_points(self, p: Panel, label_prefix: str = "") -> list[tuple]:
        token = p.snap_cache_token(label_prefix) if hasattr(p, "snap_cache_token") else None
        if token is not None and getattr(p, "_snap_cache_key", None) == token:
            cached = getattr(p, "_snap_cache_data", None)
            if cached is not None:
                return cached

        prefix = f"{label_prefix}: " if label_prefix else ""
        candidates: list[tuple] = []
        w, h, d = float(p.width), float(p.height), float(p.depth)
        wm, hm, dm = w * 0.5, h * 0.5, d * 0.5

        def to_world(lx: float, ly: float, lz: float) -> np.ndarray:
            if hasattr(p, "local_to_world"):
                wx, wy, wz = p.local_to_world(lx, ly, lz)
                return np.array([wx, wy, wz], dtype=float)
            return np.array([float(p.x) + lx, float(p.y) + ly, float(p.z) + lz], dtype=float)

        # 8 углов панели (в локальных координатах → мир через local_to_world)
        for lx in (0.0, w):
            for ly in (0.0, h):
                for lz in (0.0, d):
                    candidates.append((to_world(lx, ly, lz), f"{prefix}Угол детали", "corner", p, {}))

        # 12 середин рёбер (с сохранением длины ребра)
        for ly in (0.0, h):
            for lz in (0.0, d):
                candidates.append(
                    (to_world(wm, ly, lz), f"{prefix}Середина ребра ({w:.0f} мм)", "edge_mid", p, {"edge_length": w})
                )
        for lx in (0.0, w):
            for lz in (0.0, d):
                candidates.append(
                    (to_world(lx, hm, lz), f"{prefix}Середина ребра ({h:.0f} мм)", "edge_mid", p, {"edge_length": h})
                )
        for lx in (0.0, w):
            for ly in (0.0, h):
                candidates.append(
                    (to_world(lx, ly, dm), f"{prefix}Середина ребра ({d:.0f} мм)", "edge_mid", p, {"edge_length": d})
                )

        # 6 центров граней
        candidates.append((to_world(wm, hm, 0.0), f"{prefix}Центр задней грани", "face_center", p, {"face_id": "back"}))
        candidates.append((to_world(wm, hm, d), f"{prefix}Центр передней грани", "face_center", p, {"face_id": "front"}))
        candidates.append((to_world(0.0, hm, dm), f"{prefix}Центр левой грани", "face_center", p, {"face_id": "left"}))
        candidates.append((to_world(w, hm, dm), f"{prefix}Центр правой грани", "face_center", p, {"face_id": "right"}))
        candidates.append((to_world(wm, 0.0, dm), f"{prefix}Центр нижней грани", "face_center", p, {"face_id": "bottom"}))
        candidates.append((to_world(wm, h, dm), f"{prefix}Центр верхней грани", "face_center", p, {"face_id": "top"}))

        # Центр детали
        candidates.append((to_world(wm, hm, dm), f"{prefix}Центр детали", "center", p, {}))

        # Отверстия присадки (с метаданными диаметра, глубины и оси)
        for hole in getattr(p, "holes", []):
            hx, hy, hz = float(hole[0]), float(hole[1]), float(hole[2])
            diam = float(hole[3]) * 2.0 if len(hole) > 3 else 8.0
            depth = float(hole[4]) if len(hole) > 4 else 13.0
            candidates.append(
                (
                    to_world(hx, hy, hz),
                    f"{prefix}Отверстие Ø{diam:.1f}×{depth:.0f}",
                    "hole",
                    p,
                    {"hole": hole},
                )
            )

        if token is not None:
            p._snap_cache_key = token
            p._snap_cache_data = candidates
        return candidates

    def _panel_within_screen_radius(
        self,
        p: Panel,
        mx: float,
        my: float,
        radius_px: float,
        mvp: np.ndarray,
        vp: tuple[int, int, int, int],
        dpr: float,
    ) -> bool:
        """Быстрое экранное отсечение по 8 углам бокса (Screen-Space BBox Cull).

        Проецирует 8 мировых углов детали на экран и проверяет, попадает ли курсор `(mx, my)`
        в расширенную на `radius_px` 2D-рамку детали. Если деталь пересекает ближнюю плоскость
        камеры (часть углов позади, часть спереди), консервативно возвращает True.
        """
        if not getattr(p, "visible", True):
            return False
        corners = (
            p.world_corners()
            if hasattr(p, "world_corners")
            else [
                (float(p.x), float(p.y), float(p.z)),
                (float(p.x) + float(p.width), float(p.y), float(p.z)),
                (float(p.x) + float(p.width), float(p.y) + float(p.height), float(p.z)),
                (float(p.x), float(p.y) + float(p.height), float(p.z)),
                (float(p.x), float(p.y), float(p.z) + float(p.depth)),
                (float(p.x) + float(p.width), float(p.y), float(p.z) + float(p.depth)),
                (float(p.x) + float(p.width), float(p.y) + float(p.height), float(p.z) + float(p.depth)),
                (float(p.x), float(p.y) + float(p.height), float(p.z) + float(p.depth)),
            ]
        )
        min_sx = float("inf")
        max_sx = float("-inf")
        min_sy = float("inf")
        max_sy = float("-inf")
        in_front = 0
        behind = 0
        for cx, cy, cz in corners:
            try:
                wx, wy, wz = glmath.project(cx, cy, cz, mvp, vp)
            except Exception:
                return True
            if wz < 0.0:
                behind += 1
                continue
            if wz > 1.0:
                continue
            in_front += 1
            sx = wx / dpr
            sy = (vp[3] - wy) / dpr
            if sx < min_sx:
                min_sx = sx
            if sx > max_sx:
                max_sx = sx
            if sy < min_sy:
                min_sy = sy
            if sy > max_sy:
                max_sy = sy

        if in_front == 0:
            return False
        if behind > 0:
            # Деталь пересекает плоскость камеры вблизи — не отсекаем
            return True

        margin = float(radius_px) + 8.0
        return (
            (min_sx - margin) <= mx <= (max_sx + margin)
            and (min_sy - margin) <= my <= (max_sy + margin)
        )

    def _collect_snap_candidates(
        self,
        mx: float | None = None,
        my: float | None = None,
        radius_px: float = 54.0,
    ) -> list[tuple]:
        candidates = []
        use_cull = mx is not None and my is not None
        dpr = float(self.devicePixelRatioF()) if use_cull else 1.0
        vp = self._vp_size
        mvp = self._mvp
        plane = self.current_section_plane()
        for block in self.blocks:
            for p in block.panels:
                if use_cull and not self._panel_within_screen_radius(
                    p, float(mx), float(my), radius_px, mvp, vp, dpr
                ):
                    continue
                pts = self._collect_panel_snap_points(p, label_prefix=p.name)
                if plane is not None:
                    pts = [
                        item for item in pts
                        if glmath.point_passes_clip_plane(float(item[0][0]), float(item[0][1]), float(item[0][2]), plane)
                    ]
                candidates.extend(pts)
        return candidates

    def _find_nearest_snap_point(self, mx: int, my: int, max_dist_px: float = 24.0, ctrl_boost: bool = False):
        """
        Ищет ближайшую точку привязки (угол, ребро, отверстие, центр) по ВСЕМ деталям сцены без необходимости их выделения.
        Использует Screen-Space BBox Cull по 8 углам бокса перед проверкой отверстий и рёбер.
        При ctrl_boost=True радиус захвата увеличивается до 54px и приоритет отдаётся точным углам/рёбрам/отверстиям.
        Также сохраняет распознанный `MeasureTarget` в `self.measure_current_target`.
        """
        effective_max = 54.0 if ctrl_boost else max_dist_px
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp
        candidates = self._collect_snap_candidates(mx=mx, my=my, radius_px=effective_max)

        best_pt = None
        best_desc = ""
        best_kind = "space"
        best_screen_pt = None
        best_panel = None
        best_meta: dict = {}
        min_screen_dist = effective_max

        for item in candidates:
            pt = item[0]
            desc = item[1]
            kind = item[2] if len(item) > 2 else "point"
            panel = item[3] if len(item) > 3 else None
            meta = item[4] if len(item) > 4 and isinstance(item[4], dict) else {}
            try:
                wx, wy, wz = glmath.project(pt[0], pt[1], pt[2], mvp, vp)
                if wz < 0.0 or wz > 1.0:
                    continue
                sx = wx / dpr
                sy = (vp[3] - wy) / dpr
                dist = math.hypot(sx - mx, sy - my)
                # Если зажат Ctrl, даём приоритет отверстиям, углам и рёбрам
                weighted_dist = dist
                if ctrl_boost and kind in ("corner", "hole"):
                    weighted_dist *= 0.85
                elif ctrl_boost and kind == "edge_mid":
                    weighted_dist *= 0.92

                if weighted_dist < min_screen_dist:
                    min_screen_dist = weighted_dist
                    best_pt = pt
                    best_desc = desc
                    best_kind = kind
                    best_screen_pt = (int(sx), int(sy))
                    best_panel = panel
                    best_meta = meta
            except Exception as exc:
                _log.debug("Ошибка проекции точки привязки: %s", exc)

        if best_pt is not None and best_screen_pt is not None:
            dist_real = math.hypot(best_screen_pt[0] - mx, best_screen_pt[1] - my)
            target = build_measure_target(best_pt, best_desc, best_kind, best_panel, best_meta)
            self.measure_current_target = target
            return best_pt, target.format_hover_summary(), best_kind, best_screen_pt, True, dist_real, best_panel

        # Пересечение луча с поверхностью детали (с учётом Screen-Space BBox Cull, OBB поворота и плоскости сечения)
        origin, ray_dir = self._mouse_ray(mx, my)
        plane = self.current_section_plane()
        min_t = float("inf")
        hit_pt = None
        hit_panel = None
        for block in self.blocks:
            for p in block.panels:
                if not self._panel_within_screen_radius(p, mx, my, 4.0, mvp, vp, dpr):
                    continue
                t_hit = self._intersect_ray_panel(origin, ray_dir, p)
                if t_hit is not None and t_hit < min_t:
                    cand_pt = origin + t_hit * ray_dir
                    if plane is not None and not glmath.point_passes_clip_plane(
                        float(cand_pt[0]), float(cand_pt[1]), float(cand_pt[2]), plane
                    ):
                        continue
                    min_t = t_hit
                    hit_pt = cand_pt
                    hit_panel = p

        if hit_pt is not None:
            s_hit = None
            try:
                wx, wy, wz = glmath.project(hit_pt[0], hit_pt[1], hit_pt[2], mvp, vp)
                if 0.0 <= wz <= 1.0:
                    s_hit = (int(wx / dpr), int((vp[3] - wy) / dpr))
            except Exception as exc:
                _log.debug("Ошибка проекции точки пересечения с поверхностью: %s", exc)
            pname = f"{hit_panel.name}: " if hit_panel else ""
            target = build_measure_target(hit_pt, f"{pname}Поверхность детали", "surface", hit_panel)
            self.measure_current_target = target
            return hit_pt, target.format_hover_summary(), "surface", s_hit, False, 0.0, hit_panel

        if getattr(self, "is_ortho", False):
            vp_pt = self._intersect_ray_with_view_plane(origin, ray_dir)
            if vp_pt is not None:
                self.measure_current_target = build_measure_target(vp_pt, "Плоскость 2D-вида", "space", None)
                return vp_pt, "Плоскость 2D-вида", "space", None, False, 0.0, None

        # Плоскость пола Y=0
        if abs(ray_dir[1]) > 1e-6:
            t = (0.0 - origin[1]) / ray_dir[1]
            if t > 0:
                f_pt = origin + t * ray_dir
                self.measure_current_target = build_measure_target(f_pt, "Плоскость пола", "floor", None)
                return f_pt, "Плоскость пола", "floor", None, False, 0.0, None

        sp_pt = origin + ray_dir * 500.0
        self.measure_current_target = build_measure_target(sp_pt, "Пространство", "space", None)
        return sp_pt, "Пространство", "space", None, False, 0.0, None

    def _update_measure_hover(self, mx: int, my: int, ctrl_held: bool = False):
        self.measure_mouse_pos = (mx, my)
        self.ctrl_held = ctrl_held

        snap_pt, snap_desc, snap_kind, snap_screen_pt, is_magnetic, snap_dist, snap_panel = self._find_nearest_snap_point(
            mx, my, ctrl_boost=ctrl_held
        )
        cur_target = self.measure_current_target or build_measure_target(snap_pt, snap_desc, snap_kind, snap_panel)
        self.measure_snap_info = (snap_pt, snap_desc)
        self.measure_snap_screen_pos = snap_screen_pt
        self.measure_is_magnetic = is_magnetic
        self.measure_snap_category = snap_kind
        self.measure_snap_dist_px = snap_dist
        self.measure_snap_panel = snap_panel

        ctrl_badge = " [🧲 Ctrl захват]" if (ctrl_held and is_magnetic) else ""

        if self.measure_mode:
            if self.measure_pt1 is not None and self.measure_pt2 is not None:
                # Третья точка: измерение угла между лучом pt2->pt1 и pt2->snap_pt
                self.measure_current_pt = snap_pt
                self.measure_preview_dim = DimensionLine(self.measure_pt2, snap_pt, color=(0.1, 0.85, 0.95))
                ang_tmp = DimensionAngle(self.measure_pt1, self.measure_pt2, snap_pt, color=(0.2, 0.9, 0.95))
                self.measure_preview_angle = ang_tmp
                deg = ang_tmp.angle_deg
                l1 = ang_tmp.distance1
                l2 = ang_tmp.distance2
                right_tag = " [Прямой угол 90°]" if ang_tmp.is_right_angle else ""
                msg = f"Угол: {deg:.1f}°{right_tag} (L1: {l1:.1f} мм, L2: {l2:.1f} мм){ctrl_badge} | ЛКМ — зафиксировать угол | Esc — оставить отрезок"
                self.measurement_updated.emit(msg)
                self.fastener_message.emit(msg)
            elif self.measure_pt1 is not None:
                # Вторая цель: умное контекстное измерение между target1 и cur_target
                self.measure_current_pt = snap_pt
                t1 = self.measure_target1 or build_measure_target(self.measure_pt1, "Точка 1", "point")
                smart = compute_smart_measurement(t1, cur_target)
                preview_dim = DimensionLine(
                    pt1=smart.dimension_line.pt1,
                    pt2=smart.dimension_line.pt2,
                    color=(0.1, 0.85, 0.95),
                    name=smart.dimension_line.name,
                    sub_label=smart.dimension_line.sub_label,
                )
                self.measure_preview_dim = preview_dim
                self.measure_preview_angle = smart.angle_dimension
                msg = f"{smart.status_message}{ctrl_badge} | ЛКМ — зафиксировать"
                self.measurement_updated.emit(msg)
                self.fastener_message.emit(msg)
            else:
                self.measure_preview_dim = None
                self.measure_preview_angle = None
                if cur_target.is_hole:
                    msg = f"Отверстие: {snap_desc}{ctrl_badge} | ЛКМ — замерить шаг до другого отверстия или отступ до грани"
                elif cur_target.is_edge:
                    msg = f"{snap_desc}{ctrl_badge} ({snap_pt[0]:.1f}, {snap_pt[1]:.1f}, {snap_pt[2]:.1f}) | ЛКМ — первая точка"
                elif cur_target.is_face:
                    msg = f"Грань: {snap_desc} | ЛКМ — кликните 2 грани для замера в свету или угла"
                elif is_magnetic:
                    msg = f"Привязка [{snap_desc}]{ctrl_badge} ({snap_pt[0]:.1f}, {snap_pt[1]:.1f}, {snap_pt[2]:.1f}) | ЛКМ — первая точка"
                else:
                    msg = f"Рулетка: [{snap_desc}] ({snap_pt[0]:.1f}, {snap_pt[1]:.1f}, {snap_pt[2]:.1f}) | Зажмите [Ctrl] для магнитного захвата углов/рёбер/отверстий"
                self.measurement_updated.emit(msg)
        else:
            # Общий режим (рулетка выключена): примагничивание по нажатию Ctrl без выделения панели
            if is_magnetic:
                msg = f"🧲 [Ctrl] Магнитная привязка: {snap_desc} ({snap_pt[0]:.1f}, {snap_pt[1]:.1f}, {snap_pt[2]:.1f} мм) | ЛКМ — выделить деталь"
                self.fastener_message.emit(msg)
                self.coordinates_changed.emit(float(snap_pt[0]), float(snap_pt[1]), float(snap_pt[2]))
            elif ctrl_held:
                msg = "🧲 [Ctrl] Магнитный захват активен (54px) — наведите на угол, ребро или отверстие детали"
                self.fastener_message.emit(msg)

        self.update()

    def _handle_measure_click(self, mx: int, my: int, ctrl_held: bool = False):
        snap_pt, snap_desc, snap_kind, _spt, _is_mag, _dist, snap_panel = self._find_nearest_snap_point(
            mx, my, ctrl_boost=ctrl_held
        )
        cur_target = self.measure_current_target or build_measure_target(snap_pt, snap_desc, snap_kind, snap_panel)

        if self.measure_pt1 is None:
            # Выбор первой цели (точки, грани, отверстия, ребра)
            self.measure_pt1 = snap_pt
            self.measure_pt2 = None
            self.measure_current_pt = snap_pt
            self.measure_target1 = cur_target
            self.measure_preview_dim = None
            self.measure_preview_angle = None
            if cur_target.is_face:
                msg = f"▭ Выбрана грань 1 ({snap_desc}). Кликните вторую грань (в свету / угол) или отверстие."
            elif cur_target.is_hole:
                msg = f"🕳 Выбрано отверстие 1 ({snap_desc}). Кликните второе отверстие (шаг) или грань (отступ)."
            else:
                msg = f"📏 Точка 1 ({snap_desc}): ({snap_pt[0]:.1f}, {snap_pt[1]:.1f}, {snap_pt[2]:.1f}). Кликните точку 2."
            self.measurement_updated.emit(msg)
            self.fastener_message.emit(msg)
        elif self.measure_pt2 is None:
            # Выбор второй цели: вычисляем умное измерение
            t1 = self.measure_target1 or build_measure_target(self.measure_pt1, "Точка 1", "point")
            smart = compute_smart_measurement(t1, cur_target)
            if smart.dimension_line.distance < 0.2 and smart.angle_dimension is None:
                return  # повторный клик в ту же точку

            self.dimensions.append(smart.dimension_line)
            if smart.angle_dimension is not None:
                self.angles.append(smart.angle_dimension)

            if not smart.allows_third_point_angle:
                # Умное измерение 2 объектов (грани в свету, угол граней, шаг отверстий, отступ от грани) завершено
                msg = f"✅ {smart.status_message}"
                self.measurement_updated.emit(msg)
                self.fastener_message.emit(msg)
                self.measure_pt1 = None
                self.measure_pt2 = None
                self.measure_current_pt = None
                self.measure_target1 = None
                self.measure_preview_dim = None
                self.measure_preview_angle = None
            else:
                # Обычные точки/углы/рёбра: можно кликнуть 3-ю точку для измерения угла
                self.measure_pt2 = snap_pt
                self.measure_current_pt = snap_pt
                self.measure_preview_dim = None
                self.measure_preview_angle = None
                msg = (
                    f"📏 Точка 2 установлена: L1 = {smart.dimension_line.distance:.1f} мм. "
                    f"Кликните Точку 3 для замера УГЛА (или Esc / ПКМ — оставить линейный размер)."
                )
                self.measurement_updated.emit(msg)
                self.fastener_message.emit(msg)
        else:
            # Выбор третьей точки (завершение 3-точечного угла)
            dist2 = float(np.linalg.norm(snap_pt - self.measure_pt2))
            if dist2 < 0.5:
                # Кликнули в вершину повторно — завершаем без угла
                self.measure_pt1 = None
                self.measure_pt2 = None
                self.measure_current_pt = None
                self.measure_target1 = None
                self.measure_preview_dim = None
                self.measure_preview_angle = None
                return

            dim2 = DimensionLine(self.measure_pt2, snap_pt)
            self.dimensions.append(dim2)
            ang = DimensionAngle(self.measure_pt1, self.measure_pt2, snap_pt)
            self.angles.append(ang)
            deg = ang.angle_deg
            right_tag = " [Прямой угол 90°]" if ang.is_right_angle else ""
            msg = f"✅ Угол зафиксирован: {deg:.1f}°{right_tag} (L1: {ang.distance1:.1f} мм, L2: {ang.distance2:.1f} мм)"
            self.measurement_updated.emit(msg)
            self.fastener_message.emit(msg)
            self.measure_pt1 = None
            self.measure_pt2 = None
            self.measure_current_pt = None
            self.measure_target1 = None
            self.measure_preview_dim = None
            self.measure_preview_angle = None

        self.update()

    def _draw_dimensions(self):
        """Отрисовывает 3D линии размеров, засечки и дуги углов."""
        all_dims = list(self.dimensions)
        if self.measure_mode:
            if self.measure_preview_dim is not None:
                all_dims.append(self.measure_preview_dim)
            elif self.measure_pt1 is not None and self.measure_pt2 is None and self.measure_current_pt is not None:
                all_dims.append(DimensionLine(self.measure_pt1, self.measure_current_pt, color=(0.1, 0.85, 0.95)))
            elif self.measure_pt2 is not None and self.measure_current_pt is not None:
                all_dims.append(DimensionLine(self.measure_pt2, self.measure_current_pt, color=(0.1, 0.85, 0.95)))

        glDisable(GL_DEPTH_TEST)

        # 1. Линейные размеры с 45° засечками
        pts = []
        for dim in all_dims:
            p1, p2 = dim.pt1, dim.pt2
            pts.extend([p1[0], p1[1], p1[2], p2[0], p2[1], p2[2]])

            v = p2 - p1
            nv = np.linalg.norm(v)
            if nv > 1e-6:
                tick_len = 16.0
                u = v / nv
                up = np.array([0.0, 1.0, 0.0]) if abs(u[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
                perp = np.cross(u, up)
                np_len = np.linalg.norm(perp)
                if np_len > 1e-6:
                    perp = perp / np_len
                    tick = (u + perp) * 0.7071 * tick_len
                    pts.extend([p1[0] - tick[0], p1[1] - tick[1], p1[2] - tick[2],
                                p1[0] + tick[0], p1[1] + tick[1], p1[2] + tick[2]])
                    pts.extend([p2[0] - tick[0], p2[1] - tick[1], p2[2] - tick[2],
                                p2[0] + tick[0], p2[1] + tick[1], p2[2] + tick[2]])

        if pts:
            arr = np.asarray(pts, dtype=np.float32).reshape(-1, 3)
            self._draw_lines(arr, (0.96, 0.45, 0.12), 2.5)

        # 2. Дуги углов в 3D
        all_angles = list(self.angles)
        if self.measure_mode:
            if self.measure_preview_angle is not None:
                all_angles.append(self.measure_preview_angle)
            elif self.measure_pt1 is not None and self.measure_pt2 is not None and self.measure_current_pt is not None:
                all_angles.append(DimensionAngle(self.measure_pt1, self.measure_pt2, self.measure_current_pt, color=(0.2, 0.9, 0.95)))

        arc_lines = []
        for ang in all_angles:
            apts = ang.arc_points()
            if len(apts) >= 2:
                for k in range(len(apts) - 1):
                    arc_lines.extend([apts[k][0], apts[k][1], apts[k][2],
                                      apts[k + 1][0], apts[k + 1][1], apts[k + 1][2]])
        if arc_lines:
            arc_arr = np.asarray(arc_lines, dtype=np.float32).reshape(-1, 3)
            self._draw_lines(arc_arr, (0.98, 0.73, 0.01), 3.0)

        # 3. Ортогональные направляющие проекции
        if self.measure_mode and self.measure_pt1 is not None and self.measure_current_pt is not None:
            active_p1 = self.measure_pt2 if self.measure_pt2 is not None else self.measure_pt1
            p2 = self.measure_preview_dim.pt2 if self.measure_preview_dim is not None else self.measure_current_pt
            dx = abs(p2[0] - active_p1[0])
            dy = abs(p2[1] - active_p1[1])
            dz = abs(p2[2] - active_p1[2])
            guide_pts = []
            if dx > 1.0 and (dy > 1.0 or dz > 1.0):
                corner_x = np.array([p2[0], active_p1[1], active_p1[2]])
                guide_pts.extend([active_p1[0], active_p1[1], active_p1[2], corner_x[0], corner_x[1], corner_x[2]])
                if dy > 1.0:
                    corner_xy = np.array([p2[0], p2[1], active_p1[2]])
                    guide_pts.extend([corner_x[0], corner_x[1], corner_x[2], corner_xy[0], corner_xy[1], corner_xy[2]])
                    if dz > 1.0:
                        guide_pts.extend([corner_xy[0], corner_xy[1], corner_xy[2], p2[0], p2[1], p2[2]])
            if guide_pts:
                g_arr = np.asarray(guide_pts, dtype=np.float32).reshape(-1, 3)
                self._draw_lines(g_arr, (0.4, 0.7, 0.9), 1.0)

        glEnable(GL_DEPTH_TEST)

    def _draw_dimensions_overlay(self, painter: QPainter):
        """Отрисовывает 2D маркеры и бейджи размеров в стиле темы программы."""
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp
        bg, border, text_col, text_dim, theme_accent, theme_warning = self._overlay_palette()
        fixed_dim_accent = QColor(217, 119, 6)

        # --- 1. Отрисовка бейджей линейных размеров ---
        all_dims = []
        for dim in self.dimensions:
            all_dims.append((dim, False))
        if self.measure_mode:
            if self.measure_preview_dim is not None:
                all_dims.append((self.measure_preview_dim, True))
            elif self.measure_pt1 is not None and self.measure_pt2 is None and self.measure_current_pt is not None:
                all_dims.append((DimensionLine(self.measure_pt1, self.measure_current_pt), True))
            elif self.measure_pt2 is not None and self.measure_current_pt is not None:
                all_dims.append((DimensionLine(self.measure_pt2, self.measure_current_pt), True))

        for dim, is_active in all_dims:
            mid = dim.midpoint
            try:
                wx, wy, wz = glmath.project(mid[0], mid[1], mid[2], mvp, vp)
                if wz < 0.0 or wz > 1.0:
                    continue
                sx = int(wx / dpr)
                sy = int((vp[3] - wy) / dpr)
            except Exception:
                continue

            stripe_col = theme_accent if is_active else fixed_dim_accent
            for pt in (dim.pt1, dim.pt2):
                try:
                    px, py, pz = glmath.project(pt[0], pt[1], pt[2], mvp, vp)
                    if 0.0 <= pz <= 1.0:
                        psx, psy = int(px / dpr), int((vp[3] - py) / dpr)
                        painter.setPen(QPen(bg, 1.5))
                        painter.setBrush(stripe_col)
                        painter.drawEllipse(QPoint(psx, psy), 4, 4)
                except Exception as exc:
                    _log.debug("Ошибка отрисовки маркера размерной точки: %s", exc)

            main_text = dim.main_badge_text()
            sub_text = dim.sub_badge_text()

            font_main = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
            font_sub = QFont("Segoe UI", 7, QFont.Weight.Normal)

            painter.setFont(font_main)
            fm_main = painter.fontMetrics()
            w1 = fm_main.horizontalAdvance(main_text)
            h1 = fm_main.height()

            painter.setFont(font_sub)
            fm_sub = painter.fontMetrics()
            w2 = fm_sub.horizontalAdvance(sub_text)
            h2 = fm_sub.height()

            stripe_w = 3
            box_w = max(w1, w2) + 16 + stripe_w
            box_h = h1 + h2 + 6
            rect_x = sx - box_w // 2
            rect_y = sy - box_h // 2

            badge_rect = QRect(rect_x, rect_y, box_w, box_h)
            painter.setPen(QPen(theme_accent if is_active else border, 1.0))
            painter.setBrush(bg)
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.fillRect(QRect(rect_x + 1, rect_y + 2, 2, max(1, box_h - 4)), stripe_col)

            text_rect_w = box_w - stripe_w
            painter.setFont(font_main)
            painter.setPen(text_col)
            painter.drawText(
                QRect(rect_x + stripe_w, rect_y + 3, text_rect_w, h1),
                Qt.AlignmentFlag.AlignCenter,
                main_text,
            )

            painter.setFont(font_sub)
            painter.setPen(text_dim)
            painter.drawText(
                QRect(rect_x + stripe_w, rect_y + 4 + h1, text_rect_w, h2),
                Qt.AlignmentFlag.AlignCenter,
                sub_text,
            )

        # --- 2. Отрисовка бейджей углов (DimensionAngle) ---
        all_angles_list = []
        for ang in self.angles:
            all_angles_list.append((ang, False))
        if self.measure_mode:
            if self.measure_preview_angle is not None:
                all_angles_list.append((self.measure_preview_angle, True))
            elif self.measure_pt1 is not None and self.measure_pt2 is not None and self.measure_current_pt is not None:
                all_angles_list.append((DimensionAngle(self.measure_pt1, self.measure_pt2, self.measure_current_pt), True))

        for ang, is_active in all_angles_list:
            bpos = ang.bisector_point(distance=45.0)
            try:
                wx, wy, wz = glmath.project(bpos[0], bpos[1], bpos[2], mvp, vp)
                if wz < 0.0 or wz > 1.0:
                    continue
                asx = int(wx / dpr)
                asy = int((vp[3] - wy) / dpr)
            except Exception:
                continue

            ang_stripe = theme_accent if is_active else theme_warning
            try:
                vx, vy, vz = glmath.project(ang.vertex[0], ang.vertex[1], ang.vertex[2], mvp, vp)
                if 0.0 <= vz <= 1.0:
                    vsx, vsy = int(vx / dpr), int((vp[3] - vy) / dpr)
                    painter.setPen(QPen(bg, 1.5))
                    painter.setBrush(ang_stripe)
                    painter.drawEllipse(QPoint(vsx, vsy), 4, 4)
            except Exception as exc:
                _log.debug("Ошибка отрисовки маркера вершины угла: %s", exc)

            deg = ang.angle_deg
            angle_title = ang.name if ang.name else f"∠ {deg:.1f}°"
            if not ang.name and ang.is_right_angle:
                angle_title = "∠ 90.0° [Прямой]"

            angle_sub = f"L1: {ang.distance1:.0f}  L2: {ang.distance2:.0f} мм"

            font_angle = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
            font_ang_sub = QFont("Segoe UI", 7, QFont.Weight.Normal)

            painter.setFont(font_angle)
            fm_ang = painter.fontMetrics()
            w_ang = fm_ang.horizontalAdvance(angle_title)
            h_ang = fm_ang.height()

            painter.setFont(font_ang_sub)
            fm_ang_sub = painter.fontMetrics()
            w_ang_sub = fm_ang_sub.horizontalAdvance(angle_sub)
            h_ang_sub = fm_ang_sub.height()

            stripe_w = 3
            abox_w = max(w_ang, w_ang_sub) + 16 + stripe_w
            abox_h = h_ang + h_ang_sub + 6
            arect_x = asx - abox_w // 2
            arect_y = asy - abox_h // 2

            abadge_rect = QRect(arect_x, arect_y, abox_w, abox_h)
            painter.setPen(QPen(theme_accent if is_active else border, 1.0))
            painter.setBrush(bg)
            painter.drawRoundedRect(abadge_rect, 3, 3)
            painter.fillRect(QRect(arect_x + 1, arect_y + 2, 2, max(1, abox_h - 4)), ang_stripe)

            atext_w = abox_w - stripe_w
            painter.setFont(font_angle)
            painter.setPen(text_col)
            painter.drawText(
                QRect(arect_x + stripe_w, arect_y + 3, atext_w, h_ang),
                Qt.AlignmentFlag.AlignCenter,
                angle_title,
            )

            painter.setFont(font_ang_sub)
            painter.setPen(text_dim)
            painter.drawText(
                QRect(arect_x + stripe_w, arect_y + 4 + h_ang, atext_w, h_ang_sub),
                Qt.AlignmentFlag.AlignCenter,
                angle_sub,
            )

        # --- 3. Отрисовка маркера привязки, силового луча [Ctrl] и компактной подсказки цели ---
        if (self.measure_mode or getattr(self, "ctrl_held", False)) and self.measure_snap_info is not None:
            snap_pt, _snap_desc = self.measure_snap_info
            is_mag = getattr(self, "measure_is_magnetic", False)
            is_ctrl = getattr(self, "ctrl_held", False)
            mouse_pos = getattr(self, "measure_mouse_pos", None)
            screen_pos = getattr(self, "measure_snap_screen_pos", None)

            if screen_pos is None:
                try:
                    wx, wy, wz = glmath.project(snap_pt[0], snap_pt[1], snap_pt[2], mvp, vp)
                    if 0.0 <= wz <= 1.0:
                        screen_pos = (int(wx / dpr), int((vp[3] - wy) / dpr))
                except Exception as exc:
                    _log.debug("Ошибка вычисления экранных координат привязки: %s", exc)

            if screen_pos is not None:
                sx, sy = screen_pos

                if mouse_pos is not None:
                    mx, my = mouse_pos
                    dist_px = math.hypot(sx - mx, sy - my)
                    if dist_px >= 2.0 and is_mag:
                        if is_ctrl:
                            painter.setPen(QPen(QColor(249, 115, 22, 60), 4, Qt.PenStyle.SolidLine))
                            painter.drawLine(mx, my, sx, sy)
                            painter.setPen(QPen(QColor(249, 115, 22, 220), 1.8, Qt.PenStyle.DashLine))
                            painter.drawLine(mx, my, sx, sy)

                            painter.setPen(QPen(QColor(249, 115, 22), 1.5))
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawEllipse(QPoint(mx, my), 3, 3)
                        else:
                            painter.setPen(QPen(QColor(249, 115, 22, 140), 1.4, Qt.PenStyle.DashLine))
                            painter.drawLine(mx, my, sx, sy)

                if is_mag:
                    orange_col = QColor(249, 115, 22)
                    r_sz = 9 if is_ctrl else 8
                    poly = [QPoint(sx, sy - r_sz), QPoint(sx + r_sz, sy), QPoint(sx, sy + r_sz), QPoint(sx - r_sz, sy)]
                    painter.setPen(QPen(orange_col, 2.0))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(poly)
                else:
                    painter.setPen(QPen(QColor(249, 115, 22, 180), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPoint(sx, sy), 3, 3)

                # Компактная подсказка элемента под курсором в стиле системной темы
                cur_t = self.measure_current_target
                if self.measure_mode and cur_t is not None and (cur_t.is_hole or cur_t.is_edge or cur_t.is_face):
                    info_text = cur_t.format_hover_summary()
                    font_tip = QFont("Segoe UI", 8)
                    painter.setFont(font_tip)
                    fm_tip = painter.fontMetrics()
                    stripe_w = 3
                    pad_x, pad_y = 7, 3
                    tw = fm_tip.horizontalAdvance(info_text) + pad_x * 2 + stripe_w
                    th = fm_tip.height() + pad_y * 2
                    tx = min(max(8, sx + 14), max(8, self.width() - tw - 8))
                    ty = max(8, sy - th - 10)
                    tip_rect = QRect(tx, ty, tw, th)
                    painter.setPen(QPen(border, 1.0))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(tip_rect, 3, 3)
                    painter.fillRect(QRect(tx + 1, ty + 2, 2, max(1, th - 4)), theme_accent)
                    painter.setPen(text_col)
                    painter.drawText(
                        tip_rect.adjusted(pad_x + stripe_w, 0, -pad_x, 0),
                        Qt.AlignmentFlag.AlignVCenter,
                        info_text,
                    )

    def _mouse_ray(self, mx: int, my: int):
        """Луч из камеры в мир (origin, direction)."""
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        x = mx * dpr
        y = vp[3] - my * dpr
        near = glmath.unproject(x, y, 0.0, self._mvp, vp)
        far = glmath.unproject(x, y, 1.0, self._mvp, vp)
        origin = np.asarray(near, dtype=float)
        direction = np.asarray(far, dtype=float) - origin
        n = np.linalg.norm(direction)
        if n > 1e-12:
            direction = direction / n
        return origin, direction

    def start_drag_mode(self, panel: Panel | None = None):
        """Активирует режим перемещения детали по клавише G:
        Порядок:
        1) Нажали G
        2) Однократный клик ЛКМ по точке за которую тащим (угол, ребро, центр)
        3) Деталь сразу следует за курсором (без зажатия кнопок!)
        4) Клик ЛКМ по целевой точке — деталь зафиксирована
        """
        if panel is None:
            panel = self.get_selected_panel()

        if panel is None:
            self.fastener_message.emit("Перемещение (G): сначала выберите деталь (ЛКМ), затем нажмите G")
            return

        self.stop_measure_mode()
        self.stop_fastener_mode()
        self.setMouseTracking(True)

        self.drag_mode = True
        self.drag_stage = 1  # ЭТАП 1: ожидание клика по точке зацепа!
        self.drag_panel = panel
        self.drag_orig_pos = (float(panel.x), float(panel.y), float(panel.z))
        self.drag_base_point = None
        self.drag_base_desc = ""
        self.drag_target_point = None
        self.drag_target_desc = ""

        # Сразу определяем точку под текущим положением курсора для быстрой подсветки
        mx = self.last_mouse_pos.x() if hasattr(self, "last_mouse_pos") and not self.last_mouse_pos.isNull() else self.width() // 2
        my = self.last_mouse_pos.y() if hasattr(self, "last_mouse_pos") and not self.last_mouse_pos.isNull() else self.height() // 2
        self.drag_hover_point, self.drag_hover_desc = self._find_base_snap_point(mx, my)

        msg = f"[G] Выберите базовую точку [{panel.name}] (ЛКМ) | Esc — отмена"
        self.fastener_message.emit(msg)
        self.update()

    def cancel_drag_mode(self, quiet: bool = False):
        """Отменяет режим перемещения без изменения положения детали."""
        self.drag_mode = False
        self.drag_stage = 0
        self.drag_panel = None
        self.drag_orig_pos = None
        self.drag_base_point = None
        self.drag_base_desc = ""
        self.drag_target_point = None
        self.drag_target_desc = ""
        self.drag_hover_point = None
        self.drag_hover_desc = ""
        self.drag_axis_lock = None
        if not quiet:
            self.fastener_message.emit("Перемещение отменено")
        self.update()


    def copy_selection(self) -> None:
        """Ctrl+C: снимок выделения → ждём клик точки привязки."""
        self.cancel_drag_mode(quiet=True)
        if getattr(self, "fastener_mode", False) or getattr(self, "fastener_pick_second", False):
            self.stop_fastener_mode()
        payload = capture_selection(self.blocks)
        if payload is None:
            self.fastener_message.emit("📋 Копирование: сначала выделите панели или блок")
            return
        self.clipboard = payload
        self.clipboard_await_anchor = True
        self.paste_mode = False
        self.paste_target_point = None
        n = payload.count_panels
        b = payload.count_blocks
        self.fastener_message.emit(
            f"📋 Скопировано: панелей {n}" + (f", блоков {b}" if b else "")
            + " — кликните точку привязки на оригинале, затем Ctrl+V"
        )
        self.update()

    def cancel_paste_mode(self, quiet: bool = False) -> None:
        self.clipboard_await_anchor = False
        self.paste_mode = False
        self.paste_target_point = None
        if not quiet:
            self.fastener_message.emit("Вставка отменена")
        self.update()

    def begin_paste_mode(self) -> None:
        """Ctrl+V: превью вставки (нужны буфер и точка привязки)."""
        if self.clipboard is None:
            self.fastener_message.emit("📋 Буфер пуст — сначала Ctrl+C")
            return
        if self.clipboard.anchor is None:
            self.clipboard_await_anchor = True
            self.fastener_message.emit("📋 Сначала кликните точку привязки на оригинале")
            return
        self.cancel_drag_mode(quiet=True)
        self.paste_mode = True
        self.clipboard_await_anchor = False
        self.setMouseTracking(True)
        self.fastener_message.emit(
            "📋 Вставка: наведите курсор и кликните место размещения | Esc — отмена"
        )
        self.update()

    def _place_clipboard_at(self, target: np.ndarray) -> None:
        if self.clipboard is None or self.clipboard.anchor is None:
            return
        try:
            new_blocks = materialize(
                self.clipboard,
                (float(target[0]), float(target[1]), float(target[2])),
            )
        except Exception as exc:
            _log.exception("paste failed")
            self.fastener_message.emit(f"📋 Ошибка вставки: {exc}")
            return
        if not new_blocks:
            self.fastener_message.emit("📋 Нечего вставлять")
            return
        # снять выделение со старых
        for b in self.blocks:
            b.selected = False
            for p in b.panels:
                p.selected = False
        cmd = PasteBlocksCommand(self.blocks, new_blocks, description="Вставка")
        self.undo_stack.push(cmd, execute=True)
        self.paste_mode = False
        self.paste_target_point = None
        # буфер оставляем — можно вставлять ещё раз
        n = sum(len(b.panels) for b in new_blocks)
        self.fastener_message.emit(f"📋 Вставлено панелей: {n}")
        self.scene_structure_changed.emit()
        self.update()

    def _find_base_snap_point(self, mx: int, my: int) -> tuple[np.ndarray, str]:
        if self.drag_panel is None:
            return np.zeros(3, dtype=float), "Точка"
        p = self.drag_panel
        candidates = self._collect_panel_snap_points(p)
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp

        best_pt = None
        best_desc = ""
        min_screen_dist = 24.0

        for item in candidates:
            pt, desc = item[0], item[1]
            try:
                wx, wy, wz = glmath.project(pt[0], pt[1], pt[2], mvp, vp)
                if wz < 0.0 or wz > 1.0:
                    continue
                sx = wx / dpr
                sy = (vp[3] - wy) / dpr
                dist = math.hypot(sx - mx, sy - my)
                if dist < min_screen_dist:
                    min_screen_dist = dist
                    best_pt = pt
                    best_desc = desc
            except Exception as exc:
                _log.debug("Ошибка проекции базовой точки захвата панели: %s", exc)

        if best_pt is not None:
            return best_pt, best_desc

        origin, ray_dir = self._mouse_ray(mx, my)
        t_hit = self._intersect_ray_panel(origin, ray_dir, p)
        if t_hit is not None:
            return origin + t_hit * ray_dir, "Поверхность детали"

        if hasattr(p, "world_center"):
            wc = p.world_center()
            return np.array([wc[0], wc[1], wc[2]], dtype=float), "Центр детали"
        return np.array([p.x + p.width * 0.5, p.y + p.height * 0.5, p.z + p.depth * 0.5], dtype=float), "Центр детали"

    def _ray_hit_workplane(self, mx: int, my: int) -> np.ndarray | None:
        """Точка на полу Y=0 или вдоль луча (fallback для вставки)."""
        pt, _desc = self._find_target_snap_point(mx, my)
        return pt

    def _find_target_snap_point(self, mx: int, my: int) -> tuple[np.ndarray, str]:
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp
        is_ctrl = bool(getattr(self, "ctrl_held", False))
        snap_active = bool(getattr(self, "face_snap_enabled", True)) or is_ctrl
        plane = self.current_section_plane()

        is_ortho = bool(getattr(self, "is_ortho", False))
        n_ax = self._view_plane_normal_axis() if is_ortho else None
        cam_fwd = self._camera_axes()[2]
        ref_pt: np.ndarray | None = None
        if self.drag_mode and self.drag_base_point is not None:
            ref_pt = np.asarray(self.drag_base_point, dtype=float)
        elif self.paste_mode and self.clipboard is not None and self.clipboard.anchor is not None:
            ref_pt = np.asarray(self.clipboard.anchor, dtype=float)

        best_pt, best_label = self._find_magnetic_snap_point(
            mx, my, exclude_panel=self.drag_panel, base_radius=24.0
        )
        if best_pt is not None:
            out_pt = np.asarray(best_pt, dtype=float).copy()
            if is_ortho and ref_pt is not None and self.drag_axis_lock is None:
                if n_ax in (0, 1, 2):
                    out_pt[int(n_ax)] = float(ref_pt[int(n_ax)])
                else:
                    out_pt = out_pt - float(np.dot(out_pt - ref_pt, cam_fwd)) * cam_fwd
            return out_pt, best_label

        origin, ray_dir = self._mouse_ray(mx, my)

        # Пересечение с поверхностью другой детали (активно только при включённой магнитной привязке или с Ctrl)
        if snap_active:
            min_t = float("inf")
            hit_pt = None
            hit_desc = ""
            for block in self.blocks:
                for p in block.panels:
                    if p is self.drag_panel:
                        continue
                    if not self._panel_within_screen_radius(p, mx, my, 4.0, mvp, vp, dpr):
                        continue
                    t_hit = self._intersect_ray_panel(origin, ray_dir, p)
                    if t_hit is not None and t_hit < min_t:
                        cand_pt = origin + t_hit * ray_dir
                        if plane is not None and not glmath.point_passes_clip_plane(
                            float(cand_pt[0]), float(cand_pt[1]), float(cand_pt[2]), plane
                        ):
                            continue
                        min_t = t_hit
                        hit_pt = cand_pt
                        prefix = "🧲 [Ctrl] " if is_ctrl else "🧲 "
                        hit_desc = f"{prefix}Поверхность [{p.name}]"

            if hit_pt is not None:
                out_hit = np.asarray(hit_pt, dtype=float).copy()
                if is_ortho and ref_pt is not None and self.drag_axis_lock is None:
                    if n_ax in (0, 1, 2):
                        out_hit[int(n_ax)] = float(ref_pt[int(n_ax)])
                    else:
                        out_hit = out_hit - float(np.dot(out_hit - ref_pt, cam_fwd)) * cam_fwd
                return out_hit, hit_desc

        return glmath.project_ray_to_drag_plane(
            origin,
            ray_dir,
            ref_pt,
            is_ortho=is_ortho,
            normal_axis=n_ax,
            camera_forward=cam_fwd,
            axis_lock=self.drag_axis_lock,
            fallback_pivot=self._focus_reference_point(),
        )

    def _draw_ghost_panel(self, p: Panel, dx: float, dy: float, dz: float):
        """Отрисовывает полупрозрачный 3D фантом панели со смещением (dx, dy, dz)."""
        if p.mesh_data is None:
            p.rebuild_geometry()
        gpu = self._upload_panel_gpu(p)
        if gpu is not None:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(1.5, 2.0)
            glUseProgram(self._prog_solid)
            mvp_loc = glGetUniformLocation(self._prog_solid, "uMVP")
            t_mat = glmath.translate(dx, dy, dz)
            mvp_translated = glmath.mul(self._mvp, t_mat)
            glUniformMatrix4fv(mvp_loc, 1, GL_TRUE, mvp_translated)
            glUniform3f(glGetUniformLocation(self._prog_solid, "uColor"), 0.15, 0.78, 0.98)
            self._apply_studio_light_uniforms(self._prog_solid)
            self._apply_clip_plane_uniform(self._prog_solid, active_override=False)
            aloc = glGetUniformLocation(self._prog_solid, "uAlpha")
            if aloc >= 0:
                glUniform1f(aloc, 0.45)
            glBindVertexArray(gpu["vao"])
            glDrawElements(GL_TRIANGLES, gpu["count"], GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
            glUseProgram(0)
            glDisable(GL_POLYGON_OFFSET_FILL)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)

        # Контуры рёбер и вырезов смещённого тела (с учётом поворота OBB)
        color = (0.05, 0.9, 1.0)
        if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "world_corners"):
            corners = [(cx + dx, cy + dy, cz + dz) for cx, cy, cz in p.world_corners()]
            self._draw_oriented_box_wireframe(corners, color, 1.5)
        else:
            self._draw_box_wireframe(p.x + dx, p.y + dy, p.z + dz, p.width, p.height, p.depth, color, 1.5)
        for gx, gy, gz, gw, gh, gd in getattr(p, "grooves", []):
            if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "local_to_world"):
                locals_g = [
                    (gx, gy, gz), (gx + gw, gy, gz), (gx + gw, gy + gh, gz), (gx, gy + gh, gz),
                    (gx, gy, gz + gd), (gx + gw, gy, gz + gd), (gx + gw, gy + gh, gz + gd), (gx, gy + gh, gz + gd),
                ]
                wc = []
                for c in locals_g:
                    wx, wy, wz = p.local_to_world(*c)
                    wc.append((wx + dx, wy + dy, wz + dz))
                self._draw_oriented_box_wireframe(wc, color, 1.2)
            else:
                self._draw_box_wireframe(p.x + dx + gx, p.y + dy + gy, p.z + dz + gz, gw, gh, gd, color, 1.2)
        for hole in getattr(p, "holes", []):
            hx, hy, hz, radius, length, axis = hole[:6]
            self._draw_panel_hole_wire(p, hx, hy, hz, radius, length, axis, color=color, dx=dx, dy=dy, dz=dz)

    def _draw_drag_preview(self):
        """Отрисовывает 3D вектор перемещения и полупрозрачный фантом панели."""
        if not self.drag_mode or self.drag_panel is None:
            return

        if self.drag_stage == 2 and self.drag_base_point is not None and self.drag_target_point is not None:
            delta = self.drag_target_point - self.drag_base_point
            dx, dy, dz = float(delta[0]), float(delta[1]), float(delta[2])

            # 1. 3D вектор перемещения (линия от базы к цели)
            line_pts = np.array([
                self.drag_base_point,
                self.drag_target_point,
            ], dtype=np.float32)
            self._draw_lines(line_pts, (0.05, 0.85, 1.0), 1.5)

            # 2. Фантомное тело панели
            self._draw_ghost_panel(self.drag_panel, dx, dy, dz)

    def _draw_paste_preview(self):
        """Фантомы копируемых панелей со сдвигом anchor→target."""
        if not self.paste_mode or self.clipboard is None or self.clipboard.anchor is None:
            return
        if self.paste_target_point is None:
            return
        ax, ay, az = self.clipboard.anchor
        tpt = self.paste_target_point
        dx = float(tpt[0]) - float(ax)
        dy = float(tpt[1]) - float(ay)
        dz = float(tpt[2]) - float(az)
        # линия привязки
        line = np.array([[ax, ay, az], [float(tpt[0]), float(tpt[1]), float(tpt[2])]], dtype=np.float32)
        self._draw_lines(line, (0.2, 0.9, 0.35), 1.5)
        # фантомы из исходных панелей (до клонирования)
        ghosts = []
        for bd in self.clipboard.block_dicts:
            for pd in bd.get("panels") or []:
                ghosts.append(pd)
        ghosts.extend(self.clipboard.free_panel_dicts)
        for pd in ghosts:
            try:
                rx = float(pd.get("rx", 0.0) or 0.0)
                ry = float(pd.get("ry", 0.0) or 0.0)
                rz = float(pd.get("rz", 0.0) or 0.0)
                if abs(rx) > 1e-6 or abs(ry) > 1e-6 or abs(rz) > 1e-6:
                    corners = panel_dict_preview_corners(pd, dx, dy, dz)
                    self._draw_oriented_box_wireframe(corners, (0.15, 0.85, 0.35), 1.2)
                else:
                    x = float(pd.get("x", 0)) + dx
                    y = float(pd.get("y", 0)) + dy
                    z = float(pd.get("z", 0)) + dz
                    w = float(pd.get("width", 100))
                    h = float(pd.get("height", 16))
                    d = float(pd.get("depth", 100))
                    self._draw_box_wireframe(x, y, z, w, h, d, (0.15, 0.85, 0.35), 1.2)
            except Exception as exc:
                _log.debug("Paste preview wireframe skipped: %s", exc)
                continue


    def _draw_drag_overlay(self, painter: QPainter):
        """Отрисовывает только компактные 2D-маркеры базовой и целевой точек при перемещении (G)."""
        if not self.drag_mode:
            return

        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        mvp = self._mvp

        if self.drag_stage == 1:
            # Маркер точки зацепа под курсором на выбранной детали
            if self.drag_hover_point is not None:
                pt = self.drag_hover_point
                try:
                    wx, wy, wz = glmath.project(pt[0], pt[1], pt[2], mvp, vp)
                    if 0.0 <= wz <= 1.0:
                        sx = int(wx / dpr)
                        sy = int((vp[3] - wy) / dpr)

                        painter.setPen(QPen(QColor(249, 115, 22), 2.0))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        poly = [QPoint(sx, sy - 8), QPoint(sx + 8, sy), QPoint(sx, sy + 8), QPoint(sx - 8, sy)]
                        painter.drawPolygon(poly)
                except Exception as exc:
                    _log.debug("Ошибка отрисовки маркера зацепа (drag stage 1): %s", exc)
        elif self.drag_stage == 2:
            # Маркер исходной базовой точки
            if self.drag_base_point is not None:
                bpt = self.drag_base_point
                try:
                    wx, wy, wz = glmath.project(bpt[0], bpt[1], bpt[2], mvp, vp)
                    if 0.0 <= wz <= 1.0:
                        bsx = int(wx / dpr)
                        bsy = int((vp[3] - wy) / dpr)
                        painter.setPen(QPen(QColor(245, 115, 20), 2))
                        painter.setBrush(QColor(245, 115, 20, 60))
                        painter.drawEllipse(QPoint(bsx, bsy), 6, 6)
                        painter.setBrush(QColor(255, 255, 255))
                        painter.drawEllipse(QPoint(bsx, bsy), 2, 2)
                except Exception as exc:
                    _log.debug("Ошибка отрисовки базовой точки (drag stage 2): %s", exc)

            # Маркер целевой точки (перекрестие без всплывающей плашки)
            if self.drag_target_point is not None:
                tpt = self.drag_target_point
                try:
                    wx, wy, wz = glmath.project(tpt[0], tpt[1], tpt[2], mvp, vp)
                    if 0.0 <= wz <= 1.0:
                        tsx = int(wx / dpr)
                        tsy = int((vp[3] - wy) / dpr)
                        painter.setPen(QPen(QColor(0, 120, 212), 1.8))
                        painter.setBrush(QColor(0, 120, 212, 55))
                        painter.drawEllipse(QPoint(tsx, tsy), 7, 7)
                        painter.drawLine(tsx - 11, tsy, tsx + 11, tsy)
                        painter.drawLine(tsx, tsy - 11, tsx, tsy + 11)
                except Exception as exc:
                    _log.debug("Ошибка отрисовки целевого маркера перетаскивания: %s", exc)

    def _update_fastener_preview(self, mx: int, my: int):
        if not self.fastener_mode or self.fastener_joint is None:
            return
        j = self.fastener_joint
        origin, direction = self._mouse_ray(mx, my)
        n = j.drill_dir.astype(float)
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            return
        n = n / nn
        denom = float(np.dot(direction, n))
        if abs(denom) < 1e-8:
            hit = origin
        else:
            t = float(np.dot(j.origin - origin, n)) / denom
            hit = origin + t * direction
        margin = float(self.fastener_margin)
        self.fastener_preview = clamp_joint_point(j, hit, margin=margin)
        rel = self.fastener_preview - j.origin
        center_t = float(np.dot(rel, j.slide_dir))
        self._refresh_fastener_preview_points(center_t=center_t)
        self.update()

    def _place_fastener_at_preview(self) -> bool:
        if not self.fastener_mode or self.fastener_joint is None:
            return False
        j = self.fastener_joint
        pts = self.fastener_preview_points
        if not pts and self.fastener_preview is not None:
            pts = [self.fastener_preview]
        if not pts:
            return False

        target_block = getattr(j.panel_a, "_block", None) or getattr(j.panel_b, "_block", None)
        if target_block is None:
            for b in self.blocks:
                if j.panel_a in b.panels or j.panel_b in b.panels:
                    target_block = b
                    break

        preset_id = getattr(self, "fastener_preset_id", "") or "confirmat_3"
        preset = get_fastener_preset(preset_id)
        fastener_id = str(preset.get("fastener_id") or "") if preset else ""

        center_offset = 0.0
        if self.fastener_preview is not None:
            rel = self.fastener_preview - j.origin
            center_t = float(np.dot(rel, j.slide_dir))
            mid_t = 0.5 * (float(j.t_min) + float(j.t_max))
            center_offset = center_t - mid_t

        pa_uid = str(getattr(j.panel_a, "uid", "") or "")
        pb_uid = str(getattr(j.panel_b, "uid", "") or "")
        existing_uid = ""
        if target_block is not None:
            for existing in getattr(target_block, "joints", None) or []:
                ea = str(getattr(existing, "panel_a_uid", ""))
                eb = str(getattr(existing, "panel_b_uid", ""))
                if {ea, eb} == {pa_uid, pb_uid} and pa_uid and pb_uid:
                    existing_uid = str(getattr(existing, "uid", ""))
                    break

        custom = getattr(self, "_last_fastener_params", None)
        use_custom = isinstance(custom, dict) and not str(preset_id).startswith("dowel")
        face_dia: float | None = None
        edge_dia: float | None = None
        edge_dep: float | None = None
        record_params: dict = {
            "diameter": float(self.fastener_diameter),
            "depth": float(self.fastener_depth),
            "margin": float(self.fastener_margin),
            "count": int(self.fastener_count),
            "pitch": float(self.fastener_pitch) if self.fastener_pitch is not None else None,
            "center_offset": float(center_offset),
        }
        if use_custom and custom is not None:
            face_dia = float(custom.get("drill_face_diameter", custom.get("d1", self.fastener_diameter)))
            edge_dia = float(custom.get("drill_edge_diameter", custom.get("d2", 5.0)))
            edge_dep = float(custom.get("drill_edge_depth", custom.get("depth", self.fastener_depth)))
            record_params.update(
                {
                    "d1": face_dia,
                    "d2": edge_dia,
                    "h": float(custom.get("h", 50.0)),
                    "h1": float(custom.get("h1", 0.0)),
                    "drill_face_diameter": face_dia,
                    "drill_edge_diameter": edge_dia,
                    "drill_edge_depth": edge_dep,
                    "custom_name": str(custom.get("name") or ""),
                }
            )

        joint_record = JointRecord(
            uid=existing_uid,
            panel_a_uid=pa_uid,
            panel_b_uid=pb_uid,
            preset_id=preset_id,
            fastener_id=fastener_id,
            params=record_params,
        )

        holes_a = [
            h for h in j.panel_a.holes
            if not (existing_uid and hole_joint_uid(h) == existing_uid)
        ]
        holes_b = [
            h for h in j.panel_b.holes
            if not (existing_uid and hole_joint_uid(h) == existing_uid)
        ]
        joint_issues = []
        for pt in pts:
            ha, hb = make_joint_holes(
                j, pt,
                self.fastener_diameter, self.fastener_depth,
                fastener_id=fastener_id or None,
                issues=joint_issues,
                face_diameter=face_dia,
                edge_diameter=edge_dia,
                edge_depth=edge_dep,
            )
            holes_a.append(tag_joint_hole(ha, joint_record.uid))
            holes_b.append(tag_joint_hole(hb, joint_record.uid))
        n = len(pts)
        cmd = PlaceJointFastenerCommand(
            j.panel_a, list(j.panel_a.holes), holes_a,
            j.panel_b, list(j.panel_b.holes), holes_b,
            f"Крепёж ×{n} Ø{self.fastener_diameter:.0f} на стыке",
            block=target_block,
            joint_record=joint_record,
        )
        self.undo_stack.push(cmd, execute=True)
        self.scene_structure_changed.emit()
        if joint_issues:
            warn_txt = "; ".join(iss.format_line() for iss in joint_issues)
            self.fastener_message.emit(
                f"Поставлено крепежей: {n} (Ø{self.fastener_diameter:.0f}) | {warn_txt}"
            )
        else:
            self.fastener_message.emit(f"✅ Поставлено крепежей: {n} (Ø{self.fastener_diameter:.0f})")
        self.update()
        return True


    def _panel_corners(self, p: Panel) -> list[tuple[tuple[int, int, int], np.ndarray]]:
        """8 углов панели: ((sx,sy,sz), world_xyz). sx/sy/sz = 0|1 (min|max) в локальных координатах детали."""
        w, h, d = float(p.width), float(p.height), float(p.depth)
        lxs, lys, lzs = (0.0, w), (0.0, h), (0.0, d)
        has_ltw = hasattr(p, "local_to_world")
        out = []
        for sx in (0, 1):
            for sy in (0, 1):
                for sz in (0, 1):
                    if has_ltw:
                        wx, wy, wz = p.local_to_world(lxs[sx], lys[sy], lzs[sz])
                    else:
                        wx, wy, wz = float(p.x) + lxs[sx], float(p.y) + lys[sy], float(p.z) + lzs[sz]
                    out.append(((sx, sy, sz), np.array([wx, wy, wz], dtype=float)))
        return out

    def _project_to_screen(self, pt: np.ndarray) -> tuple[float, float] | None:
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        wx, wy, wz = glmath.project(float(pt[0]), float(pt[1]), float(pt[2]), self._mvp, vp)
        if wz < -0.05 or wz > 1.05:
            return None
        return wx / dpr, (vp[3] - wy) / dpr

    def _resize_active_axes(self) -> tuple[bool, bool, bool]:
        """Какие оси можно менять в текущем виде (X,Y,Z)."""
        if not self.is_ortho:
            return True, True, True
        name = getattr(self, "view_name", "iso")
        if name in ("front", "back"):
            return True, True, False
        if name == "top":
            return True, False, True
        if name in ("left", "right"):
            return False, True, True
        return True, True, True

    def _panel_face_handles(
        self, p: Panel
    ) -> list[tuple[tuple[int, int], np.ndarray, np.ndarray, str]]:
        """Ручки вытягивания 4 рабочих торцов детали («Тянуть грань в 3D» / Push-Pull).

        Пропускает пласть вдоль `thickness_axis`, чтобы толщина материала оставалась неизменной.
        Возвращает список `((axis_idx, side), world_center, world_outward_normal, label)`.
        """
        w, h, d = float(p.width), float(p.height), float(p.depth)
        wm, hm, dm = w * 0.5, h * 0.5, d * 0.5
        tax = int(getattr(p, "thickness_axis", -1))
        allow_axes = self._resize_active_axes()
        has_ltw = hasattr(p, "local_to_world")
        has_rot = hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "rotate_vector")

        def to_world(lx: float, ly: float, lz: float) -> np.ndarray:
            if has_ltw:
                wx, wy, wz = p.local_to_world(lx, ly, lz)
                return np.array([wx, wy, wz], dtype=float)
            return np.array([float(p.x) + lx, float(p.y) + ly, float(p.z) + lz], dtype=float)

        def to_world_dir(nx: float, ny: float, nz: float) -> np.ndarray:
            if has_rot:
                rx, ry, rz = p.rotate_vector(nx, ny, nz)
                v = np.array([rx, ry, rz], dtype=float)
            else:
                v = np.array([nx, ny, nz], dtype=float)
            vn = float(np.linalg.norm(v))
            return v / vn if vn > 1e-12 else np.array([nx, ny, nz], dtype=float)

        defs = [
            ((0, 0), (0.0, hm, dm), (-1.0, 0.0, 0.0), "Левый торец (-X)"),
            ((0, 1), (w, hm, dm), (1.0, 0.0, 0.0), "Правый торец (+X)"),
            ((1, 0), (wm, 0.0, dm), (0.0, -1.0, 0.0), "Нижний торец (-Y)"),
            ((1, 1), (wm, h, dm), (0.0, 1.0, 0.0), "Верхний торец (+Y)"),
            ((2, 0), (wm, hm, 0.0), (0.0, 0.0, -1.0), "Задний торец (-Z)"),
            ((2, 1), (wm, hm, d), (0.0, 0.0, 1.0), "Передний торец (+Z)"),
        ]
        out = []
        for (ax_idx, side), lpt, lnrm, label in defs:
            if ax_idx == tax or not allow_axes[ax_idx]:
                continue
            out.append(((ax_idx, side), to_world(*lpt), to_world_dir(*lnrm), label))
        return out

    def _panel_face_corners_world(self, p: Panel, face_id: tuple[int, int]) -> list[np.ndarray]:
        """Возвращает 4 мировых угла грани `face_id = (axis_idx, side)` в порядке обхода контура."""
        w, h, d = float(p.width), float(p.height), float(p.depth)
        ax_idx, side = face_id
        if ax_idx == 0:
            x = w if side == 1 else 0.0
            local_pts = [(x, 0.0, 0.0), (x, h, 0.0), (x, h, d), (x, 0.0, d)]
        elif ax_idx == 1:
            y = h if side == 1 else 0.0
            local_pts = [(0.0, y, 0.0), (w, y, 0.0), (w, y, d), (0.0, y, d)]
        else:
            z = d if side == 1 else 0.0
            local_pts = [(0.0, 0.0, z), (w, 0.0, z), (w, h, z), (0.0, h, z)]
        has_ltw = hasattr(p, "local_to_world")
        out = []
        for lx, ly, lz in local_pts:
            if has_ltw:
                wx, wy, wz = p.local_to_world(lx, ly, lz)
            else:
                wx, wy, wz = float(p.x) + lx, float(p.y) + ly, float(p.z) + lz
            out.append(np.array([wx, wy, wz], dtype=float))
        return out

    def _find_face_handle(self, mx: int, my: int, panel: Panel | None = None):
        """Ближайшая ручка торца («Тянуть грань в 3D») в радиусе курсора."""
        panels = [panel] if panel is not None else self.get_selected_panels()
        if not panels:
            return None
        self._sync_viewport_matrices()
        best = None
        best_d = self.resize_handle_px + 3.5
        for p in panels:
            for face_id, wpt, wnrm, label in self._panel_face_handles(p):
                scr = self._project_to_screen(wpt)
                if scr is None:
                    continue
                d = math.hypot(scr[0] - mx, scr[1] - my)
                if d < best_d:
                    best_d = d
                    best = (p, face_id, wpt, wnrm, label)
        return best

    def _find_resize_handle(self, mx: int, my: int, panel: Panel | None = None):
        """Ближайший угол выделенной панели в радиусе ручки. (panel, corner, world_pt) | None."""
        panels = [panel] if panel is not None else self.get_selected_panels()
        if not panels:
            return None
        self._sync_viewport_matrices()
        best = None
        best_d = self.resize_handle_px + 3.5
        for p in panels:
            for corner, wpt in self._panel_corners(p):
                scr = self._project_to_screen(wpt)
                if scr is None:
                    continue
                d = math.hypot(scr[0] - mx, scr[1] - my)
                if d < best_d:
                    best_d = d
                    best = (p, corner, wpt)
        return best

    def _cursor_on_resize_plane(
        self,
        mx: int,
        my: int,
        fixed_pt: np.ndarray,
        plane_normal: np.ndarray | None = None,
    ) -> np.ndarray:
        """Точка под курсором на рабочей плоскости детали (или плоскости, параллельной экрану) через fixed_pt.

        Если задана `plane_normal` (нормаль рабочей плоскости плиты), луч пересекается с плоскостью детали,
        а при скользящих углах обзора (< 20°) нормаль плавно стабилизируется к направлению взгляда камеры,
        чтобы исключить скачки и уход точки на бесконечность.
        """
        origin, direction = self._mouse_ray(mx, my)
        v = np.asarray(direction, dtype=float)
        vn = float(np.linalg.norm(v))
        if vn > 1e-12:
            v = v / vn
        R = self._rotation_matrix()
        forward = R[:3, :3].T @ np.array([0.0, 0.0, -1.0], dtype=float)
        fn = float(np.linalg.norm(forward))
        if fn > 1e-12:
            forward = forward / fn

        n_cam = -v
        if plane_normal is not None:
            n_s = np.asarray(plane_normal, dtype=float)
            ns_norm = float(np.linalg.norm(n_s))
            if ns_norm > 1e-12:
                n_s = n_s / ns_norm
                if float(np.dot(n_s, n_cam)) < 0.0:
                    n_s = -n_s
                c = float(np.dot(n_s, n_cam))
                min_cos = 0.35
                if c >= min_cos:
                    normal = n_s
                else:
                    t_perp = n_s - c * n_cam
                    tn = float(np.linalg.norm(t_perp))
                    if tn > 1e-9:
                        t_unit = t_perp / tn
                        normal = min_cos * n_cam + math.sqrt(max(0.0, 1.0 - min_cos * min_cos)) * t_unit
                    else:
                        normal = n_cam
            else:
                normal = forward
        else:
            normal = forward

        denom = float(np.dot(v, normal))
        if abs(denom) < 1e-10:
            return np.asarray(fixed_pt, dtype=float)
        t = float(np.dot(np.asarray(fixed_pt, dtype=float) - origin, normal)) / denom
        return origin + v * t

    def _corner_active_axes_and_dirs(
        self,
        panel: Panel,
        corner: tuple[int, int, int],
        orig_box: tuple[float, float, float, float, float, float],
    ) -> tuple[list[int], dict[int, np.ndarray], dict[int, np.ndarray], np.ndarray, np.ndarray]:
        """Возвращает для угла `corner = (sx, sy, sz)`:
        - `active_axes`: список рабочих осей детали (без `thickness_axis` и заблокированных осей 2D-вида);
        - `axis_worlds`: единичные мировые векторы вытягивания от неподвижной грани к тянущемуся углу;
        - `fixed_face_pts`: опорные мировые точки неподвижных противоположных граней для каждой рабочей оси;
        - `grab_world`: исходная мировая точка захваченного угла;
        - `sheet_normal`: мировая нормаль плоскости плиты.
        """
        x0, y0, z0, w, h, d = [float(v) for v in orig_box]
        dims = [w, h, d]
        sx, sy, sz = int(corner[0]), int(corner[1]), int(corner[2])
        sides = (sx, sy, sz)

        allow_axes = self._resize_active_axes()
        raw_tax = getattr(panel, "thickness_axis", -1)
        if isinstance(raw_tax, str):
            tax = {"X": 0, "Y": 1, "Z": 2}.get(raw_tax.upper(), -1)
        else:
            try:
                tax = int(raw_tax)
            except (TypeError, ValueError):
                tax = -1

        active_axes = [ax for ax in (0, 1, 2) if ax != tax and allow_axes[ax]]

        has_rot = (
            hasattr(panel, "has_rotation")
            and panel.has_rotation()
            and hasattr(panel, "rotate_vector")
        )
        cx_orig = x0 + w * 0.5
        cy_orig = y0 + h * 0.5
        cz_orig = z0 + d * 0.5

        def local_to_world_orig(lx: float, ly: float, lz: float) -> np.ndarray:
            if has_rot:
                rx, ry, rz = panel.rotate_vector(lx - w * 0.5, ly - h * 0.5, lz - d * 0.5)
                return np.array([cx_orig + rx, cy_orig + ry, cz_orig + rz], dtype=float)
            return np.array([x0 + lx, y0 + ly, z0 + lz], dtype=float)

        def dir_to_world(dx: float, dy: float, dz: float) -> np.ndarray:
            if has_rot:
                rx, ry, rz = panel.rotate_vector(dx, dy, dz)
                v = np.array([rx, ry, rz], dtype=float)
            else:
                v = np.array([dx, dy, dz], dtype=float)
            vn = float(np.linalg.norm(v))
            return v / vn if vn > 1e-12 else v

        grab_local = [
            w if sx == 1 else 0.0,
            h if sy == 1 else 0.0,
            d if sz == 1 else 0.0,
        ]
        grab_world = local_to_world_orig(grab_local[0], grab_local[1], grab_local[2])

        axis_worlds: dict[int, np.ndarray] = {}
        fixed_face_pts: dict[int, np.ndarray] = {}
        for ax in active_axes:
            sign = 1.0 if sides[ax] == 1 else -1.0
            ldir = [0.0, 0.0, 0.0]
            ldir[ax] = sign
            u_ax = dir_to_world(ldir[0], ldir[1], ldir[2])
            axis_worlds[ax] = u_ax
            # Точка на противоположной (неподвижной) грани на линии ребра, идущего в grab_world
            fixed_face_pts[ax] = grab_world - dims[ax] * u_ax

        if tax in (0, 1, 2):
            tn = [0.0, 0.0, 0.0]
            tn[tax] = 1.0
            sheet_normal = dir_to_world(tn[0], tn[1], tn[2])
        elif len(active_axes) >= 2:
            c_vec = np.cross(axis_worlds[active_axes[0]], axis_worlds[active_axes[1]])
            cn = float(np.linalg.norm(c_vec))
            sheet_normal = c_vec / cn if cn > 1e-12 else np.array([0.0, 1.0, 0.0], dtype=float)
        else:
            sheet_normal = np.array([0.0, 1.0, 0.0], dtype=float)

        return active_axes, axis_worlds, fixed_face_pts, grab_world, sheet_normal

    def _apply_corner_resize(self, panel: Panel, corner: tuple[int, int, int], new_pt: np.ndarray, live: bool = True) -> None:
        """Растягивает панель за угол `corner = (sx, sy, sz)` по принципу Push-Pull:
        противоположные грани и противоположный угол остаются строго неподвижными в мире."""
        box = self.resize_orig_box
        if box is None:
            box = (panel.x, panel.y, panel.z, panel.width, panel.height, panel.depth)
        x0, y0, z0, w, h, d = [float(v) for v in box]
        min_size = 10.0

        active_axes, axis_worlds, fixed_face_pts, _grab_world, _sheet_normal = (
            self._corner_active_axes_and_dirs(panel, corner, (x0, y0, z0, w, h, d))
        )
        if not active_axes:
            return

        pt = np.asarray(new_pt, dtype=float)
        new_lens: dict[int, float] = {}
        for ax in active_axes:
            raw_len = float(np.dot(pt - fixed_face_pts[ax], axis_worlds[ax]))
            clamped_len = max(min_size, raw_len)
            if self.grid_enabled and self.is_ortho:
                step = max(0.1, float(self.grid_step))
                side = int(corner[ax])
                moving_coord = (
                    ([x0, y0, z0][ax] + clamped_len)
                    if side == 1
                    else ([x0 + w, y0 + h, z0 + d][ax] - clamped_len)
                )
                snapped_coord = round(moving_coord / step) * step
                cand_len = (
                    (snapped_coord - [x0, y0, z0][ax])
                    if side == 1
                    else ([x0 + w, y0 + h, z0 + d][ax] - snapped_coord)
                )
                if cand_len >= min_size:
                    clamped_len = cand_len
            new_lens[ax] = clamped_len

        nx, ny, nz, nw, nh, nd = glmath.compute_corner_push_pull_box(
            (x0, y0, z0, w, h, d),
            corner,
            new_lens,
            panel=panel,
            min_size=min_size,
        )
        panel.x, panel.y, panel.z = nx, ny, nz
        panel.width, panel.height, panel.depth = nw, nh, nd
        if hasattr(panel, "lock_thickness_to_material"):
            panel.lock_thickness_to_material()

        panel.mesh_data = CADKernel.make_aabb_mesh(
            panel.x,
            panel.y,
            panel.z,
            panel.width,
            panel.height,
            panel.depth,
            getattr(panel, "rx", 0.0),
            getattr(panel, "ry", 0.0),
            getattr(panel, "rz", 0.0),
        )
        panel._gl_arrays = None
        panel.geometry_generation = int(getattr(panel, "geometry_generation", 0)) + 1
        panel.geometry_pending = True

    def _apply_corner_push_pull(
        self,
        panel: Panel,
        corner: tuple[int, int, int],
        mx: int,
        my: int,
    ) -> str:
        """Вытягивает угол `corner = (sx, sy, sz)` одновременно вдоль его рабочих торцов в 3D (Push-Pull),
        идентично вытягиванию грани (`_apply_face_push_pull`):
        - Если активна только 1 рабочая ось (например, в 2D-виде с торца) — делегирует `_apply_face_push_pull`;
        - Поддерживает магнитную привязку `🧲` к углам, рёбрам и точкам соседних деталей (или с `[Ctrl]`);
        - Проецирует луч курсора на 3D-плоскость самой плиты через захваченный угол (без начального скачка и без переворота бокса);
        - При скользящем ракурсе камеры проецирует луч на 3D-оси рёбер угла (ближайшая точка скрещивающихся прямых).
        """
        box = self.resize_orig_box
        if box is None:
            box = (panel.x, panel.y, panel.z, panel.width, panel.height, panel.depth)
        x0, y0, z0, w, h, d = [float(v) for v in box]
        min_size = 10.0

        active_axes, axis_worlds, fixed_face_pts, grab_world, sheet_normal = (
            self._corner_active_axes_and_dirs(panel, corner, (x0, y0, z0, w, h, d))
        )
        if not active_axes:
            return ""

        if len(active_axes) == 1:
            ax_only = active_axes[0]
            return self._apply_face_push_pull(panel, (ax_only, int(corner[ax_only])), mx, my)

        # 1. Магнитная привязка к точкам других панелей сцены (если включён «🧲 Магнит» или зажат [Ctrl])
        best_snap_pt, best_snap_label = self._find_magnetic_snap_point(
            mx, my, exclude_panel=panel, base_radius=18.0
        )

        snapped_axes: set[int] = set()
        new_lens: dict[int, float] = {}
        snap_desc = ""

        if best_snap_pt is not None:
            snap_vec = np.asarray(best_snap_pt, dtype=float)
            for ax in active_axes:
                proj_len = float(np.dot(snap_vec - fixed_face_pts[ax], axis_worlds[ax]))
                if proj_len >= min_size:
                    new_lens[ax] = proj_len
                    snapped_axes.add(ax)
            if snapped_axes:
                snap_desc = best_snap_label

        # 2. Точная проекция луча мыши на рабочую плоскость плиты через grab_world
        origin, ray_dir = self._mouse_ray(mx, my)
        v = np.asarray(ray_dir, dtype=float)
        vn = float(np.linalg.norm(v))
        if vn > 1e-12:
            v = v / vn

        hit_pt = self._cursor_on_resize_plane(mx, my, grab_world, plane_normal=sheet_normal)

        for ax in active_axes:
            if ax in snapped_axes:
                continue
            u_ax = axis_worlds[ax]
            f_pt = fixed_face_pts[ax]
            raw_len = float(np.dot(hit_pt - f_pt, u_ax))
            clamped_len = max(min_size, raw_len)

            if not snap_desc and self.grid_enabled and self.is_ortho:
                step = max(0.1, float(self.grid_step))
                side = int(corner[ax])
                moving_coord = (
                    ([x0, y0, z0][ax] + clamped_len)
                    if side == 1
                    else ([x0 + w, y0 + h, z0 + d][ax] - clamped_len)
                )
                snapped_coord = round(moving_coord / step) * step
                cand_len = (
                    (snapped_coord - [x0, y0, z0][ax])
                    if side == 1
                    else ([x0 + w, y0 + h, z0 + d][ax] - snapped_coord)
                )
                if cand_len >= min_size:
                    clamped_len = cand_len

            new_lens[ax] = clamped_len

        nx, ny, nz, nw, nh, nd = glmath.compute_corner_push_pull_box(
            (x0, y0, z0, w, h, d),
            corner,
            new_lens,
            panel=panel,
            min_size=min_size,
        )
        panel.x, panel.y, panel.z = nx, ny, nz
        panel.width, panel.height, panel.depth = nw, nh, nd

        if hasattr(panel, "lock_thickness_to_material"):
            panel.lock_thickness_to_material()

        panel.mesh_data = CADKernel.make_aabb_mesh(
            panel.x,
            panel.y,
            panel.z,
            panel.width,
            panel.height,
            panel.depth,
            getattr(panel, "rx", 0.0),
            getattr(panel, "ry", 0.0),
            getattr(panel, "rz", 0.0),
        )
        panel._gl_arrays = None
        panel.geometry_generation = int(getattr(panel, "geometry_generation", 0)) + 1
        panel.geometry_pending = True
        self.resize_face_snap_desc = snap_desc
        return snap_desc

    def _cursor_on_face_axis(
        self,
        mx: int,
        my: int,
        fixed_pt: np.ndarray,
        axis_dir: np.ndarray,
        panel: Panel,
    ) -> tuple[float, str]:
        """Вычисляет длину детали вдоль `axis_dir` от неподвижного торца `fixed_pt` по положению мыши.

        Поддерживает:
        - Точную проекцию луча камеры на 3D-ось нормали грани (ближайшая точка скрещивающихся прямых);
        - Магнитную привязку к точкам/граням соседних деталей при наведении (или с зажатым `[Ctrl]`).
        """
        u = np.asarray(axis_dir, dtype=float)
        un = float(np.linalg.norm(u))
        if un > 1e-12:
            u = u / un

        # Магнитная привязка к точкам других панелей сцены (если включён «🧲 Магнит» или зажат [Ctrl])
        best_snap_pt, best_snap_label = self._find_magnetic_snap_point(
            mx, my, exclude_panel=panel, base_radius=18.0
        )
        if best_snap_pt is not None:
            proj_len = float(np.dot(np.asarray(best_snap_pt, dtype=float) - fixed_pt, u))
            if proj_len >= 10.0:
                return proj_len, best_snap_label

        # Ближайшая точка на прямой F(s) = fixed_pt + s * u к лучу R(t) = origin + t * ray_dir
        origin, ray_dir = self._mouse_ray(mx, my)
        v = np.asarray(ray_dir, dtype=float)
        vn = float(np.linalg.norm(v))
        if vn > 1e-12:
            v = v / vn
        w0 = np.asarray(fixed_pt, dtype=float) - np.asarray(origin, dtype=float)
        b = float(np.dot(u, v))
        d_dot = float(np.dot(u, w0))
        e_dot = float(np.dot(v, w0))
        denom = 1.0 - b * b
        if denom > 1e-5:
            s = (b * e_dot - d_dot) / denom
            return float(s), ""

        # Fallback, если луч почти параллелен оси грани
        pt_plane = self._cursor_on_resize_plane(mx, my, fixed_pt)
        return float(np.dot(pt_plane - fixed_pt, u)), ""

    def _apply_face_push_pull(
        self,
        panel: Panel,
        face_id: tuple[int, int],
        mx: int,
        my: int,
    ) -> str:
        """Вытягивает грань `face_id = (axis_idx, side)` строго вдоль её нормали в 3D (Push-Pull)."""
        ax_idx, side = face_id
        tax = int(getattr(panel, "thickness_axis", -1))
        if ax_idx == tax:
            return ""

        box = self.resize_orig_box
        if box is None:
            box = (panel.x, panel.y, panel.z, panel.width, panel.height, panel.depth)
        x0, y0, z0, w, h, d = [float(v) for v in box]
        dims = [w, h, d]
        min_size = 10.0

        # Локальный вектор от фиксированной грани к тянущейся грани
        sign = 1.0 if side == 1 else -1.0
        local_dir = [0.0, 0.0, 0.0]
        local_dir[ax_idx] = sign

        # Центр фиксированной (противоположной) грани в локальных координатах исходного бокса
        fixed_local = [w * 0.5, h * 0.5, d * 0.5]
        fixed_local[ax_idx] = 0.0 if side == 1 else dims[ax_idx]

        has_rot = (
            hasattr(panel, "has_rotation")
            and panel.has_rotation()
            and hasattr(panel, "rotate_vector")
        )
        cx_orig = x0 + w * 0.5
        cy_orig = y0 + h * 0.5
        cz_orig = z0 + d * 0.5

        if has_rot:
            rfx, rfy, rfz = panel.rotate_vector(
                fixed_local[0] - w * 0.5,
                fixed_local[1] - h * 0.5,
                fixed_local[2] - d * 0.5,
            )
            fixed_world = np.array([cx_orig + rfx, cy_orig + rfy, cz_orig + rfz], dtype=float)
            rdx, rdy, rdz = panel.rotate_vector(*local_dir)
            axis_world = np.array([rdx, rdy, rdz], dtype=float)
        else:
            fixed_world = np.array(
                [x0 + fixed_local[0], y0 + fixed_local[1], z0 + fixed_local[2]], dtype=float
            )
            axis_world = np.array(local_dir, dtype=float)

        norm_a = float(np.linalg.norm(axis_world))
        if norm_a > 1e-12:
            axis_world = axis_world / norm_a

        raw_len, snap_desc = self._cursor_on_face_axis(mx, my, fixed_world, axis_world, panel)
        new_len = max(min_size, float(raw_len))

        if not snap_desc and self.grid_enabled and self.is_ortho:
            step = max(0.1, float(self.grid_step))
            # Привязываем положение движущегося торца к шагу сетки
            moving_coord = (
                ([x0, y0, z0][ax_idx] + new_len)
                if side == 1
                else ([x0 + w, y0 + h, z0 + d][ax_idx] - new_len)
            )
            snapped_coord = round(moving_coord / step) * step
            cand_len = (
                (snapped_coord - [x0, y0, z0][ax_idx])
                if side == 1
                else ([x0 + w, y0 + h, z0 + d][ax_idx] - snapped_coord)
            )
            if cand_len >= min_size:
                new_len = cand_len

        new_dims = [w, h, d]
        new_dims[ax_idx] = new_len

        if has_rot:
            # Центр новой детали отстоит от фиксированной грани на new_len * 0.5 вдоль axis_world
            center_new = fixed_world + axis_world * (new_len * 0.5)
            panel.width, panel.height, panel.depth = new_dims[0], new_dims[1], new_dims[2]
            panel.x = float(center_new[0]) - panel.width * 0.5
            panel.y = float(center_new[1]) - panel.height * 0.5
            panel.z = float(center_new[2]) - panel.depth * 0.5
        else:
            coords = [x0, y0, z0]
            if side == 0:
                coords[ax_idx] = (coords[ax_idx] + dims[ax_idx]) - new_len
            panel.x, panel.y, panel.z = coords[0], coords[1], coords[2]
            panel.width, panel.height, panel.depth = new_dims[0], new_dims[1], new_dims[2]

        if hasattr(panel, "lock_thickness_to_material"):
            panel.lock_thickness_to_material()

        panel.mesh_data = CADKernel.make_aabb_mesh(
            panel.x,
            panel.y,
            panel.z,
            panel.width,
            panel.height,
            panel.depth,
            getattr(panel, "rx", 0.0),
            getattr(panel, "ry", 0.0),
            getattr(panel, "rz", 0.0),
        )
        panel._gl_arrays = None
        panel.geometry_generation = int(getattr(panel, "geometry_generation", 0)) + 1
        panel.geometry_pending = True
        self.resize_face_snap_desc = snap_desc
        return snap_desc

    def _draw_resize_handles(self, painter: QPainter):
        """Отрисовывает:
        - Оранжевые ромбики без заливки в центрах торцов («Тянуть грань в 3D» / Push-Pull)
          — тот же стиль, что у угловых точек и Ctrl-магнита;
        - Оранжевые ромбы углов панели с подсветкой прилегающих рабочих граней и векторов вытягивания.
        """
        if self.drag_mode or self.fastener_mode or self.measure_mode:
            return
        panels = self.get_selected_panels()
        if not panels:
            return
        self._sync_viewport_matrices()
        orange = QColor(249, 115, 22)

        for p in panels:
            # 1. Торцевые ручки «Тянуть грань в 3D» (Push-Pull) — оранжевые ромбики без заливки
            for face_id, wpt, wnrm, label in self._panel_face_handles(p):
                scr = self._project_to_screen(wpt)
                if scr is None:
                    continue
                sx, sy = int(round(scr[0])), int(round(scr[1]))
                hover = self.resize_hover_face == face_id and self.resize_panel is p
                active = self.resize_mode and self.resize_face == face_id and self.resize_panel is p

                # При наведении или вытягивании — контур грани и ось (тонкий оранжевый акцент)
                if hover or active:
                    fcorners = self._panel_face_corners_world(p, face_id)
                    scr_pts = []
                    for fc in fcorners:
                        sp = self._project_to_screen(fc)
                        if sp is not None:
                            scr_pts.append(QPoint(int(round(sp[0])), int(round(sp[1]))))
                    if len(scr_pts) == 4:
                        painter.setPen(QPen(orange, 2.0 if active else 1.6, Qt.PenStyle.SolidLine))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawPolygon(scr_pts)

                    tip_world = wpt + wnrm * 42.0
                    scr_tip = self._project_to_screen(tip_world)
                    if scr_tip is not None:
                        tx, ty = int(round(scr_tip[0])), int(round(scr_tip[1]))
                        painter.setPen(QPen(orange, 1.8))
                        painter.drawLine(sx, sy, tx, ty)
                        # Кончик оси — маленький ромб без заливки
                        tip_r = 4
                        tip_poly = [
                            QPoint(tx, ty - tip_r),
                            QPoint(tx + tip_r, ty),
                            QPoint(tx, ty + tip_r),
                            QPoint(tx - tip_r, ty),
                        ]
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawPolygon(tip_poly)

                # Точка захвата — оранжевый ромбик без заливки (как у углов)
                r = 10 if active else (9 if hover else 8)
                poly = [
                    QPoint(sx, sy - r),
                    QPoint(sx + r, sy),
                    QPoint(sx, sy + r),
                    QPoint(sx - r, sy),
                ]
                if active:
                    painter.setPen(QPen(orange, 2.4))
                elif hover:
                    painter.setPen(QPen(orange, 2.2))
                else:
                    painter.setPen(QPen(orange, 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(poly)

            # 2. Угловые ручки — оранжевые ромбы (с подсветкой рабочих граней и осей Push-Pull)
            for corner, wpt in self._panel_corners(p):
                scr = self._project_to_screen(wpt)
                if scr is None:
                    continue
                sx, sy = int(round(scr[0])), int(round(scr[1]))
                hover = self.resize_hover_corner == corner and self.resize_panel is p
                active = self.resize_mode and self.resize_corner == corner and self.resize_panel is p

                if hover or active:
                    cur_box = (
                        float(p.x), float(p.y), float(p.z),
                        float(p.width), float(p.height), float(p.depth),
                    )
                    act_axes, ax_worlds, _f_pts, _g_w, _s_n = self._corner_active_axes_and_dirs(
                        p, corner, cur_box
                    )
                    for ax_idx in act_axes:
                        fcorners = self._panel_face_corners_world(p, (ax_idx, int(corner[ax_idx])))
                        scr_pts = []
                        for fc in fcorners:
                            sp = self._project_to_screen(fc)
                            if sp is not None:
                                scr_pts.append(QPoint(int(round(sp[0])), int(round(sp[1]))))
                        if len(scr_pts) == 4:
                            painter.setPen(QPen(orange, 2.0 if active else 1.5, Qt.PenStyle.SolidLine))
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawPolygon(scr_pts)

                        wnrm = ax_worlds[ax_idx]
                        tip_world = wpt + wnrm * 38.0
                        scr_tip = self._project_to_screen(tip_world)
                        if scr_tip is not None:
                            tx, ty = int(round(scr_tip[0])), int(round(scr_tip[1]))
                            painter.setPen(QPen(orange, 1.8))
                            painter.drawLine(sx, sy, tx, ty)
                            tip_r = 4
                            tip_poly = [
                                QPoint(tx, ty - tip_r),
                                QPoint(tx + tip_r, ty),
                                QPoint(tx, ty + tip_r),
                                QPoint(tx - tip_r, ty),
                            ]
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawPolygon(tip_poly)

                r = 10 if active else (9 if hover else 8)
                poly = [
                    QPoint(sx, sy - r),
                    QPoint(sx + r, sy),
                    QPoint(sx, sy + r),
                    QPoint(sx - r, sy),
                ]
                # Единый стиль: контур без заливки (как Ctrl-магнит и торцы)
                if active:
                    painter.setPen(QPen(orange, 2.4))
                elif hover:
                    painter.setPen(QPen(orange, 2.2))
                else:
                    painter.setPen(QPen(orange, 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(poly)

    def _pick_closest_resize_or_face_handle(self, mx: int, my: int, panel: Panel | None = None):
        """Выбирает ближайшую к курсору `(mx, my)` ручку — торец (`face`) или угол (`corner`),
        чтобы на узких деталях ручка центра грани не перехватывала клик у угла."""
        face_hit = self._find_face_handle(mx, my, panel=panel)
        corner_hit = self._find_resize_handle(mx, my, panel=panel)
        if face_hit is not None and corner_hit is not None:
            f_scr = self._project_to_screen(face_hit[2])
            c_scr = self._project_to_screen(corner_hit[2])
            d_f = math.hypot(f_scr[0] - mx, f_scr[1] - my) if f_scr is not None else float("inf")
            d_c = math.hypot(c_scr[0] - mx, c_scr[1] - my) if c_scr is not None else float("inf")
            if d_c <= d_f:
                return ("corner", corner_hit)
            return ("face", face_hit)
        if face_hit is not None:
            return ("face", face_hit)
        if corner_hit is not None:
            return ("corner", corner_hit)
        return None

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse_pos = event.pos()
        self.press_pos = event.pos()
        self.is_dragging = False
        self.selection_crossing = False

        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_press_pos = QPoint(event.pos())
            self._middle_did_drag = False

        if event.button() == Qt.MouseButton.RightButton:
            self._right_press_pos = QPoint(event.pos())
            self._right_did_drag = False

        if event.button() == Qt.MouseButton.LeftButton:
            # ViewCube: захват для клика (грань/ребро/угол/Home) или вращения перетаскиванием куба
            if self._begin_viewcube_interaction(event.pos().x(), event.pos().y()):
                return
            # Точка привязки после Ctrl+C
            if self.clipboard_await_anchor and self.clipboard is not None:
                pt, desc = self._find_target_snap_point(event.pos().x(), event.pos().y())
                if pt is None:
                    pt = self._ray_hit_workplane(event.pos().x(), event.pos().y())
                if pt is not None:
                    set_anchor(self.clipboard, float(pt[0]), float(pt[1]), float(pt[2]))
                    self.clipboard_await_anchor = False
                    self.fastener_message.emit(
                        f"📋 Точка привязки: {desc if desc else 'точка'} "
                        f"({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}) — Ctrl+V для вставки"
                    )
                    self.update()
                return

            # Размещение копии
            if self.paste_mode and self.clipboard is not None:
                pt = self.paste_target_point
                if pt is None:
                    pt, _ = self._find_target_snap_point(event.pos().x(), event.pos().y())
                if pt is None:
                    pt = self._ray_hit_workplane(event.pos().x(), event.pos().y())
                if pt is not None:
                    self._place_clipboard_at(pt)
                return

            # Вытягивание торца в 3D (Push-Pull) или растягивание за угол выделенной панели
            if not self.drag_mode and not self.fastener_mode and not self.measure_mode and not self.paste_mode:
                picked = self._pick_closest_resize_or_face_handle(event.pos().x(), event.pos().y())
                if picked is not None:
                    kind, payload = picked
                    if kind == "face":
                        panel, face_id, _wpt, _wnrm, label = payload
                        self.resize_mode = True
                        self.resize_panel = panel
                        self.resize_face = face_id
                        self.resize_corner = None
                        self.resize_face_snap_desc = ""
                        self.resize_orig_box = (
                            float(panel.x), float(panel.y), float(panel.z),
                            float(panel.width), float(panel.height), float(panel.depth),
                        )
                        self.selecting_rect = None
                        self.fastener_message.emit(
                            f"↔ Вытягивание [{panel.name}] — {label} | Наведите на деталь для магнита | Esc — отмена"
                        )
                        self.update()
                        return
                    else:
                        panel, corner, _wpt = payload
                        self.resize_mode = True
                        self.resize_panel = panel
                        self.resize_corner = corner
                        self.resize_face = None
                        self.resize_face_snap_desc = ""
                        self.resize_orig_box = (
                            float(panel.x), float(panel.y), float(panel.z),
                            float(panel.width), float(panel.height), float(panel.depth),
                        )
                        self.selecting_rect = None
                        self.fastener_message.emit(
                            f"↔ Вытягивание угла [{panel.name}] | Наведите на деталь для магнита | Esc — отмена"
                        )
                        self.update()
                        return
            if self.is_ortho and not self.drag_mode:
                self.selecting_rect = QRect(event.pos(), event.pos())

    def mouseMoveEvent(self, event):
        dx = event.pos().x() - self.last_mouse_pos.x()
        dy = event.pos().y() - self.last_mouse_pos.y()

        # Перетаскивание самого ViewCube мышью (плавное вращение камеры вокруг 3D-pivot)
        if self._vc_press_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            from ui.viewcube import pan_for_pivot

            drag_dist = math.hypot(
                event.pos().x() - self._vc_press_pos.x(),
                event.pos().y() - self._vc_press_pos.y(),
            )
            if drag_dist > 4.0 or self._vc_dragging:
                self._vc_dragging = True
                if self._view_anim_timer.isActive():
                    self._view_anim = None
                    self._view_anim_timer.stop()
                self.rot_x = max(-89.9, min(89.9, float(self.rot_x) + dy * 0.65))
                self.rot_y = float(self.rot_y) + dx * 0.65
                piv = self._vc_pivot or self._focus_reference_point()
                self.pan_x, self.pan_y = pan_for_pivot(self.rot_x, self.rot_y, piv)
                self._focus_pivot = piv
                self.view_name = "custom"
                try:
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                except Exception as exc:
                    _log.debug("Cursor update failed: %s", exc)
                self.update()
            self.last_mouse_pos = event.pos()
            return

        # Hover ViewCube (без зажатых кнопок)
        if not event.buttons():
            self._update_viewcube_hover(event.pos().x(), event.pos().y())

        if event.buttons() & Qt.MouseButton.MiddleButton:
            if abs(dx) > 2 or abs(dy) > 2:
                self._middle_did_drag = True

        if event.buttons() & Qt.MouseButton.RightButton:
            if abs(dx) > 2 or abs(dy) > 2:
                self._right_did_drag = True

        if self.resize_mode and self.resize_panel is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.is_dragging = True
                self.ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                p = self.resize_panel
                if self.resize_face is not None:
                    snap_desc = self._apply_face_push_pull(
                        p, self.resize_face, event.pos().x(), event.pos().y()
                    )
                    self.coordinates_changed.emit(p.x, p.y, p.z)
                    snap_suffix = f" | {snap_desc}" if snap_desc else ""
                    self.fastener_message.emit(
                        f"↔ Грань [{p.name}]: {p.width:.1f} × {p.height:.1f} × {p.depth:.1f} мм{snap_suffix}"
                    )
                    self.update()
                elif self.resize_corner is not None:
                    snap_desc = self._apply_corner_push_pull(
                        p, self.resize_corner, event.pos().x(), event.pos().y()
                    )
                    self.coordinates_changed.emit(p.x, p.y, p.z)
                    snap_suffix = f" | {snap_desc}" if snap_desc else ""
                    self.fastener_message.emit(
                        f"↔ Угол [{p.name}]: {p.width:.1f} × {p.height:.1f} × {p.depth:.1f} мм{snap_suffix}"
                    )
                    self.update()
            self.last_mouse_pos = event.pos()
            return

        # Hover ручек торцов (Push-Pull) и углов размера
        if not self.drag_mode and not self.fastener_mode and not self.measure_mode:
            picked = self._pick_closest_resize_or_face_handle(event.pos().x(), event.pos().y())
            if picked is not None:
                kind, payload = picked
                if kind == "face":
                    new_panel, new_face = payload[0], payload[1]
                    new_corner = None
                else:
                    new_panel, new_corner = payload[0], payload[1]
                    new_face = None
            else:
                new_panel = None
                new_face = None
                new_corner = None

            if (
                new_face != self.resize_hover_face
                or new_corner != self.resize_hover_corner
                or (new_panel is not self.resize_panel and not self.resize_mode)
            ):
                self.resize_hover_face = new_face
                self.resize_hover_corner = new_corner
                if not self.resize_mode:
                    self.resize_panel = new_panel
                self.update()

        # Hover 3D-отверстий (для подсветки группы стыка/ассоциации и навигации)
        if not event.buttons():
            self._update_hole_hover(event.pos().x(), event.pos().y())

        if self.paste_mode and self.clipboard is not None and self.clipboard.anchor is not None:
            raw, desc = self._find_target_snap_point(event.pos().x(), event.pos().y())
            if raw is None:
                raw = self._ray_hit_workplane(event.pos().x(), event.pos().y())
            if raw is not None:
                is_mag_snap = bool(desc and desc.startswith("🧲"))
                snapped = (
                    raw
                    if is_mag_snap
                    else (self._snap_point_to_grid(raw) if hasattr(self, "_snap_point_to_grid") else raw)
                )
                self.paste_target_point = snapped
                ax = self.clipboard.anchor
                d = snapped - np.asarray(ax, dtype=float)
                snap_str = f" | {desc}" if is_mag_snap else ""
                self.fastener_message.emit(
                    f"📋 Вставка Δ ({d[0]:.1f}, {d[1]:.1f}, {d[2]:.1f}){snap_str} | клик — поставить, Esc — отмена"
                )
            self.update()
            return

        if self.drag_mode:
            if self.drag_stage == 1:
                self.drag_hover_point, self.drag_hover_desc = self._find_base_snap_point(event.pos().x(), event.pos().y())
                msg = f"Точка зацепа: [{self.drag_hover_desc}] ({self.drag_hover_point[0]:.1f}, {self.drag_hover_point[1]:.1f}, {self.drag_hover_point[2]:.1f}) | ЛКМ — начать, Esc — отмена"
                self.fastener_message.emit(msg)
                self.update()
            elif self.drag_stage == 2:
                raw_target, self.drag_target_desc = self._find_target_snap_point(event.pos().x(), event.pos().y())
                if self.drag_base_point is not None and raw_target is not None and self.drag_panel is not None:
                    delta = self._apply_axis_lock(raw_target - self.drag_base_point)
                    is_mag_snap = bool(self.drag_target_desc and self.drag_target_desc.startswith("🧲"))
                    self.drag_face_snap_desc = self.drag_target_desc if is_mag_snap else ""
                    target = self.drag_base_point + delta
                    if not is_mag_snap:
                        snapped = self._snap_point_to_grid(target)
                        delta = snapped - self.drag_base_point
                        target = snapped
                    self.drag_target_point = target
                    dist = float(np.linalg.norm(delta))
                    axis_str = f" | ось [{self.drag_axis_lock}]" if self.drag_axis_lock else " | X/Y/Z — ось"
                    grid_str = ""
                    if self.grid_enabled and self.is_ortho and not is_mag_snap:
                        grid_str = f" | сетка {self.grid_step:g} мм"
                    msg = (
                        f"📍 ΔX={delta[0]:+.1f} ΔY={delta[1]:+.1f} ΔZ={delta[2]:+.1f} "
                        f"(L={dist:.1f}) | {self.drag_target_desc}{grid_str}{axis_str} | ЛКМ — OK"
                    )
                    self.fastener_message.emit(msg)
                self.update()

            if not (event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton)):
                self.last_mouse_pos = event.pos()
                return

        ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self.ctrl_held = ctrl_held

        if self.measure_mode or ctrl_held:
            self._update_measure_hover(event.pos().x(), event.pos().y(), ctrl_held=ctrl_held)
            if self.measure_mode and not (event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton | Qt.MouseButton.LeftButton)):
                self.last_mouse_pos = event.pos()
                return
        elif not self.measure_mode and getattr(self, "measure_snap_info", None) is not None:
            self.measure_snap_info = None
            self.measure_is_magnetic = False
            self.update()

        if self.fastener_mode and self.fastener_joint is not None:
            if not (event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton)):
                self._update_fastener_preview(event.pos().x(), event.pos().y())
                self.last_mouse_pos = event.pos()
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    return

        if event.buttons() & Qt.MouseButton.LeftButton:
            self.is_dragging = True
            if self.fastener_mode or self.measure_mode or self.drag_mode:
                self.last_mouse_pos = event.pos()
                return
            if self.is_ortho and self.selecting_rect is not None:
                self.selecting_rect = QRect(self.press_pos, event.pos())
                self.selection_crossing = event.pos().x() < self.press_pos.x()
                self.update()
            else:
                self.rot_x += dy * 0.5
                self.rot_y += dx * 0.5
                self.update()
        elif event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
            from ui.viewcube import pivot_from_pan

            # Панорама пропорциональна масштабу вида: далеко — быстрее, близко — точнее
            sp = self._pan_speed_per_pixel()
            self.pan_x += dx * sp
            self.pan_y -= dy * sp
            self._focus_pivot = pivot_from_pan(
                self.rot_x, self.rot_y, self.pan_x, self.pan_y, self._focus_reference_point()
            )
            self.update()

        self.last_mouse_pos = event.pos()

    def _begin_viewcube_interaction(self, mx: int, my: int) -> bool:
        """Начало взаимодействия с ViewCube (клик или перетаскивание куба мышью)."""
        from ui.viewcube import (
            build_drawable,
            hit_test,
            is_in_viewcube_region,
            layout_for_widget,
            pivot_from_pan,
        )

        layout = layout_for_widget(max(1, self.width()), max(1, self.height()))
        if not is_in_viewcube_region(float(mx), float(my), layout):
            return False
        drawable = build_drawable(float(self.rot_x), float(self.rot_y), layout)
        hit = hit_test(float(mx), float(my), drawable, layout)
        if hit is None:
            return False
        self._vc_press_pos = QPoint(int(mx), int(my))
        self._vc_press_hit = hit
        self._vc_dragging = False
        self._vc_pivot = pivot_from_pan(
            float(self.rot_x),
            float(self.rot_y),
            float(self.pan_x),
            float(self.pan_y),
            self._focus_reference_point(),
        )
        return True

    def _apply_viewcube_hit(self, hit: tuple[str, str]) -> bool:
        """Применяет клик по элементу ViewCube (грань / ребро / угол / Home)."""
        from ui.viewcube import target_for_hit

        kind, key = hit
        if kind == "home":
            self.go_home_view(animate=True)
            self.fastener_message.emit("⌂ Вид: Домой (изометрия)")
            return True
        rx, ry, ortho, label = target_for_hit(kind, key)
        self.view_name = key if kind == "face" else "custom"
        self.animate_camera_to(rx, ry, is_ortho=ortho)
        self.fastener_message.emit(f"🧭 Вид: {label}")
        return True

    def _try_viewcube_click(self, mx: int, my: int) -> bool:
        """Прямой клик по ViewCube: грань / ребро / угол / Home. True если обработано."""
        from ui.viewcube import build_drawable, hit_test, is_in_viewcube_region, layout_for_widget

        layout = layout_for_widget(max(1, self.width()), max(1, self.height()))
        if not is_in_viewcube_region(float(mx), float(my), layout):
            return False
        drawable = build_drawable(float(self.rot_x), float(self.rot_y), layout)
        hit = hit_test(float(mx), float(my), drawable, layout)
        if hit is None:
            return False
        return self._apply_viewcube_hit(hit)

    def _update_viewcube_hover(self, mx: int, my: int) -> None:
        from ui.viewcube import build_drawable, hit_test, is_in_viewcube_region, layout_for_widget

        layout = layout_for_widget(max(1, self.width()), max(1, self.height()))
        if not is_in_viewcube_region(float(mx), float(my), layout):
            if self._viewcube_hover is not None:
                self._viewcube_hover = None
                if not (self.drag_mode or self.fastener_mode or self.measure_mode or self.resize_mode):
                    try:
                        self.unsetCursor()
                    except Exception as exc:
                        _log.debug("Unset cursor failed: %s", exc)
                self.update()
            return
        drawable = build_drawable(float(self.rot_x), float(self.rot_y), layout)
        hit = hit_test(float(mx), float(my), drawable, layout)
        if hit != self._viewcube_hover:
            self._viewcube_hover = hit
            if not (self.drag_mode or self.fastener_mode or self.measure_mode or self.resize_mode):
                try:
                    if hit is not None:
                        self.setCursor(Qt.CursorShape.PointingHandCursor)
                    else:
                        self.unsetCursor()
                except Exception as exc:
                    _log.debug("Set cursor failed: %s", exc)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._vc_press_pos is not None:
            was_drag = self._vc_dragging
            hit = self._vc_press_hit
            self._vc_press_pos = None
            self._vc_press_hit = None
            self._vc_dragging = False
            self._vc_pivot = None
            try:
                if self._viewcube_hover is not None:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    self.unsetCursor()
            except Exception as exc:
                _log.debug("Cursor restore failed: %s", exc)
            if not was_drag and hit is not None:
                self._apply_viewcube_hit(hit)
            self.is_dragging = False
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            # Короткий клик СКМ — плавный фокус на точку детали (или плоскости сцены) под курсором
            if self._middle_press_pos is not None and not self._middle_did_drag:
                click_dist = math.hypot(
                    event.pos().x() - self._middle_press_pos.x(),
                    event.pos().y() - self._middle_press_pos.y(),
                )
                if click_dist < 8.0:
                    try:
                        self._sync_viewport_matrices()
                        pt = self._cursor_focus_point(event.pos().x(), event.pos().y())
                        piv = (float(pt[0]), float(pt[1]), float(pt[2]))
                        self.animate_camera_to(
                            float(self.rot_x),
                            float(self.rot_y),
                            is_ortho=self.is_ortho,
                            target_pivot=piv,
                        )
                        self.fastener_message.emit(
                            f"Фокус на точку ({piv[0]:.0f}, {piv[1]:.0f}, {piv[2]:.0f}) мм"
                        )
                    except Exception as exc:
                        _log.debug("Middle-click focus failed: %s", exc)
            self._middle_press_pos = None
            self._middle_did_drag = False

        if event.button() == Qt.MouseButton.RightButton:
            if self.drag_mode:
                self.cancel_drag_mode()
                self.is_dragging = False
                self._right_press_pos = None
                self._right_did_drag = False
                return
            # Короткий ПКМ без перетаскивания по отверстию -> контекстное меню навигации
            if (
                self._right_press_pos is not None
                and not self._right_did_drag
                and self._can_pick_hole_in_current_mode()
            ):
                rdist = math.hypot(
                    event.pos().x() - self._right_press_pos.x(),
                    event.pos().y() - self._right_press_pos.y(),
                )
                if rdist < 6.0:
                    hit = self.pick_hole_at_screen(event.pos().x(), event.pos().y())
                    if hit is not None:
                        self._right_press_pos = None
                        self._right_did_drag = False
                        self.is_dragging = False
                        self._show_hole_context_menu(hit, event.globalPosition().toPoint())
                        return
            self._right_press_pos = None
            self._right_did_drag = False

        if event.button() == Qt.MouseButton.LeftButton:
            click_dist = math.hypot(event.pos().x() - self.press_pos.x(), event.pos().y() - self.press_pos.y())
            is_click = click_dist < 8.0

            if self.resize_mode and self.resize_panel is not None:
                p = self.resize_panel
                old_box = self.resize_orig_box
                new_box = (
                    float(p.x), float(p.y), float(p.z),
                    float(p.width), float(p.height), float(p.depth),
                )
                self.resize_mode = False
                self.resize_corner = None
                self.resize_face = None
                self.resize_face_snap_desc = ""
                self.resize_orig_box = None
                if old_box is not None and any(abs(a - b) > 1e-6 for a, b in zip(old_box, new_box)):
                    # уже применено live — только записать в undo
                    cmd = ResizePanelCommand(p, old_box, new_box)
                    self.undo_stack.push(cmd, execute=False)
                    p.rebuild_geometry()
                    self.coordinates_changed.emit(p.x, p.y, p.z)
                    self.scene_structure_changed.emit()
                    self.panel_clicked.emit(p)
                    self.fastener_message.emit(
                        f"✅ Размер [{p.name}]: {p.width:.1f} × {p.height:.1f} × {p.depth:.1f} мм"
                    )
                self.update()
                self.is_dragging = False
                return

            if self.drag_mode:
                if self.drag_stage == 1 and is_click:
                    # ОДНОКРАТНЫЙ КЛИК ЛКМ по точке за которую тащим деталь:
                    if self.drag_hover_point is not None:
                        self.drag_base_point = np.copy(self.drag_hover_point)
                        self.drag_base_desc = self.drag_hover_desc
                    else:
                        base_pt, base_desc = self._find_base_snap_point(event.pos().x(), event.pos().y())
                        self.drag_base_point = np.copy(base_pt)
                        self.drag_base_desc = base_desc

                    self.drag_target_point = np.copy(self.drag_base_point)
                    self.drag_target_desc = "Начальное положение"
                    self.drag_stage = 2  # ПОСЛЕ ОДНОКРАТНОГО КЛИКА ПАНЕЛЬ СРАЗУ СЛЕДУЕТ ЗА КУРСОРОМ!

                    msg = f"[{self.drag_panel.name}] перемещение (зацеп: {self.drag_base_desc}) | ЛКМ — зафиксировать | [Ctrl] — магнит | Esc/ПКМ — отмена"
                    self.fastener_message.emit(msg)
                    self.update()
                    self.is_dragging = False
                    return
                elif self.drag_stage == 2 and is_click:
                    # ВТОРОЙ ОДНОКРАТНЫЙ КЛИК ЛКМ: фиксируем с учётом оси + проверка коллизий
                    if self.drag_base_point is not None and self.drag_target_point is not None and self.drag_panel is not None:
                        delta = self._apply_axis_lock(self.drag_target_point - self.drag_base_point)
                        old_xyz = self.drag_orig_pos
                        new_xyz = (old_xyz[0] + float(delta[0]), old_xyz[1] + float(delta[1]), old_xyz[2] + float(delta[2]))
                        moved = self.drag_panel
                        cmd = MovePanelCommand(moved, old_xyz, new_xyz)
                        self.undo_stack.push(cmd, execute=True)
                        self.coordinates_changed.emit(moved.x, moved.y, moved.z)
                        self.scene_structure_changed.emit()
                        self.panel_clicked.emit(moved)
                        hits = self._check_panel_collisions(moved)
                        if hits:
                            names = ", ".join(f"{p.name} ({int(v)} мм³)" for p, v in hits[:4])
                            msg = f"⚠️ '{moved.name}' на ({new_xyz[0]:.1f}, {new_xyz[1]:.1f}, {new_xyz[2]:.1f}) — пересечение: {names}"
                            for p, _v in hits:
                                p.selected = True
                            moved.selected = True
                        else:
                            msg = f"✅ '{moved.name}' зафиксирована: ({new_xyz[0]:.1f}, {new_xyz[1]:.1f}, {new_xyz[2]:.1f})"
                        self.fastener_message.emit(msg)
                        self.cancel_drag_mode(quiet=True)
                        self.update()
                        self.is_dragging = False
                        return

            if self.ctrl_held and not self.measure_mode and not self.is_dragging and getattr(self, "measure_snap_panel", None) is not None:
                snap_panel = self.measure_snap_panel
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if not shift:
                    for b in self.blocks:
                        b.selected = False
                        for p in b.panels:
                            p.selected = False
                snap_panel.selected = True
                self.coordinates_changed.emit(snap_panel.x, snap_panel.y, snap_panel.z)
                self.panel_clicked.emit(snap_panel)
                self.update()
                self.is_dragging = False
                return

            if self.measure_mode and not self.is_dragging:
                ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) or self.ctrl_held
                self._handle_measure_click(event.pos().x(), event.pos().y(), ctrl_held=ctrl_held)
                self.is_dragging = False
                return

            if self.fastener_mode and self.fastener_joint is not None:
                self._place_fastener_at_preview()
                self.is_dragging = False
                return

            if self.is_ortho and self.selecting_rect is not None and not self.fastener_pick_second:
                r = self.selecting_rect.normalized()
                # Рамка ≥ 8px — рамочное выделение; иначе обычный клик
                if not is_click and (r.width() >= 8 or r.height() >= 8):
                    self._select_panels_in_rect(r)
                    self.selecting_rect = None
                    self.selection_crossing = False
                    self.update()
                    self.is_dragging = False
                    return
                self.selecting_rect = None
                self.selection_crossing = False

            # is_click: даже если is_dragging=True из-за дрожания мыши — выделяем кликом
            if is_click or not self.is_dragging or self.fastener_pick_second:
                # Alt+клик ЛКМ по отверстию — мгновенный переход к стыку / ассоциации
                if (
                    is_click
                    and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
                    and self._can_pick_hole_in_current_mode()
                ):
                    hit = self.pick_hole_at_screen(event.pos().x(), event.pos().y())
                    if hit is not None:
                        self._navigate_to_hole_hit(hit)
                        self.is_dragging = False
                        return

                self._sync_viewport_matrices()
                clicked_panel = self._pick_panel_raycast(event.pos().x(), event.pos().y())

                if self.fastener_pick_second and self.fastener_anchor is not None:
                    if clicked_panel is not None and clicked_panel is not self.fastener_anchor:
                        msg = self._activate_joint_mode(
                            self.fastener_anchor, clicked_panel,
                            self.fastener_diameter, self.fastener_depth,
                        )
                        if msg != "OK":
                            self.fastener_message.emit(msg)
                        else:
                            self.fastener_message.emit(
                                "Крепёж: водите мышью по стыку, ЛКМ — поставить, Esc — выход"
                            )
                        self.panel_clicked.emit(clicked_panel)
                        self.is_dragging = False
                        self.update()
                        return
                    self.is_dragging = False
                    return

                self._active_hole_owner = None
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

                if not shift:
                    for b in self.blocks:
                        b.selected = False
                        for p in b.panels:
                            p.selected = False

                if clicked_panel:
                    if shift and clicked_panel.selected:
                        clicked_panel.selected = False
                    else:
                        clicked_panel.selected = True
                    self.coordinates_changed.emit(clicked_panel.x, clicked_panel.y, clicked_panel.z)

                self.panel_clicked.emit(clicked_panel)
                self.update()

        self.is_dragging = False

    def mouseDoubleClickEvent(self, event):
        """Двойной клик ЛКМ по отверстию в 3D — переход к породившему стыку или ассоциации."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._can_pick_hole_in_current_mode()
            and self._viewcube_hover is None
        ):
            hit = self.pick_hole_at_screen(event.pos().x(), event.pos().y())
            if hit is not None:
                self._navigate_to_hole_hit(hit)
                return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        has_rect = (
            self.selecting_rect is not None
            and self.selecting_rect.normalized().width() >= 2
            and self.selecting_rect.normalized().height() >= 2
        )
        has_dims = bool(self.dimensions) or self.measure_mode
        has_drag = self.drag_mode
        has_snap = bool(getattr(self, "ctrl_held", False) and getattr(self, "measure_snap_info", None) is not None)
        has_handles = bool(self.get_selected_panels()) and not self.drag_mode
        # ViewCube всегда рисуем
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if has_dims or has_snap:
            self._draw_dimensions_overlay(painter)

        if has_drag:
            self._draw_drag_overlay(painter)

        if has_handles:
            self._draw_resize_handles(painter)

        if self._hovered_hole is not None and self._can_pick_hole_in_current_mode():
            self._draw_hole_hover_overlay(painter)

        try:
            from ui.viewcube import draw_viewcube

            self._viewcube_drawable = draw_viewcube(
                painter,
                float(self.rot_x),
                float(self.rot_y),
                max(1, self.width()),
                max(1, self.height()),
                hover=self._viewcube_hover,
            )
        except Exception as exc:
            _log.debug("ViewCube draw failed: %s", exc)

        if has_rect:
            r = self.selecting_rect.normalized()
            if self.selection_crossing:
                pen = QPen(QColor(0, 160, 0), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QColor(0, 160, 0, 40))
            else:
                pen = QPen(QColor(0, 120, 215), 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.setBrush(QColor(0, 120, 215, 40))
            painter.drawRect(r)

        painter.end()

    def _select_panels_in_rect(self, rect: QRect):
        """
        Рамковое выделение:
        - слева направо: полное вхождение;
        - справа налево: пересечение.
        """
        dpr = float(self.devicePixelRatioF())
        vp = self._vp_size
        is_crossing = self.selection_crossing
        mvp = self._mvp

        for b in self.blocks:
            b.selected = False
            for p in b.panels:
                p.selected = False

        found_any = None
        for block in self.blocks:
            for p in block.panels:
                if hasattr(p, "world_corners"):
                    corners = p.world_corners()
                else:
                    x2, y2, z2 = p.x + p.width, p.y + p.height, p.z + p.depth
                    corners = [
                        (p.x, p.y, p.z), (x2, p.y, p.z), (x2, y2, p.z), (p.x, y2, p.z),
                        (p.x, p.y, z2), (x2, p.y, z2), (x2, y2, z2), (p.x, y2, z2)
                    ]
                inside_count = 0
                total_corners = len(corners)
                for cx, cy, cz in corners:
                    try:
                        wx, wy, _wz = glmath.project(cx, cy, cz, mvp, vp)
                        screen_x = wx / dpr
                        screen_y = (vp[3] - wy) / dpr
                        if rect.contains(int(screen_x), int(screen_y)):
                            inside_count += 1
                    except Exception as exc:
                        _log.debug("Ошибка проекции вершины при выделении рамкой: %s", exc)

                if is_crossing:
                    selected_condition = inside_count > 0
                else:
                    selected_condition = inside_count == total_corners

                if selected_condition:
                    p.selected = True
                    found_any = p

        self.panel_clicked.emit(found_any)

    def _pick_panel_raycast(self, mouse_x: int, mouse_y: int):
        origin, ray_dir = self._mouse_ray(mouse_x, mouse_y)
        plane = self.current_section_plane()
        focus_set = self._get_focus_panels_set() if self.ghost_others_mode else set()
        has_ghosts = bool(self.ghost_others_mode and focus_set)

        closest_opaque = None
        min_t_opaque = float("inf")
        closest_ghost = None
        min_t_ghost = float("inf")

        for block in self.blocks:
            for p in block.panels:
                t_hit = self._intersect_ray_panel(origin, ray_dir, p)
                if t_hit is None:
                    continue
                hit_pt = origin + t_hit * ray_dir
                if plane is not None and not glmath.point_passes_clip_plane(
                    float(hit_pt[0]), float(hit_pt[1]), float(hit_pt[2]), plane
                ):
                    continue
                if has_ghosts and p not in focus_set and not self.fastener_pick_second:
                    if t_hit < min_t_ghost:
                        min_t_ghost = t_hit
                        closest_ghost = p
                else:
                    if t_hit < min_t_opaque:
                        min_t_opaque = t_hit
                        closest_opaque = p

        return closest_opaque if closest_opaque is not None else closest_ghost

    @classmethod
    def _intersect_ray_panel(cls, ray_origin, ray_dir, p: Panel):
        """Точное пересечение луча с OBB панели (перевод луча в локальные координаты детали)."""
        if hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "world_to_local") and hasattr(p, "unrotate_vector"):
            lox, loy, loz = p.world_to_local(float(ray_origin[0]), float(ray_origin[1]), float(ray_origin[2]))
            ldx, ldy, ldz = p.unrotate_vector(float(ray_dir[0]), float(ray_dir[1]), float(ray_dir[2]))
            l_orig = np.array([lox, loy, loz], dtype=float)
            l_dir = np.array([ldx, ldy, ldz], dtype=float)
            box_min = np.array([0.0, 0.0, 0.0], dtype=float)
            box_max = np.array([float(p.width), float(p.height), float(p.depth)], dtype=float)
            return cls._intersect_ray_aabb(l_orig, l_dir, box_min, box_max)
        box_min = np.array([float(p.x), float(p.y), float(p.z)], dtype=float)
        box_max = np.array([float(p.x + p.width), float(p.y + p.height), float(p.z + p.depth)], dtype=float)
        return cls._intersect_ray_aabb(ray_origin, ray_dir, box_min, box_max)

    @staticmethod
    def _intersect_ray_aabb(ray_origin, ray_dir, box_min, box_max):
        t_min = 0.0
        t_max = float("inf")
        for i in range(3):
            if abs(ray_dir[i]) < 1e-8:
                if ray_origin[i] < box_min[i] or ray_origin[i] > box_max[i]:
                    return None
            else:
                inv_d = 1.0 / ray_dir[i]
                t1 = (box_min[i] - ray_origin[i]) * inv_d
                t2 = (box_max[i] - ray_origin[i]) * inv_d
                if t1 > t2:
                    t1, t2 = t2, t1
                t_min = max(t_min, t1)
                t_max = min(t_max, t2)
                if t_min > t_max:
                    return None
        return t_min

    def closeEvent(self, event):
        """Вкладка/виджет закрывается — отключить сервис и освободить GPU."""
        try:
            svc = GeometryService.instance()
            svc.panel_geometry_updated.disconnect(self._on_panel_geometry_updated)
        except Exception as exc:
            _log.debug("Отключение GeometryService при закрытии вьюпорта пропущено: %s", exc)
        self._free_all_panel_gpu()
        try:
            super().closeEvent(event)
        except Exception:
            _log.exception("Ошибка в базовом обработчике closeEvent вьюпорта")
            if event is not None:
                event.accept()

    def delete_selected(self) -> bool:

        cmd = DeleteItemsCommand(self.blocks, "Удаление выделенного")
        if not cmd.capture():
            return False
        # Освобождаем GPU-буферы удаляемых панелей
        for b, _j, p in cmd.removed_panels:
            self._free_panel_gpu(p)
        for _i, b in cmd.removed_blocks:
            for p in getattr(b, "panels", []):
                self._free_panel_gpu(p)
        self.undo_stack.push(cmd, execute=True)
        self.panel_clicked.emit(None)
        self.scene_structure_changed.emit()
        self.update()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.resize_mode and self.resize_panel is not None and self.resize_orig_box is not None:
                box = self.resize_orig_box
                p = self.resize_panel
                p.x, p.y, p.z = box[0], box[1], box[2]
                p.width, p.height, p.depth = box[3], box[4], box[5]
                p.rebuild_geometry()
                self.resize_mode = False
                self.resize_corner = None
                self.resize_face = None
                self.resize_face_snap_desc = ""
                self.resize_orig_box = None
                self.fastener_message.emit("Размер: отменено")
                self.update()
                return
            if self.paste_mode or self.clipboard_await_anchor:
                self.cancel_paste_mode()
                return
            if self.drag_mode:
                self.cancel_drag_mode()
                return
            if self.measure_mode:
                if self.measure_pt2 is not None:
                    self.measure_pt1 = None
                    self.measure_pt2 = None
                    self.measure_current_pt = None
                    self.measure_target1 = None
                    self.measure_preview_dim = None
                    self.measure_preview_angle = None
                    msg = "Линейный размер сохранен. Выберите точку для нового замера."
                    self.measurement_updated.emit(msg)
                    self.fastener_message.emit(msg)
                    self.update()
                elif self.measure_pt1 is not None:
                    self.measure_pt1 = None
                    self.measure_pt2 = None
                    self.measure_current_pt = None
                    self.measure_target1 = None
                    self.measure_preview_dim = None
                    self.measure_preview_angle = None
                    msg = "Рулетка: измерение сброшено. Выберите первую точку."
                    self.measurement_updated.emit(msg)
                    self.fastener_message.emit(msg)
                    self.update()
                else:
                    self.stop_measure_mode()
                return
            if self.fastener_mode or self.fastener_pick_second:
                self.stop_fastener_mode()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.measure_mode and self.measure_pt2 is not None:
                self.measure_pt1 = None
                self.measure_pt2 = None
                self.measure_current_pt = None
                self.measure_target1 = None
                self.measure_preview_dim = None
                self.measure_preview_angle = None
                msg = "Линейный размер зафиксирован. Выберите точку для нового замера."
                self.measurement_updated.emit(msg)
                self.fastener_message.emit(msg)
                self.update()
                return
        if event.key() == Qt.Key.Key_M:
            self.toggle_measure_mode()
            return
        if event.key() == Qt.Key.Key_I and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.toggle_ghost_others_mode()
            return
        if event.key() == Qt.Key.Key_S and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.toggle_section_mode()
            return
        if event.key() == Qt.Key.Key_C and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.toggle_live_collision_mode()
            return
        if event.key() == Qt.Key.Key_G:
            self.start_drag_mode()
            return
        # Grab: фиксация оси X / Y / Z, Shift — снять
        if self.drag_mode and self.drag_stage == 2:
            if event.key() == Qt.Key.Key_X:
                self.drag_axis_lock = "X"
                self.fastener_message.emit("🔒 Ось X (только горизонталь по ширине сцены)")
                self.update()
                return
            if event.key() == Qt.Key.Key_Y:
                self.drag_axis_lock = "Y"
                self.fastener_message.emit("🔒 Ось Y (только высота)")
                self.update()
                return
            if event.key() == Qt.Key.Key_Z:
                self.drag_axis_lock = "Z"
                self.fastener_message.emit("🔒 Ось Z (только глубина)")
                self.update()
                return
            if event.key() == Qt.Key.Key_Shift:
                self.drag_axis_lock = None
                self.fastener_message.emit("🔓 Свободное перемещение (все оси)")
                self.update()
                return
        # Крепёж: Tab — пресет; 2/3/4 — число точек (сбрасывает pitch)
        if self.fastener_mode and self.fastener_joint is not None:
            if event.key() == Qt.Key.Key_Tab:
                self.cycle_fastener_preset(1 if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else -1)
                return
            if event.key() in (Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4):
                self.fastener_count = int(event.text() or "3")
                self.fastener_pitch = None  # равномерно
                center_t = None
                if self.fastener_preview is not None:
                    j = self.fastener_joint
                    rel = self.fastener_preview - j.origin
                    center_t = float(np.dot(rel, j.slide_dir))
                self._refresh_fastener_preview_points(center_t=center_t)
                self.fastener_message.emit(
                    f"Крепёж: ×{self.fastener_count}, отступ {self.fastener_margin:.0f} мм (равномерно)"
                )
                self.update()
                return
        # Ctrl+C / Ctrl+V — копирование с точкой привязки
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C:
                self.copy_selection()
                return
            if event.key() == Qt.Key.Key_V:
                self.begin_paste_mode()
                return

        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            return

        sel = self.get_selected_panel()
        if sel:
            use_grid = self.grid_enabled and self.is_ortho
            dx = dy = dz = 0.0

            def _nudge(value: float, sign: float) -> float:
                if not use_grid:
                    return sign * self.move_step
                step = max(0.1, float(self.grid_step))
                if sign > 0:
                    return math.floor(value / step + 1e-9) * step + step - value
                return math.ceil(value / step - 1e-9) * step - step - value

            if event.key() == Qt.Key.Key_Left:
                dx = _nudge(sel.x, -1)
            elif event.key() == Qt.Key.Key_Right:
                dx = _nudge(sel.x, 1)
            elif event.key() == Qt.Key.Key_Up:
                dy = _nudge(sel.y, 1)
            elif event.key() == Qt.Key.Key_Down:
                dy = _nudge(sel.y, -1)
            elif event.key() == Qt.Key.Key_PageUp:
                dz = _nudge(sel.z, 1)
            elif event.key() == Qt.Key.Key_PageDown:
                dz = _nudge(sel.z, -1)

            if dx or dy or dz:
                old_xyz = (sel.x, sel.y, sel.z)
                new_xyz = (sel.x + dx, sel.y + dy, sel.z + dz)
                # merge=True объединяет серию мелких смещений стрелками в одну операцию отмены
                self.undo_stack.push(MovePanelCommand(sel, old_xyz, new_xyz), execute=True, merge=True)
                self.coordinates_changed.emit(sel.x, sel.y, sel.z)
                self.panel_clicked.emit(sel)
                hits = self._check_panel_collisions(sel)
                if hits:
                    names = ", ".join(p.name for p, _ in hits[:3])
                    self.fastener_message.emit(f"⚠️ Пересечение после сдвига: {sel.name} ↔ {names}")
                self.update()
                return

        if event.key() == Qt.Key.Key_Control:
            self.ctrl_held = True
            if hasattr(self, "last_mouse_pos") and not self.last_mouse_pos.isNull():
                self._update_measure_hover(self.last_mouse_pos.x(), self.last_mouse_pos.y(), ctrl_held=True)
            self.update()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Control:
            self.ctrl_held = False
            if hasattr(self, "last_mouse_pos") and not self.last_mouse_pos.isNull():
                if self.measure_mode:
                    self._update_measure_hover(self.last_mouse_pos.x(), self.last_mouse_pos.y(), ctrl_held=False)
                else:
                    self.measure_snap_info = None
                    self.measure_is_magnetic = False
            self.update()
            return
        super().keyReleaseEvent(event)

    def undo(self) -> str | None:
        desc = self.undo_stack.undo()
        if desc is not None:
            self.scene_structure_changed.emit()
            self.update()
        return desc

    def redo(self) -> str | None:
        desc = self.undo_stack.redo()
        if desc is not None:
            self.scene_structure_changed.emit()
            self.update()
        return desc

    def wheelEvent(self, event):
        """Зум к курсору; в режиме крепежа — смена числа точек массива; с Alt при сечении — сдвиг плоскости."""
        pos = event.position() if hasattr(event, "position") else event.pos()
        mx, my = int(pos.x()), int(pos.y())
        delta = event.angleDelta().y()
        if delta == 0:
            return

        mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        if self.section_enabled and (mods & Qt.KeyboardModifier.AltModifier):
            step = 0.03 if delta > 0 else -0.03
            self.set_section_ratio(self.section_ratio + step)
            return

        # Крепёж: колесо — число точек (равномерно); Shift+колесо — цикл пресетов
        if self.fastener_mode and self.fastener_joint is not None:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.cycle_fastener_preset(1 if delta > 0 else -1)
                return
            if delta > 0:
                self.fastener_count = min(6, self.fastener_count + 1)
            else:
                self.fastener_count = max(2, self.fastener_count - 1)
            self.fastener_pitch = None
            center_t = None
            if self.fastener_preview is not None:
                j = self.fastener_joint
                rel = self.fastener_preview - j.origin
                center_t = float(np.dot(rel, j.slide_dir))
            self._refresh_fastener_preview_points(center_t=center_t)
            self.fastener_message.emit(
                f"Крепёж: ×{self.fastener_count}, отступ {self.fastener_margin:.0f} мм | Shift+колесо — пресет"
            )
            self.update()
            return

        self.makeCurrent()
        self._sync_viewport_matrices()

        # Мировая точка под курсором до зума
        target = self._cursor_focus_point(mx, my)

        # Мультипликативный зум (zoom < 0; меньше по модулю = ближе)
        factor = math.exp(-delta * 0.0012)
        new_zoom = self.zoom * factor
        new_zoom = min(max(new_zoom, -80000.0), -80.0)
        self.zoom = new_zoom

        self._sync_viewport_matrices()

        # После зума та же экранная точка смотрит в другое место — компенсируем pan
        target2 = self._cursor_focus_point(mx, my)
        shift_world = target - target2
        R = self._rotation_matrix()
        shift_view = R[:3, :3] @ shift_world
        self.pan_x += float(shift_view[0])
        self.pan_y += float(shift_view[1])

        self.update()


class CentralWorkspace(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabBar().setExpanding(False)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabCloseRequested.connect(self.close_tab)
        self.add_new_model("Новый проект.b3d")

    def add_new_model(self, name: str):
        viewport = Viewport3D(name)
        self.addTab(viewport, name)
        self.setCurrentWidget(viewport)
        return viewport

    def current_viewport(self) -> Viewport3D | None:
        w = self.currentWidget()
        return w if isinstance(w, Viewport3D) else None

    def close_tab(self, index: int):
        if self.count() > 1:
            w = self.widget(index)
            if isinstance(w, Viewport3D):
                try:
                    w.close()  # closeEvent → free GPU + disconnect
                except Exception:
                    _log.exception("Ошибка при закрытии вкладки 3D-вьюпорта")
            self.removeTab(index)
