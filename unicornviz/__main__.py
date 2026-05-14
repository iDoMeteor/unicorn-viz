"""
Entry point for both ``python -m unicornviz`` and the
``unicorn-viz`` console-script installed by pyproject.toml.

SDL2 driver selection (Wayland vs X11) happens in app.py before
``import sdl2`` so the environment variable is set before SDL loads.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from unicornviz.config import Config


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
            return record.levelno == logging.INFO
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
    parser.add_argument('--config', default='config.toml', help='Path to TOML config file.')

    display = parser.add_argument_group('display')
    display.add_argument('--width', type=int, help='Window width in pixels.')
    display.add_argument('--height', type=int, help='Window height in pixels.')
    display.add_argument('--title', help='Window title.')
    display.add_argument('--display-index', type=int, help='SDL display index / monitor to target at startup and for fullscreen.')
    display.add_argument('--display-mode', choices=['single', 'span_all', 'mirror_all'], help='Display layout mode: target one display, span across all displays, or mirror the output on all displays.')
    fullscreen = display.add_mutually_exclusive_group()
    fullscreen.add_argument('--fullscreen', action='store_true', help='Start fullscreen.')
    fullscreen.add_argument('--windowed', action='store_true', help='Start windowed.')

    demo = parser.add_argument_group('playlist / transitions')
    demo.add_argument('--mode', choices=['sequential', 'random'], help='Playlist mode.')
    demo.add_argument('--effect-duration', type=float, help='Seconds per effect in auto-play mode.')
    demo.add_argument(
        '--transition',
        choices=['crossfade', 'smoothfade', 'scanwipe', 'scanwipe_x', 'scanwipe_y', 'dissolve', 'zoomblend', 'shuffle', 'random'],
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
    recording.add_argument('--ffmpeg-path', help='Path to the ffmpeg executable.')
    recording.add_argument('--record-audio-device', help='Pulse/PipeWire audio input device/source name for recording.')

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
    put('recording', 'ffmpeg_path', args.ffmpeg_path)
    put('recording', 'audio_input_device', args.record_audio_device)
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
    log_dir = Path(str(cfg.get('logging', 'directory', default='logs')))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"unicornviz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    formatter = logging.Formatter('%(levelname)s [%(name)s] %(message)s')

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    if band_filter is not None:
        console.addFilter(band_filter)

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    if band_filter is not None:
        file_handler.addFilter(band_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)
    logging.getLogger(__name__).info('Logging to %s', log_path)


def main() -> None:
    """Create and run the main application."""
    parser = _build_parser()
    args = parser.parse_args()
    cfg = Config(args.config, overrides=_build_overrides(args))
    _setup_logging(cfg)
    from unicornviz.app import App
    app = App(cfg)
    app.run()


if __name__ == "__main__":
    main()
