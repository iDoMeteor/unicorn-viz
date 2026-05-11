"""System-level camera overlay for unicorn-viz.

Renders a live camera PiP (or fullscreen) on top of every effect, below
the HUD and help overlays.  Managed by ``App`` directly — not a playlist
effect.  Uses a dedicated background thread for V4L2/camera capture with
automatic reconnect logic.

Config section: ``[webcam]``

.. code-block:: toml

    [webcam]
    enabled       = true       # false disables all camera init
    device        = 0          # /dev/videoN index (Linux) or DirectShow idx (Windows)
    width         = 1280
    height        = 720
    fps           = 30
    pip_position  = "bottom_right"
    pip_scale     = 0.33       # fraction of viewport width  (0.12 – 0.80)
    log_frames    = false      # emit DEBUG log every 60 captured frames

Keypad layout tokens accepted by ``set_layout()``:

    7 = top_left      8 = top_center    9 = top_right
    4 = left          5 = center        6 = right
    1 = bottom_left   2 = bottom_center 3 = bottom_right
    0 = fullscreen    . = hide
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

import moderngl
import numpy as np

if TYPE_CHECKING:
    pass  # avoid circular imports

try:
    import cv2  # type: ignore
    _CV2 = True
except ImportError:
    cv2 = None  # type: ignore
    _CV2 = False

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GLSL – minimal textured-quad shaders (no background; draws on top of scene)
# ---------------------------------------------------------------------------
_QUAD_VERT = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

_QUAD_FRAG = """
#version 330
uniform sampler2D cam_tex;
in vec2  v_uv;
out vec4 fragColor;
void main() {
    fragColor = vec4(texture(cam_tex, v_uv).rgb, 1.0);
}
"""

_RECT_VERT = """
#version 330
in vec2 in_vert;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_RECT_FRAG = """
#version 330
uniform vec4 color;
out vec4 fragColor;
void main() {
    fragColor = color;
}
"""

# ---------------------------------------------------------------------------
# Layout tables
# ---------------------------------------------------------------------------
_LAYOUTS: dict[str, tuple[float, float]] = {
    'top_left':      (0.04, 0.04),
    'top_center':    (0.50, 0.04),
    'top_right':     (0.96, 0.04),
    'left':          (0.04, 0.50),
    'center':        (0.50, 0.50),
    'right':         (0.96, 0.50),
    'bottom_left':   (0.04, 0.96),
    'bottom_center': (0.50, 0.96),
    'bottom_right':  (0.96, 0.96),
}

_KEYPAD_MAP: dict[str, str] = {
    '7': 'top_left',      '8': 'top_center',     '9': 'top_right',
    '4': 'left',          '5': 'center',          '6': 'right',
    '1': 'bottom_left',   '2': 'bottom_center',   '3': 'bottom_right',
    '0': 'fullscreen',    '.': 'hide',
}


# ---------------------------------------------------------------------------
# Background camera capture thread
# ---------------------------------------------------------------------------
class _CameraWorker(threading.Thread):
    """Daemon thread that captures frames from a V4L2/OS camera device.

    Automatically reconnects if the device becomes unavailable or stops
    responding.  All inter-thread communication uses a simple lock-guarded
    frame pointer — safe to call ``latest()`` from the GL thread.
    """

    def __init__(
        self,
        device: int,
        width: int,
        height: int,
        fps: int,
        log_frames: bool = False,
    ) -> None:
        super().__init__(daemon=True, name='camera-overlay')
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps
        self._log_frames = log_frames
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest: np.ndarray | None = None
        self._active = False
        self._frame_count = 0

    # ------------------------------------------------------------------
    def run(self) -> None:
        if not _CV2:
            log.error(
                'CameraOverlay: opencv-python is not installed — '
                'install it with: pip install opencv-python-headless'
            )
            return

        period = 1.0 / max(1, self._fps)

        while not self._stop.is_set():
            cap = self._open_device()
            if cap is None:
                self._stop.wait(3.0)
                continue

            self._active = True
            fail_count = 0

            while not self._stop.is_set():
                ok, frame = cap.read()
                if ok and frame is not None:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame = cv2.flip(frame, 1)
                    with self._lock:
                        self._latest = frame
                    self._frame_count += 1
                    fail_count = 0
                    if self._log_frames and self._frame_count % 60 == 0:
                        log.debug(
                            'CameraOverlay: frame %d  shape=%s',
                            self._frame_count, frame.shape,
                        )
                else:
                    fail_count += 1
                    log.debug(
                        'CameraOverlay: read failure #%d on device %d',
                        fail_count, self._device,
                    )
                    if fail_count >= 20:
                        log.warning(
                            'CameraOverlay: device %d not responding after '
                            '20 failures — reconnecting',
                            self._device,
                        )
                        break
                self._stop.wait(period * 0.45)

            cap.release()
            self._active = False
            log.info('CameraOverlay: device %d released', self._device)
            if not self._stop.is_set():
                log.info('CameraOverlay: waiting 2 s before reconnect…')
                self._stop.wait(2.0)

    # ------------------------------------------------------------------
    def _open_device(self) -> 'cv2.VideoCapture | None':
        """Try the configured device index, then +1, then +2."""
        for delta in (0, 1, 2):
            dev = self._device + delta
            cap = self._try_open(dev)
            if cap is not None:
                if delta != 0:
                    log.info(
                        'CameraOverlay: device %d unavailable, using device %d',
                        self._device, dev,
                    )
                return cap
        log.warning(
            'CameraOverlay: no usable camera found '
            '(tried devices %d..%d) — will retry in 3 s',
            self._device, self._device + 2,
        )
        return None

    def _try_open(self, dev: int) -> 'cv2.VideoCapture | None':
        # Prefer V4L2 explicitly on Linux — avoids GStreamer/MSMF confusion
        if sys.platform != 'win32':
            log.debug('CameraOverlay: trying /dev/video%d (V4L2)', dev)
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        else:
            log.debug('CameraOverlay: trying device %d', dev)
            cap = cv2.VideoCapture(dev)

        if not cap.isOpened():
            log.debug('CameraOverlay: device %d open failed', dev)
            cap.release()
            return None

        # Prefer MJPG for better throughput and format compatibility
        if sys.platform != 'win32':
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(self._width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
        cap.set(cv2.CAP_PROP_FPS,          float(self._fps))

        actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        log.info(
            'CameraOverlay: device %d opened  '
            'requested=%dx%d@%d  actual=%dx%d@%.1f',
            dev,
            self._width, self._height, self._fps,
            actual_w, actual_h, actual_fps,
        )
        return cap

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Signal the thread to exit cleanly."""
        self._stop.set()

    def latest(self) -> np.ndarray | None:
        """Return a copy of the most recent frame, or None if not yet available."""
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    @property
    def active(self) -> bool:
        """True while the device is successfully open and delivering frames."""
        return self._active


# ---------------------------------------------------------------------------
# Public overlay class
# ---------------------------------------------------------------------------
class CameraOverlay:
    """System-level camera PiP rendered on top of every effect.

    Lifecycle::

        overlay = CameraOverlay(ctx, width, height, cfg_dict)
        overlay.start()          # starts background capture thread
        # per frame:
        overlay.render()         # draws on the currently bound screen FBO
        # on resize:
        overlay.resize(w, h)
        # on shutdown:
        overlay.destroy()

    ``cfg_dict`` is the ``[webcam]`` section from config.toml (may be empty).
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        cfg: dict,
    ) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._cfg = cfg

        self._worker: _CameraWorker | None = None
        self._cam_tex: moderngl.Texture | None = None
        self._cam_tex_size: tuple[int, int] = (0, 0)
        self._fallback_tex: moderngl.Texture | None = None
        self._quad_prog: moderngl.Program | None = None
        self._quad_vao: moderngl.VertexArray | None = None
        self._quad_vbo: moderngl.Buffer | None = None
        self._rect_prog: moderngl.Program | None = None
        self._rect_vao: moderngl.VertexArray | None = None
        self._rect_vbo: moderngl.Buffer | None = None

        self._hidden = False
        self._layout: str = str(cfg.get('pip_position', 'bottom_right')).lower()
        self._pip_scale: float = float(cfg.get('pip_scale', 0.33))
        self._cam_width: int  = int(cfg.get('width',  1280))
        self._cam_height: int = int(cfg.get('height',  720))

        self._enabled = str(cfg.get('enabled', 'true')).lower() != 'false'
        if not self._enabled:
            log.info('CameraOverlay: disabled via [webcam] enabled = false')
            return

        if not _CV2:
            log.error(
                'CameraOverlay: opencv-python is not installed — '
                'camera overlay will not function. '
                'Install with: pip install opencv-python-headless'
            )
            self._enabled = False
            return

        self._build_gl()
        log.info('CameraOverlay: initialised  pip=%s  scale=%.2f', self._layout, self._pip_scale)

    # ------------------------------------------------------------------
    # GL setup
    # ------------------------------------------------------------------
    def _build_gl(self) -> None:
        self._quad_prog = self._ctx.program(
            vertex_shader=_QUAD_VERT, fragment_shader=_QUAD_FRAG
        )
        self._quad_vbo = self._ctx.buffer(reserve=6 * 4 * 4)
        self._quad_vao = self._ctx.vertex_array(
            self._quad_prog,
            [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')],
        )

        self._rect_prog = self._ctx.program(
            vertex_shader=_RECT_VERT, fragment_shader=_RECT_FRAG
        )
        self._rect_vbo = self._ctx.buffer(reserve=6 * 2 * 4)
        self._rect_vao = self._ctx.vertex_array(
            self._rect_prog,
            [(self._rect_vbo, '2f', 'in_vert')],
        )

        # Tiny dark fallback so something is visible while camera warms up.
        fb = np.full((4, 4, 3), 30, dtype=np.uint8)
        self._fallback_tex = self._ctx.texture((4, 4), 3, fb.tobytes())
        self._fallback_tex.filter = moderngl.LINEAR, moderngl.LINEAR
        log.debug('CameraOverlay: GL resources built')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the background camera capture thread."""
        if not self._enabled:
            return
        device     = int(self._cfg.get('device', 0))
        fps        = int(self._cfg.get('fps', 30))
        log_frames = str(self._cfg.get('log_frames', 'false')).lower() == 'true'
        log.info(
            'CameraOverlay: starting capture  device=%d  %dx%d@%d  log_frames=%s',
            device, self._cam_width, self._cam_height, fps, log_frames,
        )
        self._worker = _CameraWorker(
            device, self._cam_width, self._cam_height, fps, log_frames
        )
        self._worker.start()

    def resize(self, width: int, height: int) -> None:
        """Update viewport dimensions (call from ``App._on_resize``)."""
        self._width = width
        self._height = height

    def destroy(self) -> None:
        """Stop the capture thread and release all GL resources."""
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        for attr in ('_cam_tex', '_fallback_tex',
                     '_quad_vao', '_quad_vbo', '_quad_prog',
                     '_rect_vao', '_rect_vbo', '_rect_prog'):
            obj = getattr(self, attr, None)
            if obj is not None:
                obj.release()
                setattr(self, attr, None)
        log.info('CameraOverlay: destroyed')

    # ------------------------------------------------------------------
    # State controls
    # ------------------------------------------------------------------
    def set_layout(self, layout: str) -> str:
        """Set PiP position.  Accepts keypad token or layout name.

        Returns the resolved layout name (or 'hide').
        """
        layout = layout.lower().strip()
        if layout in _KEYPAD_MAP:
            layout = _KEYPAD_MAP[layout]

        if layout == 'hide':
            self._hidden = True
            log.info('CameraOverlay: hidden')
            return 'hide'

        self._hidden = False
        if layout == 'fullscreen':
            self._layout = 'fullscreen'
            log.info('CameraOverlay: layout=fullscreen')
            return self._layout

        if layout in _LAYOUTS:
            self._layout = layout
            log.info('CameraOverlay: layout=%s', self._layout)
            return self._layout

        log.warning(
            'CameraOverlay: unknown layout %r; keeping %s', layout, self._layout
        )
        return self._layout

    def scale_pip(self, delta: float) -> float:
        """Nudge PiP scale by *delta* (±0.05 typical). Returns new value."""
        self._pip_scale = max(0.12, min(0.80, self._pip_scale + delta))
        log.info('CameraOverlay: pip_scale=%.2f', self._pip_scale)
        return self._pip_scale

    @property
    def enabled(self) -> bool:
        """True when the overlay is active (not disabled in config)."""
        return self._enabled

    @property
    def hidden(self) -> bool:
        """True when the camera is hidden (KP dot)."""
        return self._hidden

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _ndc(
        self, x: float, y: float, w: float, h: float
    ) -> tuple[float, float, float, float]:
        """Convert pixel rect to NDC (x0, x1, y0_top, y1_bottom)."""
        x0 = (x / self._width)  * 2.0 - 1.0
        x1 = ((x + w) / self._width)  * 2.0 - 1.0
        y0 = 1.0 - (y / self._height) * 2.0
        y1 = 1.0 - ((y + h) / self._height) * 2.0
        return x0, x1, y0, y1

    def _pip_rect(self) -> tuple[float, float, float, float]:
        if self._layout == 'fullscreen':
            return 0.0, 0.0, float(self._width), float(self._height)

        scale = max(0.12, min(0.80, self._pip_scale))
        w = self._width * scale
        h = w * (self._cam_height / max(1, self._cam_width))
        h = min(h, self._height * 0.72)

        ax, ay = _LAYOUTS.get(self._layout, _LAYOUTS['bottom_right'])
        x = (
            24.0 if ax <= 0.05
            else (self._width - w - 24.0 if ax >= 0.95
                  else (self._width - w) * 0.5)
        )
        y = (
            24.0 if ay <= 0.05
            else (self._height - h - 24.0 if ay >= 0.95
                  else (self._height - h) * 0.5)
        )
        return x, y, w, h

    def _update_texture(self) -> moderngl.Texture:
        if self._worker is None:
            return self._fallback_tex  # type: ignore[return-value]
        frame = self._worker.latest()
        if frame is None:
            log.debug('CameraOverlay: no frame yet — using fallback texture')
            return self._fallback_tex  # type: ignore[return-value]

        fh, fw = frame.shape[:2]
        if self._cam_tex is None or self._cam_tex_size != (fw, fh):
            if self._cam_tex is not None:
                self._cam_tex.release()
            self._cam_tex = self._ctx.texture((fw, fh), 3, frame.tobytes())
            self._cam_tex.filter = moderngl.LINEAR, moderngl.LINEAR
            self._cam_tex_size = (fw, fh)
            log.info('CameraOverlay: camera texture created  %dx%d', fw, fh)
        else:
            self._cam_tex.write(frame.tobytes())
        return self._cam_tex

    # ------------------------------------------------------------------
    # Public render
    # ------------------------------------------------------------------
    def render(self) -> None:
        """Draw the camera PiP on the currently bound framebuffer.

        Call this after the main effect renders and before the HUD overlays.
        """
        if not self._enabled or self._hidden:
            return
        if self._quad_prog is None:
            return

        tex = self._update_texture()
        x, y, w, h = self._pip_rect()

        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # Border rectangle (skip in fullscreen mode)
        if self._layout != 'fullscreen' and self._rect_prog is not None:
            border = 6.0
            bx0, bx1, by0, by1 = self._ndc(x - border, y - border,
                                             w + border * 2.0, h + border * 2.0)
            rv = np.array(
                [bx0, by0, bx1, by0, bx0, by1,
                 bx1, by0, bx1, by1, bx0, by1],
                dtype=np.float32,
            )
            self._rect_vbo.write(rv)
            self._rect_prog['color'].value = (0.05, 0.65, 1.0, 0.55)
            self._rect_vao.render(moderngl.TRIANGLES)

        # Camera quad
        x0, x1, y0, y1 = self._ndc(x, y, w, h)
        verts = np.array([
            x0, y0, 0.0, 0.0,
            x1, y0, 1.0, 0.0,
            x0, y1, 0.0, 1.0,
            x1, y0, 1.0, 0.0,
            x1, y1, 1.0, 1.0,
            x0, y1, 0.0, 1.0,
        ], dtype=np.float32)
        self._quad_vbo.write(verts)
        tex.use(location=0)
        self._quad_prog['cam_tex'].value = 0
        self._quad_vao.render(moderngl.TRIANGLES)
