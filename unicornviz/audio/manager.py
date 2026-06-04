"""
AudioManager — owns AudioCapture + Analyzer, exposes get_audio_data().
Also manages MIDI (stub for now, full impl in Phase 6).
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from unicornviz.effects.base import AudioData
from unicornviz.audio.capture import AudioCapture
from unicornviz.audio.analyzer import Analyzer, OnsetEvent  # noqa: F401 (OnsetEvent re-exported)
from unicornviz.audio.profiles import AudioProfile, get_profile, list_profiles
from unicornviz.config import Config

log = logging.getLogger(__name__)


class AudioManager:
    def __init__(self, cfg: Config) -> None:
        device_hint = cfg.get("audio", "device", default="")
        fft_bands = cfg.get("audio", "fft_bands", default=512)
        buffer_seconds = cfg.get("audio", "buffer_seconds", default=2.0)
        latency = cfg.get("audio", "latency", default="high")
        prefer_default_input = bool(
            cfg.get('audio', 'prefer_default_input', default=True)
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
        
        # Audio profile selection
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
        )
        self._analyzer = Analyzer(
            fft_bands=fft_bands,
            profile=self._profile,
            silence_rms_floor=silence_floor,
            silence_rms_span=silence_span,
        )
        self._last_data = AudioData()
        self._last_data_raw = AudioData()

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
        target.fft[:] = source.fft
        target.waveform[:] = source.waveform

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

    def stop(self) -> None:
        self._capture.stop()

    def get_reactivity(self) -> float:
        """Return current global audio reactivity multiplier."""
        return float(self._reactivity)

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
        """Return analyzer audio-time timestamp of the latest processed block."""
        return float(self._analyzer.last_audio_time)
    
    def get_profile_key(self) -> str:
        """Return the short key/name of the current profile (e.g. 'house', 'trance')."""
        return self._profile_key
    
    def set_profile(self, name: str) -> AudioProfile:
        """Switch to a named audio profile and update analyzer."""
        profile = get_profile(name)
        self._profile_key = name
        self._profile = profile
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
        """Called every frame from the main loop."""
        self._capture.maybe_fallback()
        block = self._capture.get_block()
        if block is not None and len(block) > 0:
            rms = float(np.sqrt(np.mean(block * block)))
            log.debug("Audio frame: rms=%.4f bass=%.3f mid=%.3f treble=%.3f", rms, self._last_data.bass, self._last_data.mid, self._last_data.treble)
        self._analyzer.process(block, out=self._last_data_raw)
        self._copy_audio_into(self._last_data_raw, self._last_data)
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

    # ------------------------------------------------------------------
    # P1 / P3 — onset stream forwarding
    # ------------------------------------------------------------------

    def drain_onsets(self) -> list[OnsetEvent]:
        """Return and clear all onset events queued in the analyzer.

        The BeatTracker in the auto-vj drop-in calls this each frame instead
        of reading ``audio.beat``, so no onset is missed on fast frames and
        none is double-counted on slow ones.
        """
        return self._analyzer.drain_onsets()

    def set_expected_bpm(self, bpm: float, confidence: float) -> None:
        """Forward a BPM estimate to the analyzer to tune its refractory gate.

        Called by the auto-vj director after each BeatTracker update.  When
        confidence is sufficient (>= 0.5) the analyzer will reject onsets
        faster than ~70 % of the estimated beat period.
        """
        self._analyzer.set_expected_bpm(bpm, confidence)
