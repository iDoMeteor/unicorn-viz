"""Recording support for Unicorn Viz.

This module manages a simple ffmpeg subprocess that accepts raw RGB frames
from the app and writes H.264 MP4 output. V1 records video only.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from unicornviz.config import Config

log = logging.getLogger(__name__)


class Recorder:
    """Manage an ffmpeg subprocess for recording raw RGB frames to disk."""

    def __init__(self, cfg: Config, width: int, height: int) -> None:
        self._enabled = bool(cfg.get('recording', 'enabled', default=True))
        self._auto_record = bool(cfg.get('recording', 'auto_record', default=False))
        self._directory = Path(str(cfg.get('recording', 'directory', default='recordings')))
        self._ffmpeg_path = str(cfg.get('recording', 'ffmpeg_path', default='ffmpeg'))
        self._container = str(cfg.get('recording', 'container', default='mp4'))
        self._fps = int(cfg.get('recording', 'fps', default=60))
        self._codec = str(cfg.get('recording', 'codec', default='libx264'))
        self._preset = str(cfg.get('recording', 'preset', default='veryfast'))
        self._crf = int(cfg.get('recording', 'crf', default=18))
        self._pixel_format = str(cfg.get('recording', 'pixel_format', default='yuv420p'))
        self._capture_audio = bool(cfg.get('recording', 'capture_audio', default=False))
        self._filename_prefix = str(cfg.get('recording', 'filename_prefix', default='unicornviz'))
        self._show_indicator = bool(cfg.get('recording', 'show_indicator', default=True))
        self._width = width
        self._height = height
        self._process: subprocess.Popen[bytes] | None = None
        self._current_path: Path | None = None
        self._last_error: str = ''

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def auto_record(self) -> bool:
        return self._auto_record

    @property
    def show_indicator(self) -> bool:
        return self._show_indicator

    @property
    def is_recording(self) -> bool:
        return self._process is not None and self._process.stdin is not None

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def last_error(self) -> str:
        return self._last_error

    def _build_output_path(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return self._directory / f'{self._filename_prefix}_{ts}.{self._container}'

    def _build_command(self, output_path: Path) -> list[str]:
        command = [
            self._ffmpeg_path,
            '-y',
            '-loglevel',
            'error',
            '-nostdin',
            '-f',
            'rawvideo',
            '-pix_fmt',
            'rgb24',
            '-video_size',
            f'{self._width}x{self._height}',
            '-framerate',
            str(self._fps),
            '-i',
            '-',
            '-vf',
            'vflip',
            '-c:v',
            self._codec,
            '-preset',
            self._preset,
            '-crf',
            str(self._crf),
            '-pix_fmt',
            self._pixel_format,
            '-movflags',
            '+faststart',
        ]
        if not self._capture_audio:
            command.append('-an')
        command.append(str(output_path))
        return command

    def start(self) -> bool:
        """Start a new recording session."""
        if not self._enabled:
            self._last_error = 'Recording disabled'
            return False
        if self.is_recording:
            return True

        output_path = self._build_output_path()
        command = self._build_command(output_path)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_path = output_path
            self._last_error = ''
            log.info('Recording started: %s', output_path)
            return True
        except FileNotFoundError:
            self._last_error = f'ffmpeg not found: {self._ffmpeg_path}'
            self._process = None
            self._current_path = None
            log.error(self._last_error)
            return False
        except Exception as exc:
            self._last_error = f'Recording start failed: {exc}'
            self._process = None
            self._current_path = None
            log.error(self._last_error)
            return False

    def write_frame(self, rgb_bytes: bytes) -> bool:
        """Write a single raw RGB frame to the recorder."""
        if not self.is_recording or self._process is None or self._process.stdin is None:
            return False
        try:
            self._process.stdin.write(rgb_bytes)
            return True
        except (BrokenPipeError, OSError) as exc:
            self._last_error = f'Recording write failed: {exc}'
            log.error(self._last_error)
            self.stop()
            return False

    def stop(self) -> Path | None:
        """Stop the current recording and return the output path, if any."""
        process = self._process
        output_path = self._current_path
        if process is None:
            return output_path
        try:
            if process.stdin is not None:
                process.stdin.close()
            return_code = process.wait(timeout=10.0)
            if return_code != 0:
                self._last_error = f'Recording exited with code {return_code}'
                log.warning(self._last_error)
            elif output_path is not None:
                log.info('Recording saved: %s', output_path)
        except Exception as exc:
            self._last_error = f'Recording stop failed: {exc}'
            log.warning(self._last_error)
        finally:
            self._process = None
            self._current_path = None
        return output_path