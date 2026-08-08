"""
Entry point for both ``python -m unicornviz`` and the
``unicorn-viz`` console-script installed by pyproject.toml.

SDL2 driver selection (Wayland vs X11) happens in app.py before
``import sdl2`` so the environment variable is set before SDL loads.
"""
from __future__ import annotations

import argparse
import faulthandler
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from unicornviz.config import Config, ConfigValidationError
from unicornviz.dropins import register_dropin_config_validators
from unicornviz.paths import APP_ROOT, resolve_path

# Kept open for the process lifetime so faulthandler can still write to it
# from the signal handler after a native crash (segfault, etc.).
_faulthandler_file: object | None = None


class _LogBandFilter(logging.Filter):
    """Filter records by a coarse log band while always allowing errors.

    Bands:
      - DEBUG: allow DEBUG/INFO/WARNING and errors
      - INFO:  allow INFO and errors (suppress DEBUG/WARNING)
      - WARN:  allow WARNING and errors (suppress DEBUG/INFO)
    """

    def __init__(self, band: str) -> None:
        super().__init__()
        self._band = band

    def filter(self, record: logging.LogRecord) -> bool:
        # Hard errors always show.
        if record.levelno >= logging.ERROR:
            return True

        if self._band == 'DEBUG':
            return record.levelno in (logging.DEBUG, logging.INFO, logging.WARNING)
        if self._band == 'INFO':
            return record.levelno in (logging.INFO, logging.WARNING)
        if self._band == 'WARN':
            return record.levelno == logging.WARNING
        # Fallback: default logging behavior.
        return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='unicorn-viz',
        description='Fullscreen demoscene visualizer with audio-reactive GPU effects, ANSI art, and MIDI control.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--config', default=str(APP_ROOT / 'config.toml'), help='Path to TOML config file.')

    display = parser.add_argument_group('display')
    display.add_argument('--width', type=int, help='Window width in pixels.')
    display.add_argument('--height', type=int, help='Window height in pixels.')
    display.add_argument('--title', help='Window title.')
    display.add_argument('--display-index', type=int, help='SDL display index / monitor to target at startup and for fullscreen.')
    display.add_argument('--display-mode', choices=['single', 'span_all', 'mirror_all'], help='Display layout mode: target one display, span across all displays, or mirror the output on all displays.')
    fullscreen = display.add_mutually_exclusive_group()
    fullscreen.add_argument('--fullscreen', action='store_true', help='Start fullscreen.')
    fullscreen.add_argument('--windowed', action='store_true', help='Start windowed.')

    display.add_argument(
        '--fps-limit', type=int, metavar='FPS',
        help='Render frame cap; 0 follows the display vsync. Locks to the '
             'nearest whole division of the refresh rate (default 30).',
    )

    demo = parser.add_argument_group('playlist / transitions')
    demo.add_argument('--mode', choices=['sequential', 'random'], help='Playlist mode.')
    demo.add_argument('--effect-duration', type=float, help='Seconds per effect in auto-play mode.')
    demo.add_argument(
        '--transition',
        choices=[
            'crossfade', 'smoothfade', 'scanwipe', 'scanwipe_x', 'scanwipe_y',
            'dissolve', 'zoomblend', 'radialwipe', 'lumawipe', 'stripewipe',
            'anglesweep', 'glitchsoft', 'prismsplit', 'radial', 'cut',
            'shuffle', 'random',
        ],
        help='Transition type or shuffled/randomized transitions.',
    )
    demo.add_argument('--transition-duration', type=float, help='Transition duration in seconds.')
    demo.add_argument('--start-effect', help='Display NAME or class name of starting effect.')
    demo.add_argument('--sequence', help='Comma-separated playlist sequence of effect class/display names.')

    audio = parser.add_argument_group('audio / midi')
    audio.add_argument('--audio-device', help='Audio device name substring.')
    audio.add_argument('--reactivity', type=float, help='Audio reactivity multiplier.')
    audio.add_argument('--latency', choices=['low', 'medium', 'high'], help='Audio stream latency preference.')
    audio.add_argument('--midi-device', help='MIDI device name substring; empty disables MIDI.')

    recording = parser.add_argument_group('recording')
    record_toggle = recording.add_mutually_exclusive_group()
    record_toggle.add_argument('--record', action='store_true', help='Automatically start recording after startup.')
    record_toggle.add_argument('--no-record', action='store_true', help='Disable automatic recording on startup.')
    audio_toggle = recording.add_mutually_exclusive_group()
    audio_toggle.add_argument('--record-audio', action='store_true', help='Enable audio recording/muxing when recording video.')
    audio_toggle.add_argument('--no-record-audio', action='store_true', help='Disable audio recording/muxing.')
    recording.add_argument('--record-dir', help='Directory for saved recordings.')
    recording.add_argument('--record-fps', type=int, help='Recording output FPS.')
    recording.add_argument('--record-crf', type=int, help='Recording video quality CRF value.')
    recording.add_argument(
        '--record-codec',
        help="Recording video codec. 'auto' probes for a working hardware "
             "encoder (NVENC/VA-API/QSV) and falls back to libx264; or name "
             "one explicitly, e.g. libx264, h264_vaapi, h264_nvenc.",
    )
    recording.add_argument('--ffmpeg-path', help='Path to the ffmpeg executable.')
    recording.add_argument('--record-audio-device', help='Pulse/PipeWire audio input device/source name for recording.')

    profile = parser.add_argument_group('boot profile')
    profile.add_argument(
        '--mixer', action='store_true',
        help='Boot straight into the DJ mixer console (mixer-only profile: '
             'no splash, no audio capture, no visual effects/drop-ins). '
             'Overrides [dj_mixer] mixer_only = false.',
    )

    training = parser.add_argument_group('headless training sources')
    training.add_argument('--dj-mixer-source', action='store_true', help='Force-enable dj-mixer-01 and arm headless AutoPlay for this run.')
    training.add_argument('--dj-mixer-autoplay-mode', choices=['autoload', 'cut', 'crossfade', 'smart'], help='AutoPlay mode to arm when --dj-mixer-source is set (default: cut).')
    training.add_argument('--dj-mixer-music-dir', help='Override [dj_mixer] music_dir for this run.')
    training.add_argument('--dj-mixer-output-device', help='Override [dj_mixer] output_device for this run. Defaults to --audio-device if not given (the same sink used for capture).')
    training.add_argument('--media-source', action='store_true', help='Force-enable media-01 and auto-play for this run.')
    training.add_argument('--media-dir', help='Override [media] media_dir for this run.')

    logging_group = parser.add_argument_group('logging')
    logging_group.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL', 'NONE'], help='Console/file log level; NONE disables all logging.')

    return parser


def _build_overrides(args: argparse.Namespace) -> dict:
    overrides: dict = {}

    def put(section: str, key: str, value) -> None:
        if value is None:
            return
        overrides.setdefault(section, {})[key] = value

    put('window', 'width', args.width)
    put('window', 'height', args.height)
    put('window', 'title', args.title)
    put('window', 'display_index', args.display_index)
    put('window', 'display_mode', args.display_mode)
    if args.fullscreen:
        put('window', 'fullscreen', True)
    elif args.windowed:
        put('window', 'fullscreen', False)

    put('demo', 'mode', args.mode)
    put('demo', 'effect_duration', args.effect_duration)
    put('demo', 'transition', args.transition)
    put('demo', 'transition_duration', args.transition_duration)
    put('playlist', 'start_effect', args.start_effect)
    if args.sequence is not None:
        seq = [item.strip() for item in args.sequence.split(',') if item.strip()]
        put('playlist', 'sequence', seq)

    put('audio', 'device', args.audio_device)
    put('audio', 'reactivity', args.reactivity)
    put('audio', 'latency', args.latency)
    put('midi', 'device', args.midi_device)
    if args.record:
        put('recording', 'auto_record', True)
    elif args.no_record:
        put('recording', 'auto_record', False)
    if args.record_audio:
        put('recording', 'capture_audio', True)
    elif args.no_record_audio:
        put('recording', 'capture_audio', False)
    put('recording', 'directory', args.record_dir)
    put('recording', 'fps', args.record_fps)
    put('recording', 'crf', args.record_crf)
    put('recording', 'codec', args.record_codec)
    put('recording', 'ffmpeg_path', args.ffmpeg_path)
    put('recording', 'audio_input_device', args.record_audio_device)

    if args.dj_mixer_source:
        put('dj_mixer', 'enabled', True)
        put('dj_mixer', 'start_enabled', True)
        put('dj_mixer', 'autoplay_boot_mode', args.dj_mixer_autoplay_mode or 'cut')
        put('dj_mixer', 'output_device', args.dj_mixer_output_device or args.audio_device)
        put('dj_mixer', 'music_dir', args.dj_mixer_music_dir)
        # A headless source implies a headless run: the whole point of
        # --dj-mixer-source/--media-source is nobody is at the keyboard, so
        # the set ending must also end the process (see
        # docs/planning/headless-auto-exit-plan-2026-08-07.md) -- no extra
        # flag or config.toml edit required to opt in.
        put('auto_vj', 'auto_exit_after_finale', True)
    if args.media_source:
        put('media', 'enabled', True)
        put('media', 'auto_play', True)
        put('media', 'media_dir', args.media_dir)
        put('auto_vj', 'auto_exit_after_finale', True)

    if args.mixer:
        put('dj_mixer', 'mixer_only', True)

    put('render', 'fps_limit', args.fps_limit)
    put('logging', 'level', args.log_level)
    return overrides


def _setup_logging(cfg: Config) -> None:
    level_name = str(cfg.get('logging', 'level', default='INFO')).upper()
    if level_name == 'WARNING':
        level_name = 'WARN'
    
    # Silence all logging if NONE is selected.
    if level_name == 'NONE':
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.CRITICAL + 1)
        return
    
    if level_name in ('ERROR', 'CRITICAL'):
        # Keep explicit high-severity modes meaningful.
        level = getattr(logging, level_name, logging.ERROR)
        band_filter: logging.Filter | None = None
    elif level_name in ('DEBUG', 'INFO', 'WARN'):
        level = logging.DEBUG
        band_filter = _LogBandFilter(level_name)
    else:
        level = logging.DEBUG
        band_filter = _LogBandFilter('INFO')
    log_dir = resolve_path(cfg.get('logging', 'directory', default='logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"unicornviz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    formatter = logging.Formatter('%(levelname)s [%(name)s] %(message)s')
    # The file gets wall-clock stamps; the console stays terse.  Reports come
    # in as "around 19:50 the volume dipped", and without a stamp there is no
    # way to line that up against the log at all.
    file_formatter = logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%H:%M:%S')

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    if band_filter is not None:
        console.addFilter(band_filter)

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    if band_filter is not None:
        file_handler.addFilter(band_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)
    logging.getLogger(__name__).info('Logging to %s', log_path)


def _install_gl_debug_env(cfg: Config) -> None:
    """Enable verbose Mesa/EGL driver debug output when logging is DEBUG.

    Must run before the GL context is created (so, before anything imports
    ``sdl2``/``moderngl``) since Mesa reads these at driver-load time —
    mirrors the existing ``SDL_VIDEODRIVER`` pattern in ``app.py``. This
    output goes straight to the process's raw stderr, not through Python's
    ``logging`` module, so it will not appear in the log file; redirect
    stderr yourself if you need it captured (e.g. ``... 2>&1 | tee out.log``).
    """
    level_name = str(cfg.get('logging', 'level', default='INFO')).upper()
    if level_name != 'DEBUG':
        return
    os.environ.setdefault('MESA_DEBUG', '1')
    os.environ.setdefault('LIBGL_DEBUG', 'verbose')
    os.environ.setdefault('EGL_LOG_LEVEL', 'debug')
    logging.getLogger(__name__).info(
        'GL driver debug output enabled (MESA_DEBUG=1 LIBGL_DEBUG=verbose '
        'EGL_LOG_LEVEL=debug) — written to stderr, not the log file; '
        'redirect stderr if you need it captured.'
    )


def _install_faulthandler(cfg: Config) -> None:
    """Dump a Python-level traceback on native crashes (segfaults, etc.).

    A native crash kills the process before ``logging`` can run, so a hard
    Mesa/EGL/ALSA-level crash otherwise leaves no trace beyond the log file
    stopping mid-line. ``faulthandler`` writes from the low-level signal
    handler instead, which survives that. Mirrors the ``[logging] level``
    convention used elsewhere (e.g. the deleted-effects log): a real file
    under the logs directory when logging is enabled, stderr otherwise.
    """
    global _faulthandler_file
    level_name = str(cfg.get('logging', 'level', default='INFO')).upper()
    if level_name == 'NONE':
        faulthandler.enable()
        return
    log_dir = resolve_path(cfg.get('logging', 'directory', default='logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"faulthandler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    _faulthandler_file = open(path, 'w', encoding='utf-8')  # noqa: SIM115 - kept open for process lifetime
    faulthandler.enable(file=_faulthandler_file)


def _install_exception_logging() -> None:
    """Log uncaught exceptions so crash tracebacks are persisted in log files."""

    def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        # Keep Ctrl+C behavior clean.
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger(__name__).critical(
            'Uncaught exception',
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _log_uncaught_exception


def main() -> None:
    """Create and run the main application."""
    parser = _build_parser()
    args = parser.parse_args()
    cfg = Config(args.config, overrides=_build_overrides(args))
    register_dropin_config_validators()
    try:
        cfg.validate()
    except ConfigValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    _setup_logging(cfg)
    _install_gl_debug_env(cfg)
    _install_faulthandler(cfg)
    _install_exception_logging()
    from unicornviz.app import App
    app = App(cfg)
    try:
        try:
            app.run()
        finally:
            # Teardown must run even when run() raises: audio/MIDI/recorder
            # threads and SDL are otherwise left dangling on a crash.
            app.ensure_shutdown()
    except RuntimeError as exc:
        if 'audio startup failed' in str(exc).lower() or 'audio capture' in str(exc).lower():
            print(
                '\n'
                '  unicorn-viz could not start: audio capture failed.\n'
                '\n'
                '  Possible fixes:\n'
                '    - Check that PipeWire / PulseAudio is running:  systemctl --user status pipewire\n'
                '    - Restart the audio session:                     systemctl --user restart pipewire wireplumber\n'
                '    - Set a specific device in config.toml:          [audio] device = "Built-in Audio Analog Stereo"\n'
                '    - Allow degraded (no-audio) startup:             [audio] require_startup = false\n'
                f'\n  Detail: {exc}\n',
                file=__import__("sys").stderr,
            )
            raise SystemExit(1) from exc
        raise


def main_mixer() -> None:
    """`unicorn-mix` entrypoint: boot the mixer-only profile.

    A branded identity for the same binary — equivalent to
    `unicorn-viz --mixer`; every other CLI flag still applies.
    """
    if '--mixer' not in sys.argv[1:]:
        sys.argv.insert(1, '--mixer')
    main()


if __name__ == "__main__":
    main()
