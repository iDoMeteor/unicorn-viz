"""
Audio capture via sounddevice (PipeWire / PulseAudio monitor).

Linux: raw ALSA hostapi devices are intentionally skipped — PortAudio's
ALSA backend aborts at the C level when a device disappears mid-stream
(e.g. mic toggled off), and on modern Fedora/Arch the PipeWire shim
through PulseAudio is the right path anyway.
Feeds a ring buffer consumed by the analyzer on the main thread.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception as e:
    log.warning("sounddevice unavailable: %s — audio disabled", e)
    _SD_AVAILABLE = False

_SAMPLE_RATE = 48000   # PipeWire default; 44100 fallback attempted at runtime
_BLOCK_SIZE = 1024
_CHANNELS = 2
_WARMUP_DURATION = 0.3  # seconds: time to let buffer stabilize after stream opens
_STATUS_LOG_INTERVAL = 2.0
_OPEN_DEVICE_TIMEOUT_S = 1.5  # guard against hostapi/device open hangs
_CLOSE_STREAM_TIMEOUT_S = 1.0
_DEFAULT_FALLBACK_RMS_THRESHOLD = 0.0015
_DEFAULT_FALLBACK_SILENCE_SECONDS = 6.0
_DEFAULT_FALLBACK_COOLDOWN_SECONDS = 8.0


def _candidate_monitor_devices(hint: str) -> list[int | None]:
    """Return ordered candidate input devices for auto-fallback probing.

    On Linux the ALSA hostapi is deliberately skipped in favour of
    PulseAudio / PipeWire / JACK.  PortAudio's ALSA backend is unstable
    when devices appear/disappear at runtime (e.g. mic toggled off mid-
    stream causes a C-level assertion).  PulseAudio's PipeWire shim is
    the modern path on Fedora/Arch and handles device loss gracefully.
    """
    if not _SD_AVAILABLE:
        return [None]
    try:
        devices = sd.query_devices()
    except Exception:
        return [None]

    is_linux = sys.platform.startswith('linux')
    is_windows = sys.platform.startswith('win')

    hostapi_names: dict[int, str] = {}
    try:
        hostapis = sd.query_hostapis()
        for idx, info in enumerate(hostapis):
            hostapi_names[idx] = str(info.get('name', '')).lower()
    except Exception:
        hostapi_names = {}

    def _hostapi_for(d: dict) -> str:
        return hostapi_names.get(int(d.get('hostapi', -1)), '')

    def _is_alsa(d: dict) -> bool:
        # Match the ALSA hostapi only; the PulseAudio / PipeWire shim
        # hostapis often have 'alsa' nowhere in their name.
        return _hostapi_for(d).strip() == 'alsa'

    def _is_pseudo_input(name: str) -> bool:
        lower = name.strip().lower()
        return any(
            key in lower for key in (
                'speech-dispatcher',
                'audio-src',
                'dummy',
                'alsa capture [python',
                'pipewire alsa [python',
            )
        )

    hint_lower = hint.lower()
    if hint_lower:
        matches = [
            i for i, d in enumerate(devices)
            if d.get('max_input_channels', 0) >= 1
            and hint_lower in d['name'].lower()
            and not (is_linux and _is_alsa(d))
            and not (is_linux and _is_pseudo_input(str(d.get('name', ''))))
        ]
        return matches or [None]

    # Compute one best rank per device to avoid duplicate candidates.
    best_rank: dict[int, int] = {}

    # Check for OBS (informational only)
    for i, d in enumerate(devices):
        if d.get('max_input_channels', 0) < 1:
            continue
        name = d['name'].lower()
        if is_linux and _is_pseudo_input(name):
            continue
        if 'obs' in name:
            log.info("Audio: OBS detected: device %d (%s)", i, d['name'])

    # Rank candidates:
    # Linux:
    #   0 = PipeWire/Pulse monitor sources
    #   1 = PipeWire/Pulse default input
    #   2 = other PipeWire/Pulse inputs
    #   3 = preferred app sources on non-JACK hostapis
    #   4 = browser app sources on non-JACK hostapis
    #   5 = generic non-OBS monitor
    #   8 = JACK sources (de-prioritized due to startup instability)
    # Windows:
    #   0 = WASAPI loopback
    #   1 = stereo mix / what-u-hear
    # 99 = OBS, raw ALSA on Linux, and unknown/undesired inputs
    for i, d in enumerate(devices):
        if d.get('max_input_channels', 0) < 1:
            continue
        name = d['name'].lower()
        if is_linux and _is_pseudo_input(name):
            continue
        hostapi_name = _hostapi_for(d)
        is_pipewire_like = (
            'pipewire' in hostapi_name
            or 'pulse' in hostapi_name
            or 'pulseaudio' in hostapi_name
        )
        is_jack = hostapi_name.strip() == 'jack audio connection kit'
        rank = 99

        if is_linux and _is_alsa(d):
            # Skip raw ALSA: portaudio's ALSA hostapi crashes on device loss.
            continue

        if is_windows and 'wasapi' in hostapi_name and 'loopback' in name:
            rank = 0
        elif is_windows and any(key in name for key in ('stereo mix', 'what u hear')):
            rank = 1
        elif is_linux and 'monitor' in name and 'obs' not in name and (
            is_pipewire_like or 'pipewire' in name or 'pulse' in name
        ):
            rank = 0
        elif is_linux and 'default' in name and is_pipewire_like:
            rank = 1
        elif is_linux and is_pipewire_like:
            rank = 2
        elif any(key in name for key in ('spotify', 'vlc', 'mpv')) and not is_jack:
            rank = 3
        elif any(key in name for key in ('firefox', 'chrome', 'chromium', 'brave')) and not is_jack:
            rank = 4
        elif 'monitor' in name and 'obs' not in name:
            rank = 5
        elif is_linux and any(
            key in name for key in ('speech-dispatcher', 'audio-src', 'dummy')
        ):
            rank = 98
        elif is_linux and is_jack and 'monitor' in name and 'obs' not in name:
            rank = 6
        elif is_linux and is_jack:
            rank = 8
        elif 'obs' in name:
            rank = 99

        prev = best_rank.get(i)
        if prev is None or rank < prev:
            best_rank[i] = rank

    ranked = sorted((rank, idx) for idx, rank in best_rank.items())
    candidates = [i for _, i in ranked]
    candidates.append(None)
    return candidates


class AudioCapture:
    """
    Runs a sounddevice InputStream in a background thread.
    Call `get_block()` to retrieve the latest PCM block (or None if silent).
    """

    def __init__(
        self,
        device_hint: str = "",
        buffer_seconds: float = 2.0,
        latency: str = "high",
        fallback_rms_threshold: float = _DEFAULT_FALLBACK_RMS_THRESHOLD,
        fallback_silence_seconds: float = _DEFAULT_FALLBACK_SILENCE_SECONDS,
        fallback_cooldown_seconds: float = _DEFAULT_FALLBACK_COOLDOWN_SECONDS,
        auto_fallback_enabled: bool = True,
    ) -> None:
        self._device_hint = device_hint
        self._buffer_seconds = buffer_seconds
        self._latency = latency
        self._sample_rate = _SAMPLE_RATE
        self._channels = _CHANNELS
        self._buf: deque[np.ndarray] = deque(
            maxlen=int(_SAMPLE_RATE * buffer_seconds / _BLOCK_SIZE) + 1
        )
        self._lock = threading.Lock()
        self._stream: "sd.InputStream | None" = None
        self._active = False
        self._candidate_devices: list[int | None] = []
        self._candidate_index = 0
        self._silent_blocks = 0
        self._stream_opened_time: float = 0.0  # Track when stream opens for warmup
        self._last_status_log_time = 0.0
        self._suppressed_status_count = 0
        self._fallback_rms_threshold = max(0.0, float(fallback_rms_threshold))
        self._fallback_silence_seconds = max(0.25, float(fallback_silence_seconds))
        self._fallback_cooldown_seconds = max(0.0, float(fallback_cooldown_seconds))
        self._auto_fallback_enabled = bool(auto_fallback_enabled)
        self._last_fallback_time = 0.0

    def _open_stream(self, device: int | None) -> None:
        native_rate: int = _SAMPLE_RATE
        native_channels: int = _CHANNELS
        if device is not None:
            try:
                info = sd.query_devices(device)
                native_rate = int(info.get('default_samplerate', _SAMPLE_RATE))
                native_channels = min(_CHANNELS, int(info.get('max_input_channels', _CHANNELS)))
            except Exception:
                pass
        else:
            try:
                info = sd.query_devices(kind='input')
                native_rate = int(info.get('default_samplerate', _SAMPLE_RATE))
                native_channels = min(_CHANNELS, int(info.get('max_input_channels', _CHANNELS)))
            except Exception:
                pass

        self._sample_rate = native_rate
        self._channels = native_channels
        new_maxlen = int(native_rate * self._buffer_seconds / _BLOCK_SIZE) + 1
        log.debug("Audio: opening stream device=%s rate=%d channels=%d buffer_size=%d", device, native_rate, native_channels, new_maxlen)
        with self._lock:
            self._buf = deque(maxlen=new_maxlen)
        self._stream = sd.InputStream(
            device=device,
            samplerate=native_rate,
            channels=native_channels,
            blocksize=_BLOCK_SIZE,
            dtype=np.float32,
            callback=self._callback,
            latency=self._latency,
        )
        self._stream.start()
        self._active = True
        self._silent_blocks = 0
        self._stream_opened_time = time.time()  # Start warmup timer
        self._last_fallback_time = self._stream_opened_time
        # Clear any overflow frames from the buffer during the initial stream setup
        with self._lock:
            self._buf.clear()
        log.debug("Audio: stream opened, buffer cleared, warmup period %.1fs", _WARMUP_DURATION)
        if device is not None:
            dev_info = sd.query_devices(device)
            dev_name = dev_info['name']
            hostapi_label = ''
            try:
                hostapis = sd.query_hostapis()
                hostapi_label = str(hostapis[int(dev_info.get('hostapi', -1))].get('name', '')).strip()
            except Exception:
                pass
            log.info(
                'Audio capture: device %d (%s) [hostapi=%s] at %d Hz (native rate)',
                device, dev_name, hostapi_label or 'unknown', native_rate,
            )
        else:
            log.info('Audio capture: using default input device at %d Hz', native_rate)
        log.info('Audio capture started: %d Hz, %d ch, latency=%s', native_rate, native_channels, self._latency)

    def _describe_device(self, device: int | None) -> str:
        if device is None:
            return 'default input'
        try:
            info = sd.query_devices(device)
            return f"{device} ({info.get('name', 'unknown')})"
        except Exception:
            return f'{device} (unknown)'

    def _probe_device_openable(self, device: int | None, timeout_s: float) -> bool:
        """Probe whether a device can open in an isolated process.

        PortAudio can deadlock in-process on some broken endpoints; probing in a
        subprocess keeps the main process clean and lets startup skip bad devices.
        """
        device_expr = 'None' if device is None else str(int(device))
        code = (
            'import sounddevice as sd\n'
            f'device = {device_expr}\n'
            'try:\n'
            '    info = sd.query_devices(kind="input") if device is None else sd.query_devices(device)\n'
            '    rate = int(info.get("default_samplerate", 48000))\n'
            '    channels = max(1, min(2, int(info.get("max_input_channels", 2))))\n'
            '    stream = sd.InputStream(\n'
            '        device=device,\n'
            '        samplerate=rate,\n'
            '        channels=channels,\n'
            '        blocksize=1024,\n'
            '        dtype="float32",\n'
            '    )\n'
            '    stream.start()\n'
            '    stream.stop()\n'
            '    stream.close()\n'
            'except Exception:\n'
            '    raise SystemExit(2)\n'
            'raise SystemExit(0)\n'
        )
        try:
            result = subprocess.run(
                [sys.executable, '-c', code],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
        return result.returncode == 0

    def _close_stream_safely(self, stream: object | None, context: str) -> None:
        """Close a sounddevice stream with a bounded timeout.

        Some hostapi/device combinations can block indefinitely on stop/close;
        run teardown in a daemon thread so app shutdown is never stuck.
        """
        if stream is None:
            return

        def _close_worker() -> None:
            try:
                abort = getattr(stream, 'abort', None)
                if callable(abort):
                    abort()
            except Exception:
                pass
            try:
                stop = getattr(stream, 'stop', None)
                if callable(stop):
                    stop()
            except Exception:
                pass
            try:
                close = getattr(stream, 'close', None)
                if callable(close):
                    close()
            except Exception:
                pass

        worker = threading.Thread(
            target=_close_worker,
            name='uv-audio-close',
            daemon=True,
        )
        worker.start()
        worker.join(timeout=_CLOSE_STREAM_TIMEOUT_S)
        if worker.is_alive():
            log.warning(
                'Audio: stream close timed out after %.2fs during %s; continuing shutdown',
                _CLOSE_STREAM_TIMEOUT_S,
                context,
            )

    def start(self) -> None:
        if not _SD_AVAILABLE:
            log.info("Audio capture disabled (sounddevice not available)")
            return

        self._candidate_devices = _candidate_monitor_devices(self._device_hint)
        log.debug("Audio: candidate devices = %s", self._candidate_devices)

        last_exc: Exception | None = None
        for idx, device in enumerate(self._candidate_devices):
            self._candidate_index = idx
            try:
                if not self._probe_device_openable(device, timeout_s=_OPEN_DEVICE_TIMEOUT_S):
                    raise TimeoutError(
                        f'Audio device probe timed out/failed for '
                        f'{self._describe_device(device)}'
                    )
                self._open_stream(device)
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    'Audio open failed for candidate %s: %s',
                    self._describe_device(device),
                    exc,
                )

        if last_exc is not None:
            log.warning('Could not open any audio stream candidate: %s', last_exc)
        else:
            log.warning('Could not open any audio stream candidate')

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        if status:
            now = time.time()
            if now - self._last_status_log_time >= _STATUS_LOG_INTERVAL:
                if self._suppressed_status_count > 0:
                    log.warning(
                        'Audio callback status: %s (%d similar warnings suppressed)',
                        status,
                        self._suppressed_status_count,
                    )
                else:
                    log.warning('Audio callback status: %s', status)
                self._last_status_log_time = now
                self._suppressed_status_count = 0
            else:
                self._suppressed_status_count += 1
        mono = indata.mean(axis=1) if indata.ndim > 1 and indata.shape[1] > 1 else indata[:, 0]
        rms = float(np.sqrt(np.mean(mono * mono)))
        if rms < self._fallback_rms_threshold:
            self._silent_blocks += 1
        else:
            self._silent_blocks = 0
        with self._lock:
            self._buf.append(mono.copy())
        if len(self._buf) == 1:
            log.debug("Audio: first block received (rms=%.4f, silent_blocks=%d)", rms, self._silent_blocks)

    def maybe_fallback(self) -> None:
        """Switch to next candidate device if current source appears silent.
        
        Suppressed during warmup to avoid device switches that cause overflow.
        """
        if not self._auto_fallback_enabled:
            return
        if not self._is_warmed_up():
            log.debug("Audio: fallback check suppressed during warmup")
            return
        if self._device_hint or len(self._candidate_devices) <= 1:
            return
        now = time.time()
        if self._fallback_cooldown_seconds > 0.0:
            if now - self._last_fallback_time < self._fallback_cooldown_seconds:
                return
        silent_time = self._silent_blocks * (_BLOCK_SIZE / max(self._sample_rate, 1))
        if silent_time < self._fallback_silence_seconds:
            return
        if self._candidate_index + 1 >= len(self._candidate_devices):
            log.debug("Audio: silent for %.2fs but no more fallback candidates", silent_time)
            return
        log.debug("Audio: silent for %.2fs, attempting fallback (current=%d)", silent_time, self._candidate_index)

        current_idx = self._candidate_index
        current = self._candidate_devices[current_idx]
        next_idx = current_idx + 1
        nxt = self._candidate_devices[next_idx]
        try:
            if self._stream is not None:
                self._close_stream_safely(self._stream, context='audio fallback')
                self._stream = None
            current_name = sd.query_devices(current)['name'] if current is not None else 'None'
            next_name = sd.query_devices(nxt)['name'] if nxt is not None else 'default'
            log.info(
                'Audio capture: source %r silent, trying fallback %d (%s)',
                current_name, nxt if nxt is not None else -1, next_name,
            )
            self._open_stream(nxt)
            self._candidate_index = next_idx
            self._last_fallback_time = time.time()
        except Exception as exc:
            log.warning('Audio fallback failed: %s', exc)
            # Attempt to recover the prior source so we do not report active
            # capture while no stream exists.
            try:
                log.info('Audio: restoring previous source %s after fallback failure', self._describe_device(current))
                self._open_stream(current)
                self._candidate_index = current_idx
            except Exception as restore_exc:
                log.warning('Audio restore after fallback failure also failed: %s', restore_exc)
                self._stream = None
                self._active = False

    def _is_warmed_up(self) -> bool:
        """Check if stream has had enough time to stabilize after opening."""
        if self._stream_opened_time == 0.0:
            return False
        elapsed = time.time() - self._stream_opened_time
        return elapsed >= _WARMUP_DURATION

    def get_block(self) -> np.ndarray | None:
        # Skip audio consumption during warmup to avoid buffer overflow
        if not self._is_warmed_up():
            log.debug("Audio: warming up (%.1fs so far)", time.time() - self._stream_opened_time)
            return None
        with self._lock:
            if not self._buf:
                return None
            return self._buf[-1]

    def get_history(self, n_blocks: int) -> np.ndarray:
        """Return the last n_blocks concatenated as a single float32 array."""
        with self._lock:
            blocks = list(self._buf)[-n_blocks:]
        if not blocks:
            return np.zeros(_BLOCK_SIZE * n_blocks, dtype=np.float32)
        return np.concatenate(blocks)

    def stop(self) -> None:
        if self._stream is not None:
            self._close_stream_safely(self._stream, context='shutdown')
            self._stream = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_size(self) -> int:
        return _BLOCK_SIZE

    def current_source_label(self) -> str:
        """Return a human-readable label for the currently active audio source."""
        if not _SD_AVAILABLE:
            return 'disabled'
        if not self._active:
            return 'inactive'
        device = None
        if self._candidate_devices and 0 <= self._candidate_index < len(self._candidate_devices):
            device = self._candidate_devices[self._candidate_index]
        if device is None:
            return 'default input'
        try:
            info = sd.query_devices(device)
            name = str(info.get('name', f'device {device}')).strip()
            return name or f'device {device}'
        except Exception:
            return f'device {device}'
