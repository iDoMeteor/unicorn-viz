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
    recording.add_argument('--record-dir', help='Directory for saved recordings.')
    recording.add_argument('--record-fps', type=int, help='Recording output FPS.')
    recording.add_argument('--record-crf', type=int, help='Recording video quality CRF value.')
    recording.add_argument('--ffmpeg-path', help='Path to the ffmpeg executable.')

    logging_group = parser.add_argument_group('logging')
    logging_group.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help='Console/file log level.')

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
    put('recording', 'directory', args.record_dir)
    put('recording', 'fps', args.record_fps)
    put('recording', 'crf', args.record_crf)
    put('recording', 'ffmpeg_path', args.ffmpeg_path)
    put('logging', 'level', args.log_level)
    return overrides


def _setup_logging(cfg: Config) -> None:
    level_name = str(cfg.get('logging', 'level', default='INFO')).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_dir = Path(str(cfg.get('logging', 'directory', default='logs')))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"unicornviz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    formatter = logging.Formatter('%(levelname)s [%(name)s] %(message)s')

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

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
