"""
AudioManager — owns AudioCapture + Analyzer, exposes get_audio_data().
Also manages MIDI (stub for now, full impl in Phase 6).
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from unicornviz.effects.base import AudioData
from unicornviz.audio.capture import AudioCapture
from unicornviz.audio.analyzer import Analyzer, OnsetEvent  # noqa: F401 (OnsetEvent re-exported)
from unicornviz.audio.profiles import AudioProfile, get_profile, list_profiles
from unicornviz.config import Config

if TYPE_CHECKING:
    from unicornviz.runtime_state import RuntimeStateStore

log = logging.getLogger(__name__)


class AudioManager:
    def __init__(
        self,
        cfg: Config,
        state_store: RuntimeStateStore | None = None,
    ) -> None:
        device_hint = cfg.get("audio", "device", default="")
        fft_bands = cfg.get("audio", "fft_bands", default=512)
        buffer_seconds = cfg.get("audio", "buffer_seconds", default=2.0)
        latency = cfg.get("audio", "latency", default="low")
        prefer_default_input = bool(
            cfg.get('audio', 'prefer_default_input', default=False)
        )
        fallback_rms_threshold = float(
            cfg.get('audio', 'fallback_rms_threshold', default=0.0015)
        )
        fallback_silence_seconds = float(
            cfg.get('audio', 'fallback_silence_seconds', default=6.0)
        )
        fallback_cooldown_seconds = float(
            cfg.get('audio', 'fallback_cooldown_seconds', default=8.0)
        )
        auto_fallback_enabled = bool(
            cfg.get('audio', 'auto_fallback_enabled', default=True)
        )
        # Silence gate thresholds (RMS).  Anything below ``silence_rms_floor``
        # is treated as no input; ``silence_rms_span`` is the RMS range above
        # the floor over which the spectrum scales 0 → 1.  Defaults are tuned
        # for PipeWire so monitor noise / ambient hum stays gated out.
        silence_floor = float(cfg.get("audio", "silence_rms_floor", default=0.0060))
        silence_span = float(cfg.get("audio", "silence_rms_span", default=0.045))
        # "reactivity" controls how strongly visuals respond to audio features.
        # Keep legacy "gain" as fallback for backward compatibility.
        self._reactivity = float(
            cfg.get("audio", "reactivity", default=cfg.get("audio", "gain", default=1.0))
        )
        self._reactivity = max(0.1, min(5.0, self._reactivity))
        self._reactivity_default = self._reactivity
        
        # Audio profile selection. Defaults to "house" (2026-08-06, reverted
        # from a brief "generic" default -- see config.py's DEFAULT_CONFIG
        # comment for why "generic" didn't hold up: it's enabled=False in
        # PROFILES on purpose, a loose/uninformative catch-all never meant
        # to be a real starting analyzer profile, and its weak targets were
        # a noticeably worse start for training sessions specifically).
        self._profile_key = str(cfg.get("audio", "profile", default="house"))
        self._profile = get_profile(self._profile_key)
        
        self._capture = AudioCapture(
            device_hint=device_hint,
            buffer_seconds=buffer_seconds,
            latency=latency,
            prefer_default_input=prefer_default_input,
            fallback_rms_threshold=fallback_rms_threshold,
            fallback_silence_seconds=fallback_silence_seconds,
            fallback_cooldown_seconds=fallback_cooldown_seconds,
            auto_fallback_enabled=auto_fallback_enabled,
            block_size=max(64, min(8192, int(cfg.get('audio', 'blocksize', default=1024)))),
            state_store=state_store,
        )
        self._analyzer = Analyzer(
            fft_bands=fft_bands,
            profile=self._profile,
            silence_rms_floor=silence_floor,
            silence_rms_span=silence_span,
        )
        self._last_data = AudioData()
        self._last_data_raw = AudioData()
        # P1 — dedicated analysis thread (uv-audio-analyzer).
        #
        # The analyzer owns its own daemon thread so numpy FFT computation
        # never runs on the main render thread and can never hold the GIL
        # at the same time as the audio capture deadline.
        #
        # Double-buffer design:
        #   _back_buf  — analysis thread writes here
        #   _front_buf — latest published snapshot; main thread copies from here
        # The thread swaps them atomically under _analysis_lock after each block.
        # Main thread holds the lock only for the duration of the copy (~2 KB).
        self._front_buf: AudioData = AudioData()
        self._back_buf: AudioData = AudioData()
        self._analysis_lock: threading.Lock = threading.Lock()
        self._analysis_stop: threading.Event = threading.Event()
        self._analysis_thread: threading.Thread | None = None
        # Onset events published by the analysis thread, drained by main thread.
        self._onset_pending: list[OnsetEvent] = []
        # Audio timestamp of the last published block.  Written under
        # _analysis_lock by the analysis thread; read by get_audio_time() on the
        # main thread.  Keeping it here avoids reading analyzer internal state
        # across thread boundaries without a lock.
        self._published_audio_time: float = 0.0
        # Whether start() has completed. A never-started manager (mixer-only
        # boot profile) still answers get_audio_data() with its pre-allocated
        # silent buffers, but must not run the capture fallback prober.
        self._started: bool = False

    @staticmethod
    def _copy_audio_into(source: AudioData, target: AudioData) -> None:
        """Copy all fields from source into target in-place (no allocation)."""
        target.bass = source.bass
        target.mid = source.mid
        target.treble = source.treble
        target.bass_n = source.bass_n
        target.mid_n = source.mid_n
        target.treble_n = source.treble_n
        target.beat = source.beat
        target.bpm = source.bpm
        target.bass_flux = source.bass_flux
        target.mid_flux = source.mid_flux
        target.spectral_flux = source.spectral_flux
        target.fft[:] = source.fft
        target.waveform[:] = source.waveform
        target.bands[:] = source.bands

    def start(self, timeout_s: float | None = None) -> None:
        """Start audio capture and require an active capture source.

        If ``timeout_s`` is provided and positive, capture startup runs in a
        short-lived daemon thread so startup can fail fast instead of hanging
        indefinitely in native audio backends.
        """

        log.debug('AudioManager: starting capture')

        if timeout_s is None or timeout_s <= 0:
            self._capture.start()
        else:
            start_exc: Exception | None = None

            def _start_capture() -> None:
                nonlocal start_exc
                try:
                    self._capture.start()
                except Exception as exc:  # pragma: no cover - defensive only
                    start_exc = exc

            worker = threading.Thread(
                target=_start_capture,
                name='uv-audio-start',
                daemon=True,
            )
            worker.start()
            worker.join(timeout=float(timeout_s))
            if worker.is_alive():
                raise TimeoutError(
                    f'Audio capture startup timed out after {float(timeout_s):.2f}s'
                )
            if start_exc is not None:
                raise RuntimeError(f'Audio capture startup failed: {start_exc}') from start_exc

        if not self._capture.active:
            raise RuntimeError('Audio capture did not become active')

        log.info(
            'AudioManager: capture active (source=%s)',
            self._capture.current_source_label(),
        )

        # Start the dedicated analysis thread now that capture is live.
        self._analysis_stop.clear()
        self._analysis_thread = threading.Thread(
            target=self._analysis_worker,
            name='uv-audio-analyzer',
            daemon=True,
        )
        self._analysis_thread.start()
        self._started = True
        log.info('AudioManager: analysis thread started')

    def stop(self) -> None:
        # Signal the analysis thread and unblock its wait immediately.
        self._analysis_stop.set()
        self._capture.signal_new_block()
        if self._analysis_thread is not None:
            self._analysis_thread.join(timeout=2.0)
            if self._analysis_thread.is_alive():
                log.warning('AudioManager: analysis thread did not exit within 2.0s')
            self._analysis_thread = None
        self._capture.stop()
        # Pa_Terminate() must be called after all streams are closed and before
        # Python's GC runs.  Without it the PortAudio ALSA host-API thread can
        # still be inside PaAlsaStream_WaitForFrames() when cffi callback objects
        # are collected, causing SIGSEGV.  The import is guarded so the no-audio
        # path is unaffected.
        try:
            import sounddevice as _sd  # noqa: PLC0415
            _sd.terminate()
            log.debug('AudioManager: sounddevice.terminate() called')
        except Exception as exc:
            log.debug('AudioManager: sounddevice.terminate() skipped: %s', exc)

    def _analysis_worker(self) -> None:
        """Daemon thread: process audio blocks as they arrive from AudioCapture.

        Calls ``Analyzer.process()`` (which releases the GIL during numpy FFT)
        into the back buffer, then swaps front↔back under the analysis lock so
        the main thread always reads a consistent, fully-written snapshot.
        Onset events are collected under the same lock and drained by the main
        thread via ``drain_onsets()``.
        """
        last_seq: int = -1
        log.debug('AudioManager: analysis thread running')
        while not self._analysis_stop.is_set():
            # Wait for a new block; releases the GIL for up to timeout_s.
            if not self._capture.wait_for_new_block(timeout_s=0.5):
                continue  # timeout — check stop flag and loop
            if self._analysis_stop.is_set():
                break
            block, new_seq = self._capture.get_block_if_new(last_seq)
            if block is None:
                continue
            last_seq = new_seq
            # Heavy work: numpy FFT releases the GIL → render thread runs freely.
            self._analyzer.process(block, out=self._back_buf)
            onsets = self._analyzer.drain_onsets()
            audio_t = self._analyzer.last_audio_time
            # Atomic publish: swap buffers, accumulate onsets, update timestamp.
            with self._analysis_lock:
                self._front_buf, self._back_buf = self._back_buf, self._front_buf
                self._published_audio_time = audio_t
                if onsets:
                    self._onset_pending.extend(onsets)
        log.debug('AudioManager: analysis thread exited')

    def get_reactivity(self) -> float:
        """Return current global audio reactivity multiplier."""
        return float(self._reactivity)

    def get_profile_name(self) -> str:
        """Return the active audio profile display name."""
        return str(self._profile.name)

    def get_profile_key(self) -> str:
        """Return the active audio profile key."""
        return str(self._profile_key)

    def set_reactivity(self, value: float) -> float:
        """Set current global reactivity, clamped to a safe range."""
        self._reactivity = max(0.1, min(5.0, float(value)))
        return float(self._reactivity)

    def reset_reactivity(self) -> float:
        """Reset current reactivity to the config-defined default."""
        self._reactivity = float(self._reactivity_default)
        return float(self._reactivity)

    def get_source_label(self) -> str:
        """Return a user-facing label for the active audio input source."""
        return self._capture.current_source_label()

    def source_is_output_flags(self) -> list[bool]:
        """Per-source: True for an output being monitored, False for an input."""
        return self._capture.source_is_output_flags()

    def list_sources(self) -> list[str]:
        """Return candidate capture sources for selector UI."""
        return self._capture.source_labels()

    def get_source_index(self) -> int:
        """Return currently selected source index in candidate list."""
        return self._capture.current_source_index()

    def select_source(self, index: int) -> str:
        """Select capture source by candidate index and return active label."""
        return self._capture.select_source(index)

    def cycle_source(self, delta: int) -> str:
        """Cycle to another capture source and return active source label."""
        return self._capture.cycle_source(delta)

    def source_viable_flags(self) -> list[bool]:
        """Return viable-tag flags for each listed audio source."""
        return self._capture.source_viable_flags()

    def toggle_source_viable(self, index: int) -> tuple[bool, str]:
        """Toggle viability tag for a source index; returns (enabled, message)."""
        return self._capture.toggle_source_viable(index)

    def get_raw_input_rms(self) -> float:
        """Return the last raw input RMS measured by the analyzer.

        Useful for HUD diagnostics: distinguishes true silence (value ~ 0)
        from a quiet-but-live source (small but non-zero value).
        """
        return self._analyzer.last_raw_rms

    def get_xrun_count(self) -> int:
        """Return the cumulative capture input-overflow count since stream open.

        A value of 0 means no xruns since the stream was last opened.  Each
        non-zero increment indicates one missed audio period (potential static).
        Surfaces in the TAB HUD for operator diagnostics.
        """
        return int(self._capture.xrun_count)
    
    def get_profile(self) -> AudioProfile:
        """Return the current audio profile."""
        return self._profile

    def get_profile_bpm_range(self) -> tuple[int, int]:
        """Return the preferred BPM range for the active analyzer profile."""
        return self._profile.preferred_bpm_range()

    def get_profile_hud_label(self) -> str:
        """Return a compact user-facing profile label for HUD display."""
        return f'{self._profile.name} ({self._profile.hud_bpm_range_label()})'

    def get_audio_time(self) -> float:
        """Return the audio timestamp of the latest processed block.

        Reads from the lock-protected published value so there is no data race
        with the analysis thread writing ``last_audio_time`` concurrently.
        """
        with self._analysis_lock:
            return float(self._published_audio_time)
    
    def set_profile(self, name: str) -> AudioProfile:
        """Switch to a named audio profile and update analyzer."""
        profile = get_profile(name)
        self._profile_key = name
        self._profile = profile
        # Acquire lock so the analysis thread doesn't process a block mid-switch.
        with self._analysis_lock:
            self._analyzer.set_profile(profile)
        lo, hi = profile.preferred_bpm_range()
        log.info(
            'Audio profile changed to: %s [%d-%d BPM, prior mu=%.0f sigma=%.2f]',
            profile.name,
            lo,
            hi,
            float(profile.bpm_prior_mu),
            float(profile.bpm_prior_sigma),
        )
        return profile
    
    def list_profiles(self) -> list[str]:
        """Return list of available profile names."""
        return list_profiles()

    def get_audio_data(self) -> AudioData:
        """Called every frame from the main loop.

        Copies the latest published analysis snapshot into ``_last_data`` and
        ``_last_data_raw``, then applies the global reactivity multiplier to
        ``_last_data``.  The copy is guarded by ``_analysis_lock`` so we always
        read a fully-written buffer; the lock is released before any arithmetic.
        No FFT or numpy work happens on the main thread.
        """
        if self._started:
            self._capture.maybe_fallback()
        # Copy latest published snapshot under the lock (only held for ~2 KB copy).
        with self._analysis_lock:
            self._copy_audio_into(self._front_buf, self._last_data_raw)
            self._copy_audio_into(self._front_buf, self._last_data)
        # Apply reactivity outside the lock — no shared state involved.
        if self._reactivity != 1.0:
            r = self._reactivity
            self._last_data.bass   = min(1.0, self._last_data.bass   * r)
            self._last_data.mid    = min(1.0, self._last_data.mid    * r)
            self._last_data.treble = min(1.0, self._last_data.treble * r)
            np.multiply(self._last_data.fft, r, out=self._last_data.fft)
            np.clip(self._last_data.fft, 0.0, 1.0, out=self._last_data.fft)
        return self._last_data

    def get_audio_data_raw(self) -> AudioData:
        """Return latest unscaled analyzer snapshot for detection/telemetry."""
        return self._last_data_raw

    def get_recent_pcm_window(self, duration_s: float = 10.0) -> tuple[np.ndarray, int] | None:
        """Return a recent mono PCM window and its sample rate for stream analysis."""

        if not self._capture.active:
            return None
        sample_rate = int(self._capture.sample_rate)
        block_size = max(1, int(self._capture.block_size))
        blocks = max(1, int(np.ceil(max(0.5, float(duration_s)) * sample_rate / block_size)))
        pcm = self._capture.get_history(blocks)
        if pcm.size == 0:
            return None
        return pcm.astype(np.float32, copy=False), sample_rate

    # ------------------------------------------------------------------
    # P1 / P3 — onset stream forwarding
    # ------------------------------------------------------------------

    def drain_onsets(self) -> list[OnsetEvent]:
        """Return and clear all onset events queued in the analyzer.

        Thread-safe: called from the main thread; the analysis thread publishes
        onsets under the same ``_analysis_lock``.
        """
        with self._analysis_lock:
            onsets = list(self._onset_pending)
            self._onset_pending.clear()
        return onsets

    def set_expected_bpm(self, bpm: float, confidence: float) -> None:
        """Forward a BPM estimate to the analyzer to tune its refractory gate.

        Called by the auto-vj director after each BeatTracker update.  Acquires
        ``_analysis_lock`` so the analyzer's refractory-window state is not
        mutated while the analysis thread is mid-process() reading the same
        fields.
        """
        with self._analysis_lock:
            self._analyzer.set_expected_bpm(bpm, confidence)
