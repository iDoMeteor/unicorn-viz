"""
AudioManager — owns AudioCapture + Analyzer, exposes get_audio_data().
Also manages MIDI (stub for now, full impl in Phase 6).
"""
from __future__ import annotations

import logging

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
    def _clone_audio(data: AudioData) -> AudioData:
        clone = AudioData()
        clone.bass = float(data.bass)
        clone.mid = float(data.mid)
        clone.treble = float(data.treble)
        clone.beat = float(data.beat)
        clone.bpm = float(data.bpm)
        clone.bass_flux = float(data.bass_flux)
        clone.mid_flux = float(data.mid_flux)
        clone.fft[:] = data.fft
        clone.waveform[:] = data.waveform
        return clone

    def start(self) -> None:
        log.debug("AudioManager: starting capture")
        self._capture.start()
        log.debug("AudioManager: capture started, analyzer ready")

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

    def get_raw_input_rms(self) -> float:
        """Return the last raw input RMS measured by the analyzer.

        Useful for HUD diagnostics: distinguishes true silence (value ~ 0)
        from a quiet-but-live source (small but non-zero value).
        """
        return self._analyzer.last_raw_rms
    
    def get_profile(self) -> AudioProfile:
        """Return the current audio profile."""
        return self._profile

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
        log.info('Audio profile changed to: %s', profile.name)
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
        raw = self._analyzer.process(block)
        self._last_data_raw = raw
        data = self._clone_audio(raw)
        if self._reactivity != 1.0:
            data.bass   = min(1.0, data.bass   * self._reactivity)
            data.mid    = min(1.0, data.mid    * self._reactivity)
            data.treble = min(1.0, data.treble * self._reactivity)
            if data.fft is not None:
                data.fft = np.clip(data.fft * self._reactivity, 0.0, 1.0)
        self._last_data = data
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
