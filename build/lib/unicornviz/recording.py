"""Recording support for Unicorn Viz.

This module manages a simple ffmpeg subprocess that accepts raw RGB frames
from the app and writes H.264 MP4 output. V1 records video only.
"""
from __future__ import annotations

import logging
import signal
import subprocess
import time
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
        self._audio_input_format = str(cfg.get('recording', 'audio_input_format', default='pulse'))
        self._audio_input_device = str(cfg.get('recording', 'audio_input_device', default='')).strip()
        self._audio_codec = str(cfg.get('recording', 'audio_codec', default='aac'))
        self._audio_bitrate = str(cfg.get('recording', 'audio_bitrate', default='192k'))
        self._filename_prefix = str(cfg.get('recording', 'filename_prefix', default='unicornviz'))
        self._show_indicator = bool(cfg.get('recording', 'show_indicator', default=True))
        self._width = width
        self._height = height
        self._process: subprocess.Popen[bytes] | None = None
        self._current_path: Path | None = None
        self._started_at: float = 0.0
        self._resolved_audio_input: tuple[str, str] | None = None
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

    @property
    def elapsed_seconds(self) -> float:
        if not self.is_recording or self._started_at == 0.0:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    @property
    def resolved_audio_input(self) -> tuple[str, str] | None:
        return self._resolved_audio_input

    def _build_output_path(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return self._directory / f'{self._filename_prefix}_{ts}.{self._container}'

    def _resolve_pulse_source(self) -> str:
        """Resolve a Pulse/PipeWire source name, preferring the default sink monitor."""
        if self._audio_input_device:
            return self._audio_input_device
        try:
            proc = subprocess.run(
                ['pactl', 'info'],
                check=True,
                capture_output=True,
                text=True,
            )
            for line in proc.stdout.splitlines():
                if line.startswith('Default Sink:'):
                    sink = line.split(':', 1)[1].strip()
                    if sink:
                        return f'{sink}.monitor'
        except Exception as exc:
            log.debug('Could not resolve default sink monitor via pactl: %s', exc)
        return 'default'

    def _resolve_audio_input(self) -> tuple[str, str]:
        """Return the ffmpeg audio input format and device string."""
        input_format = self._audio_input_format.lower()
        if input_format == 'pulse':
            return 'pulse', self._resolve_pulse_source()
        return input_format, self._audio_input_device or 'default'

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
        ]
        if self._capture_audio:
            audio_format, audio_device = self._resolve_audio_input()
            self._resolved_audio_input = (audio_format, audio_device)
            command += [
                '-f',
                audio_format,
                '-i',
                audio_device,
            ]
        else:
            self._resolved_audio_input = None
        command += [
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
        if self._capture_audio:
            command += [
                '-c:a',
                self._audio_codec,
                '-b:a',
                self._audio_bitrate,
                '-shortest',
            ]
        else:
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
        log.debug(
            'Recording start requested: size=%dx%d fps=%d codec=%s preset=%s crf=%d audio=%s output=%s',
            self._width,
            self._height,
            self._fps,
            self._codec,
            self._preset,
            self._crf,
            self._capture_audio,
            output_path,
        )
        log.debug('Recording command: %s', ' '.join(command))
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_path = output_path
            self._started_at = time.monotonic()
            self._last_error = ''
            if self._resolved_audio_input is not None:
                log.info(
                    'Recording audio source: %s (%s)',
                    self._resolved_audio_input[1],
                    self._resolved_audio_input[0],
                )
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
        log.debug('Stopping recording: %s', output_path)
        try:
            if process.stdin is not None:
                process.stdin.close()
            try:
                return_code = process.wait(timeout=3.0 if self._capture_audio else 10.0)
            except subprocess.TimeoutExpired:
                log.debug('Recording stop timed out; sending SIGINT to ffmpeg for graceful finalize')
                process.send_signal(signal.SIGINT)
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
            self._started_at = 0.0
        return output_path