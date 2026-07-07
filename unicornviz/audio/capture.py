"""
Audio capture via sounddevice (PipeWire / PulseAudio monitor).

Linux: raw ALSA hostapi devices are intentionally skipped — PortAudio's
ALSA backend aborts at the C level when a device disappears mid-stream
(e.g. mic toggled off), and on modern Fedora/Arch the PipeWire shim
through PulseAudio is the right path anyway.

Capture strategy: blocking-read daemon thread (not callback mode).  A
dedicated ``uv-audio-reader`` thread calls ``stream.read(blocksize)``
in a tight loop and pushes mono blocks into a ``deque`` ring buffer.
PortAudio buffers internally; when the render thread holds the GIL
longer than one period, the reader thread simply catches up on the next
schedule slice — no PortAudio xrun, no audible static.  The main thread
reads ``get_block()`` / ``get_history()`` without doing any I/O.

Block-sequence counter: ``block_seq`` increments each time a new block
is appended by the reader.  ``AudioManager.get_audio_data()`` compares
the counter each frame and skips the FFT when no new block has arrived
(~60 fps render vs ~47 Hz audio blocks at 48 kHz/1024).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from unicornviz.runtime_state import RuntimeStateStore

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
_CLOSE_STREAM_TIMEOUT_S = 3.0
_DEFAULT_FALLBACK_RMS_THRESHOLD = 0.0015
_DEFAULT_FALLBACK_SILENCE_SECONDS = 6.0
_DEFAULT_FALLBACK_COOLDOWN_SECONDS = 8.0


def _normalize_latency(latency: str | float) -> str | float:
    """Return a sounddevice-compatible latency value.

    sounddevice accepts 'low'/'high' or numeric seconds. Keep support for
    config value 'medium' by mapping it to a conservative numeric latency.
    """
    if isinstance(latency, (int, float)):
        return max(0.0, float(latency))

    value = str(latency).strip().lower()
    if value in ('low', 'high'):
        return value
    if value == 'medium':
        # PortAudio does not accept the string 'medium'; use a stable midpoint.
        return 0.06

    log.warning(
        'Audio latency value %r is unsupported; using high latency fallback',
        latency,
    )
    return 'high'


def _candidate_monitor_devices(
    hint: str,
    *,
    prefer_default_input: bool = False,
) -> list[int | None]:
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
    if prefer_default_input:
        # Startup policy: when no explicit device hint is configured, try the
        # current OS default source first. Operators can still pick any source
        # from the selector, and auto-fallback can still advance if needed.
        candidates.insert(0, None)
    else:
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
        latency: str | float = 'high',
        prefer_default_input: bool = False,
        fallback_rms_threshold: float = _DEFAULT_FALLBACK_RMS_THRESHOLD,
        fallback_silence_seconds: float = _DEFAULT_FALLBACK_SILENCE_SECONDS,
        fallback_cooldown_seconds: float = _DEFAULT_FALLBACK_COOLDOWN_SECONDS,
        auto_fallback_enabled: bool = True,
        block_size: int = _BLOCK_SIZE,
        state_store: RuntimeStateStore | None = None,
    ) -> None:
        self._device_hint = device_hint
        self._buffer_seconds = buffer_seconds
        self._latency = _normalize_latency(latency)
        self._blocksize: int = max(64, int(block_size))
        self._sample_rate = _SAMPLE_RATE
        self._channels = _CHANNELS
        self._buf: deque[np.ndarray] = deque(
            maxlen=int(_SAMPLE_RATE * buffer_seconds / self._blocksize) + 1
        )
        self._lock = threading.Lock()
        self._stream: "sd.InputStream | None" = None
        # Blocking-read capture thread and its stop signal.
        self._stop_event: threading.Event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        # Event that the reader sets on every new block.  The analysis thread
        # in AudioManager waits on this instead of polling, so it wakes
        # immediately when audio arrives and idles with zero CPU when silent.
        self._new_block_event: threading.Event = threading.Event()
        # Monotonic block-sequence counter: incremented by the reader on every
        # new block.  get_block_if_new() uses this to return a copy only when
        # the block has changed since the caller's last call.
        self._block_seq: int = 0
        # Cumulative input-overflow counter for HUD diagnostics.
        self._xrun_count: int = 0
        self._active = False
        self._candidate_devices: list[int | None] = []
        self._candidate_index = 0
        self._silent_blocks = 0
        self._stream_opened_time: float = 0.0  # Track when stream opens for warmup
        self._last_status_log_time = 0.0
        self._suppressed_status_count = 0
        # Auto-source switching now only considers operator-tagged viable sources.
        self._fallback_rms_threshold = max(0.0, float(fallback_rms_threshold))
        self._fallback_silence_seconds = max(0.25, float(fallback_silence_seconds))
        self._fallback_cooldown_seconds = max(0.0, float(fallback_cooldown_seconds))
        self._auto_fallback_enabled = bool(auto_fallback_enabled)
        self._prefer_default_input = bool(prefer_default_input)
        self._last_fallback_time = 0.0
        self._state_store = state_store
        self._selected_source_key: str | None = None
        self._viable_source_keys: set[str] = set()
        self._load_source_state()

    def _load_source_state(self) -> None:
        """Load audio source preferences from runtime state store or skip if none."""
        if self._state_store is None:
            return
        try:
            payload = self._state_store.get('audio', default={})
            if not isinstance(payload, dict):
                return
            selected = payload.get('selected_source_key')
            if isinstance(selected, str) and selected:
                self._selected_source_key = selected
            viable = payload.get('viable_source_keys', [])
            if isinstance(viable, list):
                self._viable_source_keys = {
                    str(item) for item in viable if isinstance(item, str) and item
                }
        except Exception as exc:
            log.debug('Audio source state load skipped: %s', exc)

    def _save_source_state(self) -> None:
        """Save audio source preferences to runtime state store or skip if none."""
        if self._state_store is None:
            return
        try:
            payload = {
                'selected_source_key': self._selected_source_key or '',
                'viable_source_keys': sorted(self._viable_source_keys),
            }
            self._state_store.set('audio', payload)
        except Exception as exc:
            log.warning('Audio source state save failed: %s', exc)

    def _source_key_for_device(self, device: int | None) -> str:
        if device is None:
            return 'default'
        try:
            info = sd.query_devices(device)
            name = str(info.get('name', '')).strip().lower()
            if name:
                return f'name:{name}'
        except Exception:
            pass
        return f'idx:{device}'

    def _candidate_keys(self) -> list[str]:
        return [self._source_key_for_device(device) for device in self._candidate_devices]

    def _apply_source_state_preferences(self) -> None:
        if not self._candidate_devices:
            return

        # Honor persisted selection unless a config device hint is explicitly set.
        if self._selected_source_key and not self._device_hint:
            keys = self._candidate_keys()
            if self._selected_source_key in keys:
                target = keys.index(self._selected_source_key)
                if target != 0:
                    selected = self._candidate_devices.pop(target)
                    self._candidate_devices.insert(0, selected)

        candidate_keys = self._candidate_keys()
        if not self._viable_source_keys:
            self._viable_source_keys = set(candidate_keys)
            self._save_source_state()
            return
        valid = {k for k in self._viable_source_keys if k in candidate_keys}
        if not valid:
            valid = set(candidate_keys)
        self._viable_source_keys = valid

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
        new_maxlen = int(native_rate * self._buffer_seconds / self._blocksize) + 1
        log.debug(
            'Audio: opening stream device=%s rate=%d ch=%d blocksize=%d slots=%d',
            device, native_rate, native_channels, self._blocksize, new_maxlen,
        )
        with self._lock:
            self._buf = deque(maxlen=new_maxlen)
        # Open in blocking-read mode (no callback= argument).  PortAudio
        # buffers internally; the reader thread drains it on its own schedule
        # so a GIL hold on the render thread can never cause an xrun.
        self._stop_event.clear()
        self._stream = sd.InputStream(
            device=device,
            samplerate=native_rate,
            channels=native_channels,
            blocksize=self._blocksize,
            dtype=np.float32,
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
        self._new_block_event.clear()  # discard stale wake-up from previous stream session
        log.debug('Audio: stream opened, buffer cleared, warmup period %.1fs', _WARMUP_DURATION)
        # Start the blocking-read daemon thread
        self._reader_thread = threading.Thread(
            target=self._blocking_reader_worker,
            name='uv-audio-reader',
            daemon=True,
        )
        self._reader_thread.start()
        log.debug('Audio: blocking-read capture thread started')
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

        self._candidate_devices = _candidate_monitor_devices(
            self._device_hint,
            prefer_default_input=self._prefer_default_input,
        )
        self._apply_source_state_preferences()
        self._candidate_index = 0
        log.debug("Audio: candidate devices = %s", self._candidate_devices)

        last_exc: Exception | None = None
        for idx, device in enumerate(self._candidate_devices):
            self._candidate_index = idx
            try:
                self._open_stream(device)
                self._selected_source_key = self._source_key_for_device(device)
                self._save_source_state()
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

    def wait_for_new_block(self, timeout_s: float = 0.5) -> bool:
        """Block until the reader signals a new block or timeout expires.

        Returns True when a new block arrived, False on timeout.  The caller
        should then call ``get_block_if_new()`` to retrieve it.  Clears the
        internal event before returning so back-to-back calls are safe.

        Designed for the analysis thread; only one thread should call this.
        """
        signalled = self._new_block_event.wait(timeout=timeout_s)
        if signalled:
            self._new_block_event.clear()
        return signalled

    def get_block_if_new(self, last_seq: int) -> tuple[np.ndarray | None, int]:
        """Return ``(block_copy, current_seq)`` when a new block has arrived.

        Returns ``(None, last_seq)`` when ``block_seq`` has not advanced since
        the previous call.  The returned array is a copy so the analysis thread
        may hold it safely across the full FFT pipeline while the reader thread
        continues appending to the ring buffer.
        """
        with self._lock:
            current_seq = self._block_seq
            if current_seq == last_seq or not self._buf:
                return None, last_seq
            return self._buf[-1].copy(), current_seq

    def signal_new_block(self) -> None:
        """Force-set the new-block event to unblock a waiting analysis thread.

        Called by AudioManager.stop() so the analysis thread wakes immediately
        and sees the stop flag instead of waiting up to ``timeout_s`` seconds.
        """
        self._new_block_event.set()

    def _stop_reader_thread(self, stream: object | None = None) -> bool:
        """Signal the reader thread to stop and wait up to the close timeout.

        Aborts ``stream`` first (if given) so an in-flight blocking
        ``stream.read()`` call unblocks immediately instead of racing a
        later ``stop()``/``close()`` from another thread — closing a
        PortAudio/ALSA stream while a read is still in flight on it is a
        real crash (segfault) risk, not just a leak.

        Returns True if the reader thread actually exited within the
        timeout. Callers must not close/reuse ``stream`` when this is False
        — the reader may still be inside ``stream.read()``.
        """
        self._stop_event.set()
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        if self._reader_thread is None:
            return True
        self._reader_thread.join(timeout=_CLOSE_STREAM_TIMEOUT_S)
        exited = not self._reader_thread.is_alive()
        if not exited:
            log.warning(
                'Audio: reader thread did not exit within %.2fs',
                _CLOSE_STREAM_TIMEOUT_S,
            )
        self._reader_thread = None
        return exited

    def _blocking_reader_worker(self) -> None:
        """Background daemon thread: block-reads from PortAudio into the ring buffer.

        Runs a tight ``stream.read(blocksize)`` loop.  PortAudio buffers frames
        internally so this thread just drains them.  If the render thread holds
        the GIL past one audio period the reader is delayed, but PortAudio's
        internal ring is not overflowed — no xrun, no static.  When overflow
        does occur (buffer overfilled before drain) PortAudio reports it via the
        ``overflow`` flag from ``stream.read()``; we count and log these.
        """
        blocksize = self._blocksize
        # Pre-allocate mono scratch to avoid a heap allocation per block.
        scratch = np.empty(blocksize, dtype=np.float32)
        is_first_block = True
        while not self._stop_event.is_set():
            stream = self._stream
            if stream is None or not self._active:
                break
            try:
                data, overflow = stream.read(blocksize)
            except Exception as exc:
                if not self._stop_event.is_set():
                    log.warning('Audio reader: stream.read() failed: %s', exc)
                    self._active = False
                break
            if overflow:
                self._xrun_count += 1
                now = time.time()
                if now - self._last_status_log_time >= _STATUS_LOG_INTERVAL:
                    if self._suppressed_status_count > 0:
                        log.warning(
                            'Audio reader: input overflow (%d similar suppressed)',
                            self._suppressed_status_count,
                        )
                    else:
                        log.warning('Audio reader: input overflow')
                    self._last_status_log_time = now
                    self._suppressed_status_count = 0
                else:
                    self._suppressed_status_count += 1
            # Downmix to mono using pre-allocated scratch (no per-block heap alloc)
            n = len(data)
            if data.ndim > 1 and data.shape[1] > 1:
                np.mean(data[:n], axis=1, out=scratch[:n])
                mono = scratch[:n]
            else:
                mono = data[:n, 0] if data.ndim > 1 else data[:n]
            rms = float(np.sqrt(np.mean(mono * mono)))
            if rms < self._fallback_rms_threshold:
                self._silent_blocks += 1
            else:
                self._silent_blocks = 0
            with self._lock:
                self._buf.append(mono.copy())
                self._block_seq += 1
            self._new_block_event.set()  # wake analysis thread
            if is_first_block:
                log.debug('Audio: first block received (rms=%.4f)', rms)
                is_first_block = False

    def _next_viable_candidate_index(self, current_idx: int) -> int | None:
        if len(self._candidate_devices) <= 1:
            return None
        keys = self._candidate_keys()
        for step in range(1, len(self._candidate_devices)):
            idx = (current_idx + step) % len(self._candidate_devices)
            if keys[idx] in self._viable_source_keys:
                return idx
        return None

    def _probe_source_rms(self, device: int | None, timeout_s: float = 0.8) -> float | None:
        """Probe RMS for a candidate source in a subprocess.

        Returns None when probing fails/times out.
        """
        device_expr = 'None' if device is None else str(int(device))
        code = (
            'import numpy as np\n'
            'import sounddevice as sd\n'
            f'device = {device_expr}\n'
            'try:\n'
            '    info = sd.query_devices(kind="input") if device is None else sd.query_devices(device)\n'
            '    rate = int(info.get("default_samplerate", 48000))\n'
            '    channels = max(1, min(2, int(info.get("max_input_channels", 2))))\n'
            '    with sd.InputStream(device=device, samplerate=rate, channels=channels, blocksize=1024, dtype="float32") as stream:\n'
            '        data, _ = stream.read(1024)\n'
            '    mono = data.mean(axis=1) if data.ndim > 1 else data\n'
            '    rms = float(np.sqrt(np.mean(mono * mono)))\n'
            '    print(f"{rms:.8f}")\n'
            'except Exception:\n'
            '    raise SystemExit(2)\n'
        )
        try:
            result = subprocess.run(
                [sys.executable, '-c', code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        try:
            return float((result.stdout or '').strip())
        except Exception:
            return None

    def maybe_fallback(self) -> None:
        """Switch between viable sources when current source remains silent."""
        if not self._auto_fallback_enabled:
            return
        if not self._is_warmed_up():
            log.debug('Audio: fallback check suppressed during warmup')
            return
        if len(self._candidate_devices) <= 1:
            return
        if self._fallback_cooldown_seconds > 0.0:
            now = time.time()
            if now - self._last_fallback_time < self._fallback_cooldown_seconds:
                return
        silent_time = self._silent_blocks * (self._blocksize / max(self._sample_rate, 1))
        if silent_time < self._fallback_silence_seconds:
            return

        current_idx = self._candidate_index
        target_idx = self._next_viable_candidate_index(current_idx)
        if target_idx is None:
            return

        target_device = self._candidate_devices[target_idx]
        target_rms = self._probe_source_rms(target_device)
        if target_rms is None or target_rms < self._fallback_rms_threshold:
            log.debug(
                'Audio: candidate %s probe rms=%s below threshold %.5f; staying on current source',
                self._describe_device(target_device),
                'n/a' if target_rms is None else f'{target_rms:.5f}',
                self._fallback_rms_threshold,
            )
            return

        log.info(
            'Audio capture: current source silent for %.2fs; switching to viable source %s (probe rms=%.5f)',
            silent_time,
            self._describe_device(target_device),
            target_rms,
        )
        self._switch_to_candidate_index(target_idx)
        self._last_fallback_time = time.time()

    def _is_warmed_up(self) -> bool:
        """Check if stream has had enough time to stabilize after opening."""
        if self._stream_opened_time == 0.0:
            return False
        elapsed = time.time() - self._stream_opened_time
        return elapsed >= _WARMUP_DURATION

    def get_block(self) -> np.ndarray | None:
        # Skip audio consumption during warmup to avoid buffer overflow
        if not self._is_warmed_up():
            if self._stream_opened_time > 0.0:
                log.debug(
                    'Audio: warming up (%.1fs so far)',
                    time.time() - self._stream_opened_time,
                )
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
            return np.zeros(self._blocksize * n_blocks, dtype=np.float32)
        return np.concatenate(blocks)

    def stop(self) -> None:
        # Set stop flag before abort so the reader's except branch stays silent.
        self._stop_event.set()
        self._active = False
        stream = self._stream
        self._stream = None
        # Abort synchronously to unblock any in-progress stream.read() call
        # immediately.  The reader thread catches the resulting exception,
        # sees _stop_event set, and breaks without logging.  Only then do we
        # run the full stop/close sequence — with no reader racing the ALSA
        # buffer, PortAudio cleans up silently.
        reader_exited = self._stop_reader_thread(stream)
        if stream is None:
            return
        if reader_exited:
            self._close_stream_safely(stream, context='shutdown')
        else:
            # The reader may still be inside stream.read() on this exact
            # stream object — closing it now would race the ALSA teardown
            # from two threads at once, which is what was crashing on quit
            # (segfaults deep in PortAudio's ALSA hostapi). The reader is a
            # daemon thread, so abandoning the stream here is safe: it will
            # exit on its own once its current blocked read finally returns,
            # and the process is free to exit in the meantime regardless.
            log.warning(
                'Audio: skipping stream close during shutdown — reader thread '
                'still running would race it; leaving it to clean up on its own'
            )

    @property
    def active(self) -> bool:
        return self._active

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_size(self) -> int:
        return self._blocksize

    @property
    def block_seq(self) -> int:
        """Monotonic counter incremented by the reader on each new block.

        The analyzer compares this to its own last-seen value to skip FFT
        on frames where no new audio block has arrived.
        """
        return self._block_seq

    @property
    def xrun_count(self) -> int:
        """Cumulative input-overflow count since stream open.  0 = clean."""
        return self._xrun_count

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

    def source_labels(self) -> list[str]:
        """Return ordered candidate source labels for selector UI."""
        if not _SD_AVAILABLE:
            return ['disabled']
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        labels: list[str] = []
        for device in self._candidate_devices:
            labels.append(self._describe_device(device))
        return labels

    def current_source_index(self) -> int:
        """Return index of currently selected candidate device."""
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        if not self._candidate_devices:
            return 0
        return max(0, min(self._candidate_index, len(self._candidate_devices) - 1))

    def _switch_to_candidate_index(self, target_idx: int) -> str:
        """Switch capture stream to a specific candidate index."""
        if not _SD_AVAILABLE:
            return 'disabled'
        if not self._active:
            return 'inactive'
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        if not self._candidate_devices:
            return self.current_source_label()

        bounded_idx = max(0, min(int(target_idx), len(self._candidate_devices) - 1))
        current_idx = self._candidate_index
        if bounded_idx == current_idx:
            return self.current_source_label()

        current_device = self._candidate_devices[current_idx]
        target_device = self._candidate_devices[bounded_idx]
        try:
            old_stream = self._stream
            self._stream = None
            reader_exited = self._stop_reader_thread(old_stream)
            if old_stream is not None:
                if reader_exited:
                    self._close_stream_safely(old_stream, context='operator source select')
                else:
                    # See stop()'s comment: closing while the reader may still
                    # be inside read() on this stream risks a crash. Abandon
                    # it (daemon thread cleans up on its own) and proceed.
                    log.warning(
                        'Audio: reader thread still running after source-select '
                        'abort; abandoning old stream instead of racing its close'
                    )
            self._open_stream(target_device)
            self._candidate_index = bounded_idx
            self._selected_source_key = self._source_key_for_device(target_device)
            self._save_source_state()
            return self.current_source_label()
        except Exception as exc:
            log.warning('Audio source select failed: %s', exc)
            try:
                self._open_stream(current_device)
                self._candidate_index = current_idx
            except Exception as restore_exc:
                log.warning('Audio source restore failed after select error: %s', restore_exc)
                self._stream = None
                self._active = False
            return self.current_source_label()

    def select_source(self, index: int) -> str:
        """Select a specific capture source by candidate index."""
        return self._switch_to_candidate_index(index)

    def cycle_source(self, delta: int) -> str:
        """Switch to another candidate input source and return its label.

        This is an operator-triggered source switch used by live hotkeys.
        """
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        if len(self._candidate_devices) <= 1:
            return self.current_source_label()
        step = -1 if int(delta) < 0 else 1
        target_idx = (self.current_source_index() + step) % len(self._candidate_devices)
        return self._switch_to_candidate_index(target_idx)

    def source_viable_flags(self) -> list[bool]:
        """Return per-candidate viable flags used by selector UI."""
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        keys = self._candidate_keys()
        if not self._viable_source_keys:
            self._viable_source_keys = set(keys)
            self._save_source_state()
        return [k in self._viable_source_keys for k in keys]

    def toggle_source_viable(self, index: int) -> tuple[bool, str]:
        """Toggle viability tag for candidate index and persist selection state."""
        if not self._candidate_devices:
            self._candidate_devices = _candidate_monitor_devices(
                self._device_hint,
                prefer_default_input=self._prefer_default_input,
            )
            self._apply_source_state_preferences()
            self._candidate_index = 0
        if not self._candidate_devices:
            return False, 'No audio sources available'

        idx = max(0, min(int(index), len(self._candidate_devices) - 1))
        key = self._source_key_for_device(self._candidate_devices[idx])
        currently_viable = key in self._viable_source_keys
        if currently_viable:
            if len(self._viable_source_keys) <= 1:
                return True, 'At least one viable source must remain enabled'
            self._viable_source_keys.discard(key)
            self._save_source_state()
            return False, f'Viable source OFF: {self._describe_device(self._candidate_devices[idx])}'

        self._viable_source_keys.add(key)
        self._save_source_state()
        return True, f'Viable source ON: {self._describe_device(self._candidate_devices[idx])}'
