"""
AudioManager — owns AudioCapture + Analyzer, exposes get_audio_data().
Also manages MIDI (stub for now, full impl in Phase 6).
"""
from __future__ import annotations

import logging

import numpy as np

from unicornviz.effects.base import AudioData
from unicornviz.audio.capture import AudioCapture
from unicornviz.audio.analyzer import Analyzer
from unicornviz.audio.profiles import AudioProfile, get_profile, list_profiles
from unicornviz.config import Config

log = logging.getLogger(__name__)


class AudioManager:
    def __init__(self, cfg: Config) -> None:
        device_hint = cfg.get("audio", "device", default="")
        fft_bands = cfg.get("audio", "fft_bands", default=512)
        buffer_seconds = cfg.get("audio", "buffer_seconds", default=2.0)
        latency = cfg.get("audio", "latency", default="high")
        try_alsa_loopback = cfg.get("audio", "try_alsa_loopback", default=True)
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
            try_alsa_loopback=try_alsa_loopback,
        )
        self._analyzer = Analyzer(fft_bands=fft_bands, profile=self._profile)
        self._last_data = AudioData()

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
    
    def get_profile(self) -> AudioProfile:
        """Return the current audio profile."""
        return self._profile
    
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
        data = self._analyzer.process(block)
        if self._reactivity != 1.0:
            data.bass   = min(1.0, data.bass   * self._reactivity)
            data.mid    = min(1.0, data.mid    * self._reactivity)
            data.treble = min(1.0, data.treble * self._reactivity)
            if data.fft is not None:
                data.fft = np.clip(data.fft * self._reactivity, 0.0, 1.0)
        self._last_data = data
        return self._last_data
