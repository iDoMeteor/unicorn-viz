"""In-house BPM / beat-grid tracker for the Auto VJ controller.

Designed to run entirely within the 16.67 ms frame budget with no external
dependencies beyond the standard library.  No ``librosa``, no ``aubio``.

Usage::

    grid = BeatGridTracker(cfg)
    grid.update(dt, audio)   # call every frame
    if grid.is_downbeat:
        ...  # handle bar boundary
    bpm = grid.bpm
    score = grid.drop_score

P1 extension: pass ``onsets=`` (list of OnsetEvent from Analyzer.drain_onsets)
to use the queued event stream instead of the audio.beat level.  This prevents
onsets from being missed on fast frames or double-counted on slow ones.

H9 extension: pass ``t=`` (audio-time in seconds) so timing is independent of
wall-clock speed.  Defaults to time.monotonic() for live use.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# 2026-08-09: the detector's own semver, independent of both auto_vj.py's
# drop-in-wide __version__ (a release counter for the whole package) and
# ENGINE_VERSION below (which architecture generation is active -- v1/v2/v3,
# a constant per class, stays '2.0.0' for BeatTracker across every tuning
# change). _DETECTOR_VERSION tracks the detector's *tuning state*: bump it
# whenever a detector constant changes in a way that alters live behavior
# (any constant tracked by the "Detector" table in docs/weights-and-
# thresholds.md -- _MIN_PROFILE_PRIOR_SIGMA, _V2_*, the confidence blend
# ratio, comb-filter harmonic weighting, tactus fold-down, lock/release
# confidence thresholds, etc.). Sibling constants: _DIRECTOR_VERSION and
# _RECOMMENDER_VERSION in auto_vj.py. See CLAUDE.md "Subsystem Versioning
# (Auto VJ: Detector / Director / Recommender)" for the full bump discipline.
#
# 2026-08-09: rescheme to 1.0.0-rc.N, same reasoning as _RECOMMENDER_VERSION
# in auto_vj.py -- see docs/planning/
# auto-vj-director-detector-refinement-plan-2026-08-09.md section 8a.
# rc.3: drop_score composition rework (band_blend rebalance, bass_flux_norm
# added, flux_norm rescoped away from bass). rc.4: drop_score bass-gated
# reweight (slope_norm/flux_norm cut, band_blend/bass_flux_norm raised to
# 0.65 combined) -- see the field comment above _drop_score's computation
# and docs/adr/vj-system.md "Drop Score Bass-Gated Reweight". rc.5:
# _V2_PHASE_TOL 0.18 -> 0.12 (0.08 tried and reverted same session --
# broke phase convergence outright), _V2_COHERENCE_WINDOW 32 -> 35, both
# live experiments pending real onset-jitter/coherence data -- see the
# note above _V2_PHASE_TOL's definition. rc.6: same night, _V2_PHASE_TOL
# 0.12 -> 0.14 and the ACF/phase confidence blend 0.4/0.6 -> 0.5/0.5, both
# explicit owner calls for this session specifically, not resolutions of
# the open "is phase over-weighted" question. rc.7: drop_score energy_norm
# <-> band_blend weight swap (0.15/0.30 -> 0.30/0.15), owner call after
# simulating both against two real sessions -- see the field comment above
# _drop_score's computation and docs/adr/vj-system.md. rc.8: band_blend's
# z-score inputs (bass_n/mid_n/treble_n) switched from reading audio.bass/
# mid/treble to audio.bass_det/mid_det/treble_det (new unicornviz.audio.
# analyzer channel, bass gain 6.6 -> 2.0 for the detector specifically,
# mid/treble unchanged) -- fixes bass_n reading pegged near ceiling almost
# always (verified: real cross-director-mode median separation 2.4pp ->
# 9.0pp end-to-end through the z-score). See
# docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md. rc.9: ACF/
# phase confidence blend 0.5/0.5 -> 0.7/0.3, TEMPORARY -- real session data
# showed phase_confidence structurally capped ~0.3-0.4 even during stable,
# locked stretches (real music generates legitimately off-beat onsets a
# correct lock has no business explaining away), dragging the blended
# confidence down for reasons unrelated to lock quality. Stopgap standing
# in for a proper strength/band-weighted phase-coherence rework (agreed,
# not yet built -- planned for the next work session). See the field
# comment above _estimate_tempo_acf()'s confidence blend and
# docs/adr/vj-system.md. rc.10: BeatTrackerV3's prior-freeze
# (set_profile()) gains acquire/release hysteresis
# (_PRIOR_FREEZE_CONFIDENCE=0.55 / _PRIOR_FREEZE_RELEASE_CONFIDENCE=0.28,
# new sticky _prior_frozen state) instead of re-evaluating the freeze
# fresh from instantaneous confidence every call -- closes a real gap
# where a normal mid-track confidence dip (a breakdown, a quiet passage)
# reopened re-priming, letting a recommender-applied profile drag an
# already-correctly-locked BPM. Confirmed live: a real overnight session
# showed this compounding across many track replays, BPM medians that
# should read 125-134 drifting down to 70-95 over ~9 hours. See the
# BeatTrackerV3 class docstring and docs/adr/vj-system.md.
# rc.11: the tempo-hold gate in _estimate_tempo_acf() (the "hold the
# current lock unless confidence is very low" check) now reads acf_conf
# (this frame's raw ACF evidence) instead of the published self._confidence
# blend -- decouples lock stickiness from the temporary 0.7/0.3 phase-
# confidence ratio (rc.9) and from primed_confidence's floor, neither of
# which have anything to do with whether *this frame's* autocorrelation
# evidence justifies overriding the lock. See the field comment above the
# gate and docs/adr/vj-system.md.
# rc.12: BeatTrackerV3.set_profile() supersedes rc.10's confidence-gated
# freeze entirely -- a genre profile is inferred *from* BPM (tempo_fit
# reads it), so any coupling that lets a profile write back into the
# tempo prior lets truth flow backward, no matter how tightly gated.
# Removed the acquire/release hysteresis and _prior_frozen state; the
# prior is now primed only while self._bpm <= 0.0 (no tempo established
# yet), and unconditionally inert afterward -- no confidence check of
# any kind. BeatTracker/v2 deliberately left unchanged as a live A/B
# reference via beat_tracker_shadow_engine. See the BeatTrackerV3 class
# docstring and docs/adr/vj-system.md.
# rc.13: tactus fold-down descent gains a region-consistency guard
# (_tactus_fold_accepted(), _TACTUS_REGION_GUARD_RATIO=0.70) -- a
# candidate must clear tactus_preference_ratio on raw comb-filter score
# AND not be a measurably worse fit for the recently observed beat
# spacing (_analysis_region_consistency) than the lane it would replace.
# First half of the kick-regularity/downbeat-confidence disambiguation
# work (kr/dbc option A); option B (piping kick_regularity itself into
# fold eagerness) is a separate follow-up. See docs/adr/vj-system.md.
# rc.14: kr/dbc option B. BeatTracker.update()/BeatTrackerV3.update() gain
# an optional kick_regularity param (persists across calls when omitted);
# _effective_tactus_ratio() scales the tactus fold-eagerness ratio by it,
# tightening (never loosening) the baseline as kick regularity falls
# toward 0.0 -- sparse/irregular kicks, the documented R&B/hip-hop
# triplet-fold risk territory. New _TACTUS_KICK_REGULARITY_SPREAD=0.30.
# BeatGridTracker (legacy/v1) also gains the param for call-site
# compatibility (accepted, unused -- no tactus logic in that engine).
# Wired from AutoVJController._compute_kick_regularity() in auto_vj.py.
# See docs/adr/vj-system.md.
# Not bumped for the 2026-08-14 kr/dbc observability addition (new
# kick_regularity/effective_tactus_ratio properties + three tactus-guard
# counters) -- pure logging/read-only telemetry, no constant or decision
# logic changed, which CLAUDE.md's versioning discipline explicitly
# exempts ("do not bump for changes that cannot alter the numbers:
# refactors, renames, logging, UI, tests, or docs"). See
# docs/adr/vj-system.md.
# rc.15: strength/band-weighted phase coherence -- the real fix for
# phase_confidence's structural cap, agreed and deferred since rc.9's
# temporary 0.7/0.3 ACF/phase blend ratio ("definitely tomorrow first
# thing"). _absorb_onset() now weights each onset's contribution to
# _phase_confidence by band_weight (bass fraction of its flux, from
# unicornviz.audio.analyzer's new OnsetEvent.band_weight) times a
# saturating function of strength (_V2_PHASE_STRENGTH_SATURATION=2.0),
# instead of counting every onset equally regardless of whether it was a
# kick or a hi-hat tick. New _coherence_hit_weight/_coherence_total_weight
# deques replace the flat _coherence_buf. Confidence-blend ratio (0.7/0.3)
# left unchanged pending evaluation against real session data with this
# rework live -- not reverted automatically. See docs/adr/vj-system.md.
# rc.16: confidence-blend ratio 0.7/0.3 -> 0.8/0.2 ACF/phase, the owner's
# pre-stated fallback if rc.15's strength/band-weighted phase coherence
# alone didn't raise confidence enough. Live validation same day: BPM and
# genre both correct from the first song, confidence still read too low.
# See docs/adr/vj-system.md.
# rc.17: _V2_PHASE_TOL reverted 0.14 -> 0.18 (felt "kinda hot" at 0.14 on
# live material). Confidence blend becomes a three-term
# 0.6*acf + 0.2*phase + 0.2*downbeat_regularity -- new _downbeat_regularity()
# method (region consistency + on-beat density only, renormalized), NOT
# _last_downbeat_confidence, which already reads phase_confidence/
# acf_confidence internally and would have made confidence partly echo its
# own recent history bar over bar. See docs/adr/vj-system.md.
# rc.18: analysis_mode_enabled ripped out entirely -- beat-position
# analysis (downbeat confidence gating, the tempo-jump-guard region-
# consistency cross-check, and a real downbeat_regularity signal instead
# of a flat constant) is now always on, no config key, no way to disable.
# It was an opt-in flag defaulting to False; every install that never
# explicitly set it was silently running degenerate downbeat/jump-guard
# behavior. See docs/adr/vj-system.md.
# rc.19: _V2_PHASE_TOL 0.18 -> back to 0.14 -- real v3/v2-shadow agreement
# regression found on syncopated material, see the field comment above.
# First step of a two-step revert; downbeat_regularity's weight in the
# confidence blend is next if this alone doesn't fix it.
# rc.20: no beat_grid.py constant changed, but the detector's live
# behavior did -- auto_vj.py's AutoVJController._sync_grid_audio_profile()
# (the only production caller of set_profile() with a genre-specific
# profile) was removed entirely, making recommender-to-detector genre
# coupling strictly one-way (detector -> recommender only). set_profile()
# itself is unchanged; only its live wiring is gone. See
# docs/adr/vj-system.md.
# rc.21: confidence blend re-tuned 0.6/0.2/0.2 -> 0.65/0.1/0.25 (ACF/
# phase/downbeat_regularity), plus downbeat_regularity itself gains a
# cached, externally-readable property (previously computed inline and
# discarded) for the first time. Real session data showed phase_
# confidence still capped ~0.32 mean even on locked rows -- same
# structural ceiling the 2026-08-11 investigation found, not resolved by
# the band/strength-weighting rework. Root cause flagged as a separate,
# still-open investigation. See docs/adr/vj-system.md.
# rc.22: the entire BPM-value accept/reject gate stack (10 constants,
# previously bare cfg.get() literals) promoted to named _V2_* module
# constants; 5 retuned per direct owner review after a real carry-over
# incident (BPM frozen across a track change, garbage/k):
# _V2_STARTUP_CONFIDENCE 0.55 -> 0.3, _V2_LARGE_JUMP_CONFIDENCE 0.72 ->
# 0.5, _V2_LOW_BPM_FAST_CONFIDENCE 0.80 -> 0.45, _V2_MAX_BPM_STEP 3.0 ->
# 5.0, _V2_ANALYSIS_REGION_CONFIDENCE_MIN 0.58 -> 0.40. Fixed the
# large-jump gate's region-consistency chicken-and-egg (AND -> OR logic
# -- see _estimate_tempo_acf()'s own comment). New region_consistency/
# last_tactus_fold properties for observability. See docs/adr/vj-system.md.
# rc.23: the tempo-hold lock gate removed entirely -- 20-transition-pair
# sweep showed 4/20 converged with it vs 20/20 without (almost all within
# 5-9s). New _V2_LARGE_JUMP_PERSISTENCE_CYCLES=25 fixes a real "grid-split
# wobble" found immediately after (live: a solid 127.33 BPM lock collapsed
# to 91.37 over ~12s, no track change, traced to material landing in a gap
# in the ACF's discrete lag grid) -- a separate, much longer persistence
# window gating large jumps specifically. See docs/adr/vj-system.md.
# rc.24: _V2_STARTUP_CONFIDENCE 0.3 -> 0.4, after a real session
# (logs/autovj-20260813T175608.jsonl) locked at 0.32 -- barely above the
# old floor -- on a lower-octave-family error that took ~34 minutes to
# self-correct. New long_candidate_spread/long_candidate_median
# properties: the persistence check's own median/spread, previously
# computed and discarded every evaluation, cached for observability. See
# docs/adr/vj-system.md.
# rc.25: sub-lag (parabolic) peak interpolation added, gated OFF by
# default behind acf_peak_interpolation_enabled -- proposed fix for the
# argmax-wandering root cause (consecutive-integer-lag grid resolution,
# coarse at high BPM). Shipped disabled specifically for a sequential
# A/B test: owner's next session runs baseline (A), the one after with
# the flag flipped on (B). New acf_interpolation_delta_bpm property logs
# how much interpolation moved each cycle's reading (0.0 when disabled).
# See docs/adr/vj-system.md.
# rc.26: _V2_LOCK_BAND_PCT 0.16 -> 0.08, after a live session showed a
# single in-band step (19.56 BPM at ~125 BPM) sliding through with zero
# gating and driving a repeated collapse/recover pattern. See
# docs/adr/vj-system.md.
# rc.27: BeatTrackerV3 retired -- its one override (set_profile()'s
# pre-lock-only guard) folded into BeatTracker directly, confirmed safe
# by 100% BPM agreement (v2 shadow vs v3 active) across a full live
# session. Real behavior change for anyone selecting engine="v2"
# specifically (previously only "v3" had the guard); "v3" remains a
# deprecated config alias for "v2" in auto_vj.py's _load_beat_grid_cls().
# See docs/adr/vj-system.md.
# rc.28: _V2_LOCK_BAND_PCT 0.08 -> 0.03, _V2_LOCK_BAND_MIN 10.0 -> 4.0.
# Real measured cycle-to-cycle jitter while locked (p95 ~2.3 BPM) showed
# the rc.26 band still let the top 1-2% noise tail through ungated; also
# fixed an asymmetry where the flat floor gave low-BPM material (this
# project's problem child most of the night) a wider relative allowance
# than high-BPM material despite measurably tighter natural jitter
# there. Owner: "let's do both, now! i'm hardcore like that." See
# docs/adr/vj-system.md.
# rc.29: _V2_STARTUP_CONFIDENCE 0.4 -> 0.45, owner request ("raise start
# up lock conf"). No fresh marginal-case incident this round -- the
# library/h session's own cold start locked at acf_conf=1.00, miles
# above either threshold -- so this is a further conservative step past
# the rc.24 fix (0.3 -> 0.4, after a real 0.32 lock took 34 min to self-
# correct), not a data-driven retune of a newly observed failure. Gates
# ONLY the session's first-ever lock (self._bpm <= 0.0); every
# subsequent re-lock, including at track boundaries, goes through
# _V2_MIN_UPDATE_CONFIDENCE (0.25) instead -- confirmed by reading the
# gate site directly (see the `if self._bpm <= 0.0:` branch below). See
# docs/adr/vj-system.md.
# rc.30: new sparse-evidence update gate -- holds the current lock when
# kick_evidence_smooth (EMA of kick_regularity) falls below
# _V2_MIN_KICK_EVIDENCE, instead of accepting an ACF candidate the
# recent audio doesn't have the rhythmic structure to support. Owner:
# "humming seems to trip the detector up? (steady man track)" --
# confirmed against library/f/h data. Both new constants are first-cut
# pending real engagement data; new kick_evidence_smooth/
# kick_evidence_reject_count properties exist to log and monitor it, per
# owner request, before any retune. See _V2_MIN_KICK_EVIDENCE's own
# comment and docs/adr/vj-system.md.
# rc.31: two logged-only large-jump-persistence-cycles candidates (10,
# 15) alongside the real 25-cycle window, plus their own cleared/reject
# counters -- real comparative data for whether the real value should
# come down. Owner: "i told you that 25 candidates was too many! test
# some more reasonable values for that." Neither candidate gates
# anything. See _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT's own
# comment and docs/adr/vj-system.md.
# rc.32: _V2_STARTUP_CONFIDENCE 0.45 -> 0.6, owner request ("change the
# cold start confidence lock score to .6"). No fresh marginal-case
# incident this round -- same conservative-further-step pattern as the
# rc.29 bump (0.4 -> 0.45), not a data-driven retune of a newly observed
# failure. Still gates ONLY the session's first-ever lock (self._bpm <=
# 0.0); every later re-lock goes through _V2_MIN_UPDATE_CONFIDENCE (0.25)
# instead. See docs/adr/vj-system.md.
# rc.33: round-three close-out batch (owner: "knock out all of round 3
# in one shot"; see docs/planning/auto-vj-round-three-planning-2026-08-14.md
# and docs/adr/vj-system.md's matching entry). In one bump: sub-lag
# interpolation default False -> True (A/B-validated, § 5.2); relative
# persistence spread limits max(flat, pct*median) for the short/long/
# logged windows (§ 6.3); T5 Option A -- candidate deques cleared on
# every accepted large jump (§ 8.3/8.4); accepted large jumps and
# tap-window matches now SNAP instead of crawling through max_bpm_step
# (interaction fix for Option A + audit T3); minimum lock dwell gate
# (8-bar default, in-band cumulative drift beyond 4% of the lock anchor
# escalates into the large-jump gate stack, § 1.2); cold-start
# confidence-blend guard (downbeat_regularity excluded for the first 25
# cycles after cold start, § 6.4); genre-fit-weighted candidate scoring
# behind a confidence gate (§ 4.2, tempo-independent terms only);
# tap-tempo trust window (tap_prime(), § 4.5); ACF unbiased-length
# correction n/(n-lag) (§ 6.8 #5); envelope pulse-strength log
# compression (§ 6.8 #6); signed phase-error distribution logging
# (§ 6.8 #2); energy-slope history time-bounded at 4s instead of 240
# frames (§ 6.8 #10); candidate_lock_disagreement property backing the
# auto_vj-side refractory guard (§ 6.2).
# rc.34: candidate_lock_disagreement's band split out from the jump-gate's
# _V2_LOCK_BAND_PCT/_MIN (0.03/4.0, tightened for a different job) into
# its own _V2_REFRACTORY_GUARD_BAND_PCT/_MIN (0.16/10.0, the pre-
# tightening original values). Real data across four post-round-three
# sessions showed the guard engaging ~9-11 times/sec against the tight
# band -- essentially continuous, not the rare wrong-lock rescue it was
# designed to be. Owner: "let's make the change you recommend to the
# refractory guard." See docs/adr/vj-system.md.
# rc.35 (2026-08-18): trigger/sustain split lands (drop-score redesign
# plan § 4 + the 2026-08-11 audit's F1/F3/F4/F9 corrections, owner-
# green-lit). New impact_novelty (trigger) and drop_sustain (sustain)
# signals computed alongside the legacy composite from the new raw-path
# bass level (AudioData.bass_level_raw) via a percentile-referenced
# two-timescale primitive; band_blend weights reverted 0.7/0.2/0.1 ->
# 0.45/0.30/0.25 in BOTH engines (§ 4c, decided). _V2_MIDTREB_FLUX_
# NORM_C grounded empirically (c=180, 11 tracks / 72.6k replay ticks).
# See the _V2_BASS_LEVEL_* constants block and docs/adr/vj-system.md.
# rc.36 (2026-09-01): _V2_DWELL_BARS 16 -> 32 (owner-consensus accept
# from the 2026-08-31 accelerated tuning experiment; see the constant's
# own comment). _V2_GENRE_EVIDENCE_MAX_BOOST unchanged at 0.1 but now
# bracket-validated (0.0 / 0.2 / 0.5 / 1.0 all measured).
_DETECTOR_VERSION = '1.0.0-rc.40'  # 2026-09-03: v3 phase 4 -- external prime honoured (posterior seed + held prior centre), onset-density channel inert; rc.39 phase 3; rc.38 phase 2; rc.37 phase 1


class BeatGridTracker:
    """Lightweight per-frame beat detector with BPM, energy, and drop scoring.

    All computation is O(N) where N is at most 64 recent beat timestamps.
    Expected per-frame cost < 0.3 ms on any modern CPU.

    Thread-safety: call only from the main render thread.
    """

    # See BeatTracker.ENGINE_VERSION for the semver scheme this mirrors.
    ENGINE_VERSION = '1.0.0'

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self._beat_threshold: float = float(cfg.get('beat_threshold', 0.55) or 0.55)
        self._bpm_min: float = float(cfg.get('bpm_min', 70) or 70)
        self._bpm_max: float = float(cfg.get('bpm_max', 180) or 180)
        # Profile-driven BPM prior. mu/sigma are overridden by set_profile().
        # Sigma is in log2(BPM) units (octave-symmetric). A sigma >= 1.0
        # effectively disables the prior; small values strongly bias toward
        # the genre's canonical tempo.
        self._prior_mu: float = float(cfg.get('prior_mu', 120.0) or 120.0)
        self._prior_sigma: float = max(
            _MIN_PROFILE_PRIOR_SIGMA,
            float(cfg.get('prior_sigma', 0.55) or 0.55),
        )

        # Refractory window — ignore duplicate spikes closer than this.
        self._beat_refractory_s: float = 0.16
        self._last_beat_t: float = -1e9
        self._beat_times: deque[float] = deque(maxlen=64)

        # Bar tracking: count beats mod 4.
        self._bar_beat_count: int = 0
        # Monotonically increasing count of detected beats, used by the
        # training corpus writer to sample on musical time rather than a
        # fixed wall-clock interval.
        self._beat_index: int = -1

        # BPM estimate + confidence.
        self._bpm: float = 0.0
        self._confidence: float = 0.0

        # Phase within current beat interval.
        self._beat_phase: float = 0.0

        # Per-frame flags reset each update.
        self._is_beat: bool = False
        self._is_downbeat: bool = False
        self._bar_phase_outliers: int = 0

        # Energy low-pass state.
        self._energy: float = 0.0
        self._energy_alpha: float = 0.08
        # Ring buffer of (monotonic_t, smoothed_energy) for slope estimation.
        # NOTE: despite the "2s" name, the slope reference below always
        # resolves to the OLDEST sample in this buffer once it has more than
        # 2s of history — i.e. ~4s ago at the buffer's 240-sample capacity,
        # not literally 2s ago.  All preset slope thresholds are tuned
        # against this real ~4s window; do not "fix" the window length.
        self._energy_history: deque[tuple[float, float]] = deque(maxlen=4096)
        # maxlen is a memory backstop only -- the real window is
        # _V2_ENERGY_WINDOW_S seconds, age-pruned at append time
        # (2026-08-17; was maxlen=240 FRAMES, which silently
        # shrank the window on high-refresh displays -- see
        # _V2_ENERGY_WINDOW_S's field comment).
        self._energy_prev_2s: float = 0.0
        self._drop_score: float = 0.0

        # Detector-only adaptive stats for per-band normalization.
        self._band_alpha: float = float(cfg.get('detector_band_alpha', 0.08) or 0.08)
        self._band_mean_bass: float = 0.0
        self._band_mean_mid: float = 0.0
        self._band_mean_treble: float = 0.0
        self._band_var_bass: float = 1e-4
        self._band_var_mid: float = 1e-4
        self._band_var_treble: float = 1e-4

        # Callbacks queued to fire on the next detected downbeat.
        self._pending_callbacks: list = []

    # ------------------------------------------------------------------ #
    # Public update                                                        #
    # ------------------------------------------------------------------ #

    def update(  # noqa: ARG002
        self,
        dt: float,
        audio: Any,
        onsets: Any = None,
        t: float | None = None,
        kick_regularity: float | None = None,
    ) -> None:
        """Update all signals from the current audio frame.

        Must be called once per render frame from the main thread.

        onsets: list of OnsetEvent from Analyzer.drain_onsets(), or None for
                legacy mode (reads audio.beat level instead).
        t:      optional audio-time in seconds for offline/harness use.
                Defaults to time.monotonic() when None.
        kick_regularity: accepted for call-site compatibility with
                BeatTracker.update() -- unused here, this legacy engine
                has no tactus fold-down logic.
        """
        now: float = t if t is not None else time.monotonic()
        bass = float(getattr(audio, 'bass', 0.0) or 0.0)
        mid = float(getattr(audio, 'mid', 0.0) or 0.0)
        treble = float(getattr(audio, 'treble', 0.0) or 0.0)
        raw_energy = bass + mid + treble

        # Exponential moving average energy.
        alpha = self._energy_alpha
        self._energy = self._energy * (1.0 - alpha) + raw_energy * alpha
        self._energy_history.append((now, self._energy))
        while (self._energy_history
                and (now - self._energy_history[0][0]) > _V2_ENERGY_WINDOW_S):
            self._energy_history.popleft()

        # Slope reference: oldest sample in the history buffer, once it is at
        # least 2s old (see the buffer's field comment for why this is
        # actually a ~4s window in steady state, not 2s).  Entries append in
        # increasing-time order, so the oldest (index 0) always has the
        # largest `now - t` — equivalent to the O(n) linear scan this
        # replaces, since if any entry qualifies the oldest one does too,
        # and if the oldest doesn't qualify none do.
        energy_2s_ago = self._energy
        if self._energy_history and (now - self._energy_history[0][0]) >= 2.0:
            energy_2s_ago = self._energy_history[0][1]
        self._energy_prev_2s = energy_2s_ago
        energy_slope = self._energy - self._energy_prev_2s

        # Per-band adaptive normalization for detector features only.
        # Effects still receive the raw audio channels.
        #
        # 2026-08-11: reads audio.bass_det/mid_det/treble_det (a separate
        # _shape() gain tuned for dynamic range, not the effects-facing
        # bass/mid/treble above) rather than bass/mid/treble themselves --
        # verified against real session data that bass's effects gain (6.6)
        # left this z-score's input pegged near ceiling almost always
        # (median 0.97-0.98 across every director mode). raw_energy above
        # is deliberately left reading the original bass/mid/treble --
        # energy_norm was checked separately and found already well-
        # calibrated, this fix is scoped to band_blend's inputs only. See
        # docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md.
        # `is None` (not `or`) -- bass_det legitimately reads 0.0 during real
        # silence, and `x or fallback` would wrongly substitute the higher-
        # gain bass/mid/treble for that valid zero.
        _bass_det = getattr(audio, 'bass_det', None)
        _mid_det = getattr(audio, 'mid_det', None)
        _treble_det = getattr(audio, 'treble_det', None)
        bass_det = float(_bass_det) if _bass_det is not None else bass
        mid_det = float(_mid_det) if _mid_det is not None else mid
        treble_det = float(_treble_det) if _treble_det is not None else treble
        a = min(0.35, max(0.005, self._band_alpha))

        def _norm(x: float, mean: float, var: float) -> tuple[float, float, float]:
            mean = mean + a * (x - mean)
            d = x - mean
            var = max(1e-6, var + a * (d * d - var))
            z = (x - mean) / ((var ** 0.5) + 1e-6)
            # Map z-score to [0, 1] with a gentle S-curve.
            v = 0.5 + 0.5 * (z / (1.0 + abs(z)))
            return max(0.0, min(1.0, v)), mean, var

        bass_n, self._band_mean_bass, self._band_var_bass = _norm(
            bass_det, self._band_mean_bass, self._band_var_bass
        )
        mid_n, self._band_mean_mid, self._band_var_mid = _norm(
            mid_det, self._band_mean_mid, self._band_var_mid
        )
        treble_n, self._band_mean_treble, self._band_var_treble = _norm(
            treble_det, self._band_mean_treble, self._band_var_treble
        )

        # Composite drop score uses compressed/normalized terms to avoid
        # saturating at 1.0 for long periods on loud material.
        # 2026-08-09: treble used to also get a standalone term (0.14) on top
        # of its share inside band_blend (0.25 x 0.18 = 0.045) -- an
        # undocumented double-count with no stated rationale, found during
        # the director scene-detection audit. Removed; the remaining three
        # terms' weights are renormalized proportionally (divided by their
        # old sum, 0.86) so they still sum to 1.0 rather than picking one
        # term to arbitrarily inherit the freed weight.
        energy_norm = self._energy / (self._energy + 1.0)
        slope_pos = max(0.0, energy_slope)
        slope_norm = slope_pos / (slope_pos + 0.12)
        # 2026-08-09: band_blend rebalanced toward bass (0.45/0.30/0.25 ->
        # 0.7/0.2/0.1) -- a drop should read primarily off the bass band, not
        # a roughly-even tonal blend. Starting point, not final; see
        # docs/planning/auto-vj-director-detector-refinement-plan-2026-08-09.md
        # section 4a. Mirrors the same change in BeatTracker.update() below.
        # 2026-08-18: reverted to 0.45/0.30/0.25 alongside BeatTracker's
        # revert (drop-score redesign plan § 4c) -- see the v2 site's
        # comment for the reasoning; both engines keep the same blend.
        band_blend = min(1.0, max(0.0, bass_n * 0.45 + mid_n * 0.30 + treble_n * 0.25))
        self._drop_score = min(1.0, max(0.0,
            energy_norm * 0.302
            + slope_norm * 0.488
            + band_blend * 0.210
        ))

        # Beat detection.
        self._is_beat = False
        self._is_downbeat = False

        if onsets is not None:
            # P1: consume the structured onset event stream.
            for ev in onsets:
                self._ingest_onset(float(ev.t), float(getattr(ev, 'strength', 1.0)))
        else:
            # Legacy fallback: derive a synthetic event from audio.beat level.
            beat_val = float(getattr(audio, 'beat', 0.0) or 0.0)
            if (beat_val >= self._beat_threshold
                    and (now - self._last_beat_t) >= self._beat_refractory_s):
                self._ingest_onset(now, 1.0)

        # Interpolate beat phase between detected beats.
        if self._bpm > 0.0:
            beat_interval = 60.0 / self._bpm
            elapsed = max(0.0, now - self._last_beat_t)
            self._beat_phase = min(1.0, elapsed / max(1e-6, beat_interval))
        else:
            self._beat_phase = 0.0

    # ------------------------------------------------------------------ #
    # P1 — onset ingestion (extracted from update for reuse)              #
    # ------------------------------------------------------------------ #

    def _ingest_onset(self, t: float, strength: float) -> None:  # noqa: ARG002
        """Process a single onset at audio-time t with given strength.

        Applies the refractory gate, updates bar tracking, and re-estimates
        BPM.  Safe to call multiple times per update when several onsets
        arrived in one audio block.
        """
        if (t - self._last_beat_t) < self._beat_refractory_s:
            return

        prev_t = self._last_beat_t
        ioi = t - prev_t if prev_t > 0 else 0.0
        self._last_beat_t = t
        self._beat_times.append(t)
        self._is_beat = True
        self._beat_index += 1

        count_for_bar = True
        if self._bpm > 0.0 and self._confidence >= 0.55 and ioi > 1e-6:
            expected = 60.0 / max(1e-6, self._bpm)
            dev = abs(ioi - expected) / max(1e-6, expected)
            # Outlier beats can desync the 4-beat bar counter; avoid blindly
            # advancing bar phase on heavily off-grid onsets.
            if dev > 0.35:
                count_for_bar = False
                self._bar_phase_outliers += 1

        if count_for_bar:
            self._bar_beat_count += 1

        if self._bar_beat_count >= 4:
            self._bar_beat_count = 0
            self._is_downbeat = True
            # Drain scheduled callbacks.
            callbacks = self._pending_callbacks[:]
            self._pending_callbacks.clear()
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    pass

        self._estimate_bpm()

    # ------------------------------------------------------------------ #
    # BPM estimation                                                       #
    # ------------------------------------------------------------------ #

    def _estimate_bpm(self) -> None:
        """Re-estimate BPM from recent inter-onset intervals."""
        if len(self._beat_times) < 4:
            return

        iois: list[float] = []
        prev_t: float | None = None
        for t in self._beat_times:
            if prev_t is not None:
                ioi = t - prev_t
                if ioi > 1e-6:
                    bpm = 60.0 / ioi
                    if self._bpm_min <= bpm <= self._bpm_max:
                        iois.append(ioi)
            prev_t = t

        if len(iois) < 3:
            self._confidence = 0.0
            return

        iois.sort()
        med = iois[len(iois) // 2]
        raw_bpm = 60.0 / max(1e-6, med)

        # Harmonic candidate set catches common octave/triplet errors.
        factors = (0.5, 2.0 / 3.0, 0.75, 1.0, 4.0 / 3.0, 1.5, 2.0)
        candidates = [raw_bpm * f for f in factors]
        candidates = [b for b in candidates if self._bpm_min <= b <= self._bpm_max]
        if not candidates:
            return

        def _score(bpm_candidate: float) -> tuple[float, float]:
            expected = 60.0 / max(1e-6, bpm_candidate)
            # Compare observed IOIs to beat-aligned families.
            # m=1.0 is strongest; 0.5/2.0 allow half/double-time capture.
            families = ((1.0, 1.00), (0.5, 0.82), (2.0, 0.82), (1.5, 0.72), (2.5, 0.66))
            score = 0.0
            for ioi in iois:
                best = 0.0
                for mult, weight in families:
                    target = expected * mult
                    err = abs(ioi - target) / max(1e-6, target)
                    if err < 0.20:
                        hit = (1.0 - err / 0.20) * weight
                        if hit > best:
                            best = hit
                score += best
            conf = min(1.0, score / max(1.0, len(iois)))
            return score, conf

        # Prefer the highest-score candidate; bias ties toward prior BPM
        # for temporal continuity. Apply a log2-symmetric prior centred on
        # the profile's canonical tempo so candidates near genre-typical
        # tempos are preferred over equally-fitting octave alternatives.
        import math
        log_mu = math.log2(max(1.0, self._prior_mu))
        inv_sigma2 = 1.0 / max(1e-6, self._prior_sigma * self._prior_sigma)

        def _prior_weight(bpm_candidate: float) -> float:
            d = math.log2(max(1.0, bpm_candidate)) - log_mu
            return math.exp(-0.5 * d * d * inv_sigma2)

        best_bpm = candidates[0]
        best_score, best_conf = _score(best_bpm)
        best_weighted = best_score * _prior_weight(best_bpm)
        for bpm_candidate in candidates[1:]:
            s, c = _score(bpm_candidate)
            weighted = s * _prior_weight(bpm_candidate)
            if weighted > best_weighted + 1e-6:
                best_bpm, best_score, best_conf, best_weighted = bpm_candidate, s, c, weighted
                continue
            if abs(weighted - best_weighted) <= 1e-6 and self._bpm > 0.0:
                if abs(bpm_candidate - self._bpm) < abs(best_bpm - self._bpm):
                    best_bpm, best_score, best_conf, best_weighted = bpm_candidate, s, c, weighted

        # If the best candidate is in a high-BPM lane but confidence is only
        # moderate, prefer slower harmonic folds when they are nearly as good.
        if best_bpm > 145.0 and best_conf < 0.78:
            fallback_folds = [best_bpm * (2.0 / 3.0), best_bpm * 0.75, best_bpm * 0.5]
            fallback_folds = [b for b in fallback_folds if self._bpm_min <= b <= self._bpm_max]
            for fb in fallback_folds:
                s_fb, c_fb = _score(fb)
                # A fold that is close in score/confidence is likely a better
                # musical pulse than a locked fast subdivision.
                if c_fb >= best_conf - 0.08 and s_fb >= best_score * 0.88:
                    best_bpm, best_score, best_conf = fb, s_fb, c_fb
                    break

        self._confidence = best_conf

        if self._confidence >= 0.35:
            candidate = best_bpm
            if self._bpm <= 0.0:
                self._bpm = candidate
            else:
                # Continuity guard: damp implausible frame-to-frame BPM jumps.
                max_step = 1.0 + self._confidence * 1.8
                delta = candidate - self._bpm
                if delta > max_step:
                    candidate = self._bpm + max_step
                elif delta < -max_step:
                    candidate = self._bpm - max_step

                alpha = min(0.40, max(0.10, 0.08 + self._confidence * 0.32))
                self._bpm = self._bpm * (1.0 - alpha) + candidate * alpha

    # ------------------------------------------------------------------ #
    # Profile integration                                                  #
    # ------------------------------------------------------------------ #

    def set_profile(self, profile: object) -> None:
        """Apply a genre profile's BPM prior to bias candidate scoring.

        Called from `AudioManager.set_profile()` so beat detection knows
        the genre's canonical tempo. Safe to call multiple times.

        Deliberately does NOT narrow ``_bpm_min``/``_bpm_max``: a genre
        profile is soft evidence (biases the log2-Gaussian prior below),
        not ground truth. Hard-clamping the candidate search range here
        created a self-confirming loop -- a wrong profile narrowed the
        search, the detected BPM then had to fall inside that narrowed
        range, which "confirmed" the wrong profile. See P0-A in
        docs/audits/2026-08-04-bpm-detector-audit.md and
        docs/adr/vj-system.md.
        """
        if profile is None:
            return
        mu = float(getattr(profile, 'bpm_prior_mu', self._prior_mu) or self._prior_mu)
        sigma = max(
            _MIN_PROFILE_PRIOR_SIGMA,
            float(getattr(profile, 'bpm_prior_sigma', self._prior_sigma) or self._prior_sigma),
        )
        self._prior_mu = mu
        self._prior_sigma = sigma

    def prime_tempo(self, bpm: float, *, confidence: float = 0.9) -> None:
        """Prime the tempo directly from an external ground-truth BPM.

        Used when a fresh reading is available on the shared BPM bus (e.g.
        the DJ mixer's own per-track analysis, via ``vj_api.get_bpm()``) --
        that source's detection is authoritative when present, so this
        short-circuits the median-IOI estimator rather than competing with
        it. Confidence is only ever raised, never lowered, so a stronger
        existing lock isn't weakened by a borderline external reading. See
        P0-B in docs/audits/2026-08-04-bpm-detector-audit.md.
        """
        bpm = float(bpm)
        if bpm <= 0.0:
            return
        self._bpm = bpm
        self._confidence = max(self._confidence, float(confidence))

    # ------------------------------------------------------------------ #
    # Read-only properties                                                 #
    # ------------------------------------------------------------------ #

    @property
    def bpm(self) -> float:
        """Current BPM estimate (0.0 if not yet locked)."""
        return self._bpm

    @property
    def confidence(self) -> float:
        """BPM confidence 0..1 (fraction of recent IOIs near median)."""
        return self._confidence

    @property
    def beat_phase(self) -> float:
        """Phase within the current beat interval, 0..1."""
        return self._beat_phase

    @property
    def is_beat(self) -> bool:
        """True for exactly one frame per detected beat."""
        return self._is_beat

    @property
    def is_downbeat(self) -> bool:
        """True for one frame per 4-beat bar boundary."""
        return self._is_downbeat

    @property
    def energy(self) -> float:
        """Low-pass smoothed sum of bass+mid+treble."""
        return self._energy

    @property
    def energy_slope(self) -> float:
        """Energy delta over ~2 s window (positive = rising)."""
        return self._energy - self._energy_prev_2s

    @property
    def drop_score(self) -> float:
        """Composite drop-likelihood signal 0..1."""
        return self._drop_score

    @property
    def beat_index(self) -> int:
        """Monotonically increasing count of detected beats (-1 before the first)."""
        return self._beat_index

    def schedule_for_next_downbeat(self, callback: Any) -> None:
        """Queue a callable to fire on the next detected bar downbeat."""
        self._pending_callbacks.append(callback)

    def clear_pending(self) -> None:
        """Discard all queued downbeat callbacks."""
        self._pending_callbacks.clear()


# ===========================================================================
# BeatTracker v2 — ACF tempo estimator + phase-locked oscillator
# ===========================================================================
#
# Replaces BeatGridTracker's IOI-median estimator with:
#   P4: Autocorrelation of a 100 Hz onset envelope + perceptual tempo prior
#       (Gaussian centred at 120 BPM, σ=28) → much more robust on dense
#       electronic material.  Octave-down preference resolves subdivision
#       ambiguity.
#
#   P5: Phase-locked oscillator that advances at bpm/60 Hz and snaps to
#       onsets only when they land within ±18% of the predicted beat.
#       Sub-beat onsets are silently ignored — they cannot desync the grid.
#       Confidence = phase coherence (fraction of onsets that hit the window).
#
# Public interface is identical to BeatGridTracker so it is a drop-in swap.
# Select with:  beat_tracker_engine = "v2"  in the [auto_vj] config block.

# Internal envelope parameters
_V2_ENV_RATE = 100.0          # Hz — same as Analyzer._ENV_RATE
_V2_ENV_WINDOW_S = 8.0        # seconds of history for ACF
_V2_ENV_LEN = int(_V2_ENV_RATE * _V2_ENV_WINDOW_S)   # 800 samples

# Tempo estimation
_V2_BPM_MIN = 60.0
_V2_BPM_MAX = 200.0
_V2_PRIOR_MU = 120.0          # perceptual prior centre (log2-tempo)
_V2_PRIOR_SIGMA = 0.55        # perceptual prior width in log2(BPM) units
_V2_COMB_HARMONICS = 4        # number of harmonics in aubio-style comb filter
_MIN_PROFILE_PRIOR_SIGMA = 0.45  # keep profile prior from dominating evidence

# 2026-08-07: relative BPM tolerance for the ACF confidence rival check --
# see the comment above `acf_peak_ratio` in _estimate_tempo_acf(). A tight
# four-on-the-floor track (mechanically regular kick) naturally produces
# near-equal comb-filter scores at the true tempo AND at its harmonics/
# subharmonics (2x, 3x, 4x, 1/2x, ...), because the comb filter itself sums
# correlation at those lags. That is confirmation of a single clean pulse,
# not competing evidence, so a rival lag within this tolerance of an
# integer ratio of the winning lag is excluded when finding the "genuine"
# rival used to compute confidence.
_V2_HARMONIC_CONF_TOL = 0.04

# Phase oscillator
# 2026-08-10: 0.18 -> 0.12, a live experiment, not a validated fix -- owner
# suspected ±18% (±90ms at 120 BPM, wider still at slower tempos) was
# loose enough to count genuinely off-grid onsets (swing/human timing
# variance, especially at rap_rnb/hip-hop tempos) as "on-beat," inflating
# phase_confidence past what real lock quality supports. No onset-jitter
# ground-truth data existed to pick a precise number. First tried 0.08 --
# reverted after direct verification: a mathematically perfect, zero-jitter
# synthetic click track never registered a single phase hit at that
# tolerance (phase_confidence stuck at 0.0 for 120+ simulated seconds),
# because the phase oscillator advances at the tracker's *estimated* BPM,
# which has its own small residual error versus true tempo -- 0.08 was
# tight enough that this residual alone kept phase outside tolerance
# indefinitely, not just filtering genuinely off-grid content as intended.
# 0.12 converges reliably (verified same way) but noticeably slower than
# 0.18 did -- full convergence took ~120s in one tested scenario (124 BPM)
# versus the old ~65s baseline. Owner moved to 0.14 the same night ("sounds
# pretty tight against your test") -- still well below the original 0.18,
# with more convergence headroom than 0.12. Watch BPM confidence (HUD
# "BPM: xxx (0.xx)", now backed by acf_confidence/phase_confidence logged
# separately in the corpus -- see _detector_snapshot()) and lock churn/
# profile-switch frequency for the most obvious impact. See
# docs/adr/vj-system.md "Drop Score Bass-Gated Reweight" § coherence-window
# follow-up and docs/planning/auto-vj-coherence-window-plan-2026-08-10.md.
# Jason says do NOT change this, it's super dialed. -- 2026-08-14
_V2_PHASE_TOL = 0.14          # ±14% of beat period to count as on-beat
# 2026-08-14: 0.14 -> 0.18 -> back to 0.14. Real regression found comparing
# v3/v2-shadow agreement across two same-session-shape runs (favorites/i,
# pre-change vs. a live session right after 0.18 + the three-term
# confidence blend landed): 3 of 5 tracks went from 84-100% v3/v2
# agreement to 0-12%, with v3's own BPM reading meaningfully higher on
# the affected (syncopated/complex-rhythm) tracks -- e.g. one track read
# 116 before, 136 after, not a clean octave error. The only behaviorally-
# relevant change between those two runs was this commit (phase_tol +
# the blend), so reverting phase_tol first, in isolation, to see if that
# alone explains it before touching downbeat_regularity too. See
# docs/adr/vj-system.md.
_V2_PHASE_NUDGE = 0.25        # fraction of error to correct per beat

# Re-estimation interval: run ACF every N frames to stay within budget
_V2_ACF_INTERVAL = 8          # ~8 frames @ 60fps ≈ 7.5 Hz tempo updates

# Phase coherence window: rolling average over last N onsets
# 2026-08-10: 32 -> 35. The LLM's favorites/b tuning recommendation
# (32 -> 40) was rejected as reasoning about the wrong axis -- see
# docs/adr/vj-system.md and training-kit-01's prompt fix -- but the owner
# chose to still try a partial move toward it as its own experiment,
# independent of that flawed rationale ("kinda split the difference").
_V2_COHERENCE_WINDOW = 35

# 2026-08-14: strength/band-weighted phase coherence. Each onset's
# contribution to _phase_confidence is weighted by band_weight (bass
# fraction of its flux, 0..1 -- see OnsetEvent) times a saturating
# function of its strength (z-score above the onset-detection threshold),
# rather than counting every onset equally regardless of whether it was a
# strong kick or a barely-above-threshold hi-hat tick. Real session data
# this week showed phase_confidence structurally capped ~0.3-0.4 even
# during genuinely stable, locked stretches -- real music generates
# plenty of legitimately off-beat onsets (hi-hats, syncopation, fills)
# that a correct lock has no business explaining away; this closes that
# gap at the source instead of the temporary 0.7/0.3 ACF/phase blend
# ratio compensating for it downstream. First-cut value, not yet
# validated against real session data -- an onset needs to be roughly
# "one MAD unit above threshold" (strength >= 2.0) to reach full weight.
# See docs/adr/vj-system.md.
_V2_PHASE_STRENGTH_SATURATION = 2.0

# Short-horizon beat-map analysis (always on since 2026-08-14 -- see the
# WARNING in BeatTracker.__init__'s analysis-mode field comment)
_V2_ANALYSIS_MAP_BEATS = 64
_V2_ANALYSIS_REGION_MIN_BEATS = 8
_V2_ANALYSIS_REGION_TOL = 0.20
_V2_ANALYSIS_REGION_CONFIDENCE_MIN = 0.58
# 2026-07-06: lowered from 0.55 to 0.42 as the training-start default.
# 2026-07-08: lowered twice more, 0.42 -> 0.35 -> 0.30.  Production data
# (~22k post-fix decision-log ticks, 2026-07-06 through 2026-07-08): median
# downbeat_confidence sits at 0.34-0.49 across most profiles, below 0.42 for
# a majority of ticks in several genres (see docs/audits/2026-07-06-vj-
# training-systems-audit.md and the ADR).  NOTE: not hot-reloaded -- this
# only takes effect on the next AutoVJController construction (app restart).
_V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN = 0.30
# 2026-08-14, later still (next session): 0.58 -> 0.40. Never tuned or
# logged before tonight -- promoted from an inline cfg.get() default to a
# named constant alongside the rest of the BPM-value accept/reject gate
# stack below, all discovered the same night to be invisible to LLM
# tuning entirely (see _DETECTOR_CONSTANT_DEFAULTS in training-kit-01's
# package_training_set.py). Owner: "probably should lower that a bit"
# after the Juri -> Music Sounds Better With You carry-over incident --
# this is the gate that makes the carry-over structurally hard to escape
# (a brand-new tempo can't have "recent beat positions consistent with
# it" until it's already been accepted, a real chicken-and-egg -- see the
# OR-logic fix in _estimate_tempo_acf() below and docs/adr/vj-system.md).
# First-cut value pending real session data with this stack now logged.
_V2_ANALYSIS_REGION_CONFIDENCE_MIN = 0.40

# BPM-value accept/reject gate stack (all promoted from inline cfg.get()
# defaults to named constants 2026-08-14, later still -- see the region-
# confidence-min note above for why). Every one of these decides whether a
# freshly-computed ACF candidate becomes the published self._bpm at all,
# entirely independent of the self._confidence blend above (see
# docs/adr/vj-system.md "BPM Value Determination Is Not Confidence" for
# the full account of why tuning that blend never touched any of this).
_V2_MIN_UPDATE_CONFIDENCE = 0.25   # already-locked: floor to accept ANY update
# 2026-08-14, later still: 0.55 -> 0.3. Owner: "0.35 has typically
# represented a pretty solid lock and right off the jump we'd probably
# rather have any reasonable bpm jump in and it can self correct as it
# goes -- 0.55 is a very high bar." Cold-start floor only (self._bpm <=
# 0.0); does not affect the already-locked update floor above.
# 2026-08-14, round three: 0.3 -> 0.4. Real session data
# (logs/autovj-20260813T175608.jsonl) showed 0.3 was permissive enough to
# accept a cold-start candidate at acf_conf=0.32 -- barely above the old
# floor -- that turned out to be a lower-octave-family error; the session
# stayed on that wrong value for roughly 34 minutes before a later track
# change happened to clear the large-jump persistence gate on its own.
# Raised to the midpoint between the pre-2026-08-14 value (0.55) and that
# incident's floor (0.3), not reverted all the way -- the original reason
# for lowering it (self-correction should still be cheap early) still
# holds, this just asks for slightly stronger first evidence before
# locking at all. See docs/adr/vj-system.md.
_V2_STARTUP_CONFIDENCE = 0.6

# 2026-08-14, round three, the morning after (part two): sparse-evidence
# update gate. Owner-observed live: "humming seems to trip the detector
# up? (steady man track)" -- confirmed against library/h/f data (see
# docs/adr/vj-system.md's "startup confidence raised" entry). During the
# hunting windows, kick_regularity repeatedly collapsed toward 0.0 while
# bass/energy stayed high -- a low-transient passage the ACF still finds
# *some* peak for and happily reports as a confident new candidate, even
# though there's insufficient rhythmic evidence to justify moving off an
# established lock. This is a DIFFERENT lever from acf_conf/_min_update_
# confidence above: acf_conf measures how sharply the ACF's own window
# picked one peak over rivals, which can look locally fine on a noisy
# peak from thin material; kick_regularity measures whether the recent
# audio actually *has* periodic percussive structure to trust at all.
# Also distinct from _effective_tactus_ratio()'s existing kick_regularity
# use (that tightens which harmonic candidate wins during a fold
# decision; this suppresses accepting any update at all).
#
# Gates UPDATES only (self._bpm > 0.0), never the initial cold-start
# lock -- kick_regularity legitimately starts at/persists at 0.0 before
# enough beat history exists (see _effective_tactus_ratio()'s own
# docstring), so gating cold-start on it could block ever acquiring a
# first lock at all.
#
# Raw self._kick_regularity is too noisy cycle-to-cycle to gate on
# directly -- it swung 0.0 to 0.8+ within a few cycles even during
# Steady Man's initially stable, correctly-locked opening stretch (see
# library/h row-level data). Smoothed via _kick_evidence_smooth (EMA,
# alpha below) instead, computed unconditionally every cycle so it
# reflects a genuine multi-second trend rather than single-frame noise.
#
# Both constants below are first-cut, deliberately conservative-but-
# permissive values pending real data -- owner: "let's do that, and be
# sure to log and monitor the relevant details so we can tune it if
# needed." New kick_evidence_smooth/kick_evidence_reject_count
# properties exist specifically for that; do not retune either constant
# without a live session's worth of engagement data to look at first.
_V2_KICK_EVIDENCE_ALPHA = 0.15   # EMA smoothing factor, ~1s time constant at the ~7.5 Hz ACF cycle rate
_V2_MIN_KICK_EVIDENCE = 0.12     # already-locked: floor on the smoothed evidence to accept ANY update
# 2026-08-14, round three, live-session follow-up: 0.16 -> 0.08. Owner,
# watching a live session where a single in-band step (124.73 -> 105.17,
# 19.56 BPM, cleared under the old 16% because 124.73*0.16=19.96) drove
# a chunk of a repeated correct-collapse-recover-collapse pattern:
# "that's pretty huge for a one-song swing, or even a two song swing...
# a dj *might* do that, but if they did their transition would probably
# be mighty and swift and all sorts of levers would pop." Roughly
# converges with the flat _V2_LOCK_BAND_MIN=10.0 floor around 125 BPM
# instead of nearly doubling it -- more of what used to slip through
# in-band (ungated) now has to clear the large-jump gate stack
# (persistence check, confidence floor) instead. See
# docs/adr/vj-system.md and docs/planning/auto-vj-round-three-planning-
# 2026-08-14.md § 10.
# 2026-08-14, round three, same night, next session: 0.08 -> 0.03 and
# _V2_LOCK_BAND_MIN 10.0 -> 4.0. Real cycle-to-cycle jitter measured
# directly from a healthy locked session (1440 samples): median 0.04
# BPM, p90 1.04, p95 2.3, p99 11.0 -- the old ~10 BPM band (8% mostly
# floor-dominated below ~125 BPM) was letting through moves in roughly
# the top 1-2% of the natural noise distribution completely ungated,
# exactly the tail where real problems live (the 124.73->105.17 collapse
# this same night was 19.56 BPM). This band's actual job is "don't be
# paranoid about ordinary noise" -- genuine large transitions don't need
# it, they already clear the large-jump gate stack cleanly (verified
# live the same night: a ~25+ BPM real track change into a slow track
# "handled smooth as butter"). New values sit comfortably above p95 at
# both ends without covering the tail that should go through scrutiny.
# Also fixes an asymmetry: splitting the same jitter data by tempo showed
# LOW-BPM material (chillstep/downtempo, this project's problem child
# most of the night) has TIGHTER natural jitter than high-BPM (p95 1.60
# vs. 2.26 -- consistent with the ACF lag grid being finer at low BPM,
# see the interpolation fix's own root-cause comment), yet the old flat
# 10.0 floor gave it a *wider* relative allowance (14.3% at 70 BPM vs.
# 8% once the pct term took over above ~125). Owner: "let's do both,
# now! i'm hardcore like that." See docs/adr/vj-system.md and
# docs/planning/auto-vj-round-three-planning-2026-08-14.md § 10.
_V2_LOCK_BAND_PCT = 0.03           # +-3%/min 4 BPM = "normal" range, no jump gates below apply
_V2_LOCK_BAND_MIN = 4.0

# 2026-08-17, later still: candidate_lock_disagreement's own band, split
# out from _V2_LOCK_BAND_PCT/_MIN above. Real-session data (four post-
# round-three sessions: training-house-01/d+e, favorites/m+n) showed the
# refractory guard (auto_vj.py, suspends the BPM-fed analyzer refractory
# while this property is true) engaging ~9-11 times/sec, essentially
# continuously rather than as the rare wrong-lock rescue it was designed
# to be -- because it was reusing the jump-gate's band, which rc.26/rc.28
# tightened 0.16 -> 0.08 -> 0.03 for a DIFFERENT job (catching individual
# in-band erosion steps). A band that tight makes a noisy real ACF
# candidate fall outside it often even when the lock itself is fine, so
# the guard fires on routine noise, not just genuine disagreement. Reset
# to the pre-tightening original values -- wide enough that only a real,
# substantial candidate/lock split trips it. Deliberately NOT reusing
# _V2_LOCK_BAND_PCT/_MIN so future retuning of the jump-gate band (its own
# still-active concern) doesn't silently drag this guard's threshold along
# with it. Owner: "let's make the change you recommend to the refractory
# guard." See docs/adr/vj-system.md.
_V2_REFRACTORY_GUARD_BAND_PCT = 0.16
_V2_REFRACTORY_GUARD_BAND_MIN = 10.0

# 2026-08-14, round three: two candidate replacements for the lock-band
# shape above, LOGGED ONLY -- neither drives any gating decision, the
# actual max(_V2_LOCK_BAND_MIN, bpm*_V2_LOCK_BAND_PCT) formula above is
# unchanged and still the only one used to accept/reject a jump. Owner's
# closing question the same night: "we should also consider... having
# them scale in a proportional way with bpm range that we control rather
# than letting them swing in just a random what other math happens to be
# doing way" -- the current shape's crossover point is emergent (wherever
# the flat floor and the pct term happen to intersect), not designed.
# Two real alternatives, computed and logged side by side for one full
# session per owner's own framing ("code them both up but just log both
# for one session with everything else as is, and see what we think of
# each") before either is considered for promotion to the live gate:
#
# ANALYTICAL: k * bpm^2 / (60 * _V2_ENV_RATE) is exactly k lag-grid steps
# at that tempo (see d(BPM)/d(lag) = -bpm^2/(60*_V2_ENV_RATE), the same
# identity behind the sub-lag interpolation fix's own root-cause
# reasoning). k=1.0 needs no fitting at all -- it's "one full grid step,"
# a natural, self-justifying unit rather than a chosen number.
_V2_LOCK_BAND_CANDIDATE_ANALYTICAL_K = 1.0
#
# EMPIRICAL: a flat constant from tonight's own measured cycle-to-cycle
# jitter (aggregate p95 across a full healthy session, ~2.6-2.8 BPM,
# rounded up for margin). Deliberately NOT bpm-scaled -- a linear/
# quadratic regression against real jitter data the same night showed no
# clean bpm-dependence (OLS fit: step ~ 1.03 - 0.0045*bpm, essentially
# flat, noisy per-tempo-bucket p95s with no monotonic trend) -- this
# candidate tests the hypothesis that bpm-scaling isn't actually
# supported by real data at all, as a genuine alternative to both the
# current shape and the analytical one above. First-cut value, pending
# review of the logged comparison.
_V2_LOCK_BAND_CANDIDATE_EMPIRICAL_BPM = 3.0
_V2_TEMPO_HOLD_S = 10.0            # only used for the primed_confidence floor now (see prime_tempo());
                                    # the hold-skip gate that used to read this for re-evaluation stickiness
                                    # was removed 2026-08-14, later still still -- see _estimate_tempo_acf()
_V2_LOW_BPM_GUARD = 115.0          # "low lane" ceiling for the low->fast guard below
_V2_FAST_BPM_GUARD = 130.0         # "fast lane" floor for the low->fast guard below
# 2026-08-14, later still: 0.80 -> 0.45. Owner: "way too high for our
# system." Extra-strict confidence required specifically for a jump from
# a low lane (<=115) to a fast lane (>=130) -- distinct from the general
# large-jump gate below, which still applies to every large jump too.
_V2_LOW_BPM_FAST_CONFIDENCE = 0.45
# 2026-08-14, later still: 0.72 -> 0.5 (owner's stated target once the
# rest of the confidence stack is retuned: "hopefully around .8 later").
# Confidence required for ANY jump outside the lock-band above -- this is
# the primary gate a track-boundary tempo change has to clear.
_V2_LARGE_JUMP_CONFIDENCE = 0.5
# 2026-08-14, later still: 3.0 -> 5.0. Owner: "never tuned or inspected."
# EMA smoothing cap -- even a fully-accepted new BPM value can only move
# the published self._bpm by this many BPM per update cycle, so a large
# accepted jump (e.g. a track change) still takes multiple cycles to
# fully arrive even once every gate above has cleared.
_V2_MAX_BPM_STEP = 5.0
# 2026-08-14, later still still (the morning after): a real, recurring
# "wobble" found both live (a solid, high-confidence lock at 127.33
# collapsed to 91.37 over ~12s mid-track, no transition involved) and in
# a synthetic 20-transition-pair sweep -- material with a true tempo
# landing between two ACF lag-grid points (124 BPM's nearest grid
# neighbors are 122.45 and 125.0) occasionally lets a competing candidate
# (often a 2:3-related lane) win the raw comb-filter argmax for a few
# consecutive cycles, and once that starts, nothing stopped it from
# riding the large-jump gate all the way down/up to a wrong resting
# value. _candidate_history (candidate_window, default 5 cycles <1s at
# _V2_ACF_INTERVAL's ~7.5 Hz) already filters single-frame noise but is
# far too short a window to catch a multi-second wobble. This is a
# SEPARATE, longer-window persistence check gating *only* out-of-band
# (large-jump) candidates specifically -- in-band nudges are unaffected,
# still governed by candidate_window alone. Verified: fixed all 3
# previously-failing seeds in a 112->124 repeat-seed test (worst final
# error 22.35 BPM -> 0.0) and the full 20-pair sweep (worst final error
# 1.33 BPM, 20/20 converged, ~6.5-12s -- a few seconds slower than
# without this check, still far faster than the pre-hold-gate-removal
# baseline). See docs/adr/vj-system.md.
_V2_LARGE_JUMP_PERSISTENCE_CYCLES = 25

# 2026-08-14, round three, the morning after (part three): two shorter
# candidate window sizes, LOGGED ONLY, for a real live A/B/C comparison
# against the 25-cycle real value above -- owner: "i told you that 25
# candidates was too many! test some more reasonable values for that."
# Motivating incident: a real session (garbage/m) showed the real gate
# holding an old track's BPM frozen for 100+ seconds across two separate
# track boundaries while dozens of fresh candidates were rejected every
# cycle -- not because nothing was happening, but because a 25-sample
# window of genuinely multi-modal candidates (competing harmonically-
# related readings, not noise) rarely spends 25 consecutive cycles
# within a 6 BPM band of each other. A shorter window checks more often,
# which should shorten the average wait for a "lucky" quiet stretch even
# under that same multi-modal condition -- but it is a distinct,
# complementary lever from the actual octave/harmonic-disambiguation gap
# (see the T5 proposal in docs/planning/
# auto-vj-round-three-planning-2026-08-14.md), not a substitute for it:
# a shorter window converges faster on average but has less evidence
# behind each acceptance, so it is not obviously better without real
# comparative data -- hence testing two additional sizes, not just
# picking one. SHORT (10 cycles, ~1.3s at the ~7.5 Hz ACF rate) is the
# fastest that still requires multiple independent-ish readings to
# agree, not a single noisy frame; MEDIUM (15 cycles, ~2.0s) is the
# halfway point. Computed via two separate parallel deques
# (_long_candidate_history_short/_medium), appended alongside the real
# window every cycle that reaches the large-jump evaluation, with their
# own cleared/reject counters using the exact same spread<=6.0/
# agreement<=6.0 criteria as the real gate -- so the comparison is
# apples-to-apples. Neither candidate gates anything.
_V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT = 10
_V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_MEDIUM = 15

# 2026-08-14, round three: sub-lag (parabolic) peak interpolation --
# proposed fix for the argmax-wandering root cause (see
# _estimate_tempo_acf()'s own comment at the interpolation block, and
# docs/planning/auto-vj-round-three-planning-2026-08-14.md § 6). Gated
# behind this flag, default OFF, specifically so it can be A/B tested as
# two sequential sessions rather than always-on from the moment it
# lands -- owner: "we'll consider my next run the A for this and the one
# directly after we'll do the B w/that fix." Flip to True in
# config.toml's [auto_vj] block (acf_peak_interpolation_enabled = true)
# for the B run.
# 2026-08-17, round three close-out: False -> True. The sequential A/B
# (A: library/c, B: library/d -- see docs/planning/
# auto-vj-round-three-planning-2026-08-14.md § 5.2) favored ON on every
# direct metric: persistence-gate clear rate 8.5% -> 19.9%, lock 68.6% ->
# 77.9%, toggles/min 4.55 -> 3.00, mean confidence 0.513 -> 0.547, with
# small bounded corrections (mean abs delta 0.20 BPM). The C run and every
# session after ran with the config override on; this makes the shipped
# default match the validated configuration. config.toml's
# acf_peak_interpolation_enabled override still works either way.
_V2_ACF_INTERPOLATION_ENABLED = True

# 2026-08-17, round three close-out: the persistence checks' spread
# thresholds become max(flat, pct * window median) instead of flat BPM
# constants. Rationale (plan § 6.3, audit T1): a flat 6.0 BPM is ~8%
# relative at 75 BPM but only ~4% at 150 -- strictest exactly where the
# lag grid is noisiest. The pct term only ever LOOSENS the gate above the
# flat floor's crossover (~171 BPM for 6.0/0.035, ~133 for 4.0/0.03), so
# low/mid-tempo behavior -- everything this round's sessions validated --
# is bit-for-bit unchanged; only the fast lanes gain the relative
# allowance the grid math says they need. Sequenced deliberately AFTER
# the interpolation default above (same close-out) per § 6.3: these two
# were tuned/validated as a pair. persistence_spread_limit is logged so
# engagement is observable (which bound was active, per evaluation).
_V2_PERSISTENCE_SPREAD_BPM = 6.0   # flat floor -- long (25-cycle) window, unchanged value
_V2_PERSISTENCE_SPREAD_PCT = 0.035  # relative component of the long-window limit
_V2_CANDIDATE_SPREAD_BPM = 4.0     # flat floor -- short (candidate_window) check, unchanged value
_V2_CANDIDATE_SPREAD_PCT = 0.03    # relative component of the short-window limit

# 2026-08-17, round three close-out: cold-start confidence-blend guard
# (plan § 6.4 / audit menu #8). downbeat_regularity measures the
# self-consistency of the just-established grid -- at cold start it is
# incumbent-confirming by construction (a wrong lock beats perfectly
# regularly against its own wrong grid; the 17:56 session's 75.95
# episode flipped bpm_locked one cycle after first candidate partly on a
# 0.25 * 0.56 regularity contribution). For the first N ACF cycles after
# a cold-start acceptance, the public confidence blend excludes the
# regularity term (its 0.25 share is given to acf_confidence, the only
# genuinely independent signal that early): 0.9*acf + 0.1*phase.
# 25 cycles ~= 3.3s at the ~7.5 Hz ACF cadence -- matched to the
# large-jump persistence window so "cold start" ends when the evidence
# deques are fully populated. Established-lock behavior is untouched.
_V2_COLD_START_GUARD_CYCLES = 25

# 2026-08-17, round three close-out: minimum lock dwell (plan § 1.2,
# owner: test candidates 8 and 16 bars, "32 bars too long"). Closes the
# residual in-band drift gap the two lock-band tightenings shrank but
# could not eliminate: a sequence of individually-legal in-band nudges
# can still accumulate into a large net drift (the 122->88 collapse
# pattern). Design is the sketch's option (c) shape: for the first
# `bpm_lock_dwell_bars` bars after a lock anchor (cold-start acceptance
# or an accepted large jump), an in-band candidate that has drifted more
# than `bpm_lock_dwell_drift_pct` cumulatively from the anchor is not
# rejected -- it is ROUTED THROUGH the existing large-jump gate stack
# (persistence window + confidence floor), so genuine early tempo
# changes still have a path (the sketch's explicit risk) while gradual
# erosion must now show large-jump-quality evidence. Bar-relative (via
# the oscillator's own bar counter), so it scales with tempo exactly as
# the owner's rolling-window framing wanted. 0 bars disables entirely.
# dwell_gated_count logs engagement per the track-new-tunables rule.
# 2026-08-31: 8.0 -> 16.0 -- the owner ran the 16-bar variant via a
# config override since 2026-08-17 and has now removed the override
# permanently, promoting the active value to the code default ("8 is
# most likely way too low").
# 2026-09-01: 16.0 -> 32.0, accepted from the 2026-08-31 accelerated
# tuning experiment (owner consensus). Deciding pair on curveballs-03
# over the margin-0.10 base: Acc1 +8pt (s3), churn -32% (s11, the
# largest churn improvement of the experiment), coverage +3.1-3.5pt,
# nothing regressed; house pair read churn -9% / inert. Validated on
# the average-track playlist set (toughies is diagnostic-only per the
# owner's 2026-08-31 ruling). Full trail: the experiment ledger
# (logs/replay/, gitignored) and docs/adr/vj-system.md.
_V2_DWELL_BARS = 32.0
_V2_DWELL_DRIFT_PCT = 0.04

# 2026-08-17, round three close-out: genre-fit-weighted candidate scoring
# (plan § 4.2, confidence-gated per the owner's refinement). When the
# previous cycle's acf_confidence is below the gate, the ACF's
# prior-weighted score array gets one extra multiplicative reweight from
# the recommender's TEMPO-INDEPENDENT genre evidence (pushed in via
# set_genre_tempo_evidence(); terms that depend on the BPM reading --
# tempo_fit, top_cand_fit, onset_fit, kick_regularity_fit -- are
# excluded on the auto_vj side, see § 6.5). Influence, not a gate: the
# boost tops out at (1 + MAX_BOOST * weight) inside the winning genre's
# tempo band and decays as a Gaussian outside it, so strong direct ACF
# evidence still wins whenever it exists; when confidence is high the
# evidence is never consulted at all. Evidence expires after STALE_S so
# a dead recommender (or a source switch) can't keep steering candidate
# selection on old opinions. genre_evidence_applied_count logs
# engagement.
_V2_GENRE_EVIDENCE_GATE_CONFIDENCE = 0.5   # consult only when last acf_conf < this
# 2026-08-17, later still: 0.35 -> 0.1, owner's own temp mitigation while
# the training-house-01 c-vs-d regression (measurably lower/noisier
# confidence and more within-track lock toggles on the same 32-track
# list, worst on already-harmonically-ambiguous tracks) is investigated.
# Owner: "let's change the genre weight to 0.1, we need to do work
# before we use that." Not a validated retune -- dials the mechanism's
# influence way down without disabling it outright, pending the planned
# same-list re-run to measure the effect directly.
# 2026-09-01: that re-run happened -- 0.1 is now BRACKET-VALIDATED from
# both sides (2026-08-31 experiment): ablation (0.0) cost churn
# +10/+38% and coverage on both curveballs seeds with Acc1 -7 on one;
# doubling (0.2) reproduced the c-vs-d toggle regression in isolation;
# the 0.5/1.0 dose sweep showed the channel amplifies evidence QUALITY
# (rescues hidden fold errors when right -- house s3 Acc1 +10 at 1.0 --
# but captures/harasses when wrong). Keep 0.1 until Stage-1 profile
# recalibration makes the evidence net-right, then revisit upward
# behind a lock-state-aware gate (see
# docs/planning/recommender-director-excellence-plan-2026-08-31.md).
_V2_GENRE_EVIDENCE_MAX_BOOST = 0.1         # peak multiplicative boost at weight=1.0
_V2_GENRE_EVIDENCE_MIN_SIGMA = 0.25        # floor (log2 units) so a tight profile can't spike one lane
_V2_GENRE_EVIDENCE_STALE_S = 20.0          # evidence older than this is ignored

# 2026-08-17, round three close-out: tap-tempo trust window (plan § 4.5,
# "cheater mode" #2). A confirmed human tap is genuine external ground
# truth (a literal real-time human tapping the actual beat), so for
# TAP_PRIME_WINDOW_S after Enter-confirm: the Gaussian tempo prior is
# re-centered on the tapped value at TAP_PRIME_SIGMA (much tighter than
# any genre profile's), candidates within TAP_PRIME_BAND_PCT of the tap
# bypass the large-jump persistence/confidence gates and the
# max_bpm_step crawl (snap, don't crawl -- the operator is telling us
# the answer), and the primed-confidence floor holds at
# TAP_PRIME_CONFIDENCE. On expiry the saved profile prior is restored
# exactly -- no permanent state change. Manual-trigger-only by
# construction (there is no automatic path to a keyboard tap), so the
# backward-flow class of bug structurally cannot apply.
_V2_TAP_PRIME_WINDOW_S = 30.0
_V2_TAP_PRIME_SIGMA = 0.10        # log2(BPM) units -- tight, human-measured
_V2_TAP_PRIME_BAND_PCT = 0.06     # candidates within +-6% of the tap get the fast path
_V2_TAP_PRIME_CONFIDENCE = 0.85   # primed-confidence floor for the window

# 2026-08-17, round three close-out: energy-slope history is time-bounded
# (seconds) instead of frame-counted (audit menu #10 / F7). The old
# deque(maxlen=240) was 240 FRAMES: exactly the documented ~4s window at
# 60 fps, but only 1.67s at 144 fps -- where the ">= 2s old" slope
# reference check could then never pass, silently zeroing energy_slope
# and killing BUILD detection on high-refresh displays. Same real window
# as before at 60 fps (preset slope thresholds stay tuned against ~4s;
# see the "do not fix the window length" field comment), now honest at
# any frame rate.
_V2_ENERGY_WINDOW_S = 4.0

# --------------------------------------------------------------------------
# Drop trigger/sustain split (2026-08-18) — the drop-score redesign plan
# (docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md § 4) plus
# the 2026-08-11 music-theory audit's corrections (F1/F3/F4/F9). Two NEW
# signals computed alongside (not replacing) the legacy drop_score
# composite:
#
#   impact_novelty — the TRIGGER (boundary/event): bass transient AND
#     broadband mid+treble activity, coming out of a suppressed bass
#     state, with rising energy as influence-not-gate. Multiplicative
#     coincidence (the asymmetric EMAs themselves are the lead/lag
#     window, per audit F3).
#   drop_sustain — the SUSTAIN (state): are we currently IN a drop
#     section. Product form (audit F9): bass level is load-bearing by
#     construction — zero bass forces zero sustain, no weight accounting
#     can erode the "no bass, no drop" invariant.
#
# The bass LEVEL primitive both need (audit F4's two-timescale/percentile
# form, chosen over the plan's asymmetric-alpha z-score whose stated
# direction was ambiguous-to-inverted): a fast EMA of the raw-path level
# (AudioData.bass_level_raw, audit F1 — pre-normalization, so it has real
# dynamic range) normalized against a rolling low-percentile reference
# over a long ring. A percentile reference cannot renormalize during a
# 60 s drop by construction — the exact failure that made band_blend
# fade held drops toward "boring". bass_was_suppressed falls out of the
# same ring for free (1 − recent max, windowed in BARS per audit F4:
# many buildups keep the kick until the last 1-2 bars, so a short
# ~1-bar window is OR'd with the longer one to catch the pre-drop gap).
# All new EMAs are time-constant-based (dt-independent, audit F7).
_V2_BASS_LEVEL_RING_S = 90.0        # slow-reference history window
_V2_BASS_LEVEL_RING_RATE = 20.0     # Hz — ring sample rate (1800 slots)
_V2_BASS_LEVEL_FAST_TAU_S = 0.3     # fast level EMA time constant
_V2_BASS_LEVEL_REF_LO_PCT = 20.0    # slow reference = ring p20
_V2_BASS_LEVEL_REF_HI_PCT = 80.0    # range norm = (p80 − p20)
_V2_BASS_LEVEL_PCT_REFRESH_S = 0.25  # percentile recompute cadence
_V2_BASS_SUPP_WINDOW_BARS = 6.0     # long suppression window (bars)
_V2_BASS_SUPP_SHORT_BARS = 1.0      # pre-drop-gap window (bars)
# Trigger mid+treble activity: residual flux (spectral_flux − bass_flux)
# — deliberately the same broadband residual the legacy composite's
# flux term uses (includes low-mids, air, and the rms_rise bonus), NOT a
# literal mid_flux + treble_flux; audit F3 says either is defensible but
# pick one and note it, since thresholds tuned on one don't transfer.
# Asymmetric fast-attack/slow-release taus match bass_flux_fast's
# per-frame 0.4/0.6-attack, 0.85/0.15-release shape at 60 fps,
# re-expressed as time constants.
_V2_MIDTREB_FAST_ATTACK_TAU_S = 0.018
_V2_MIDTREB_FAST_RELEASE_TAU_S = 0.103
_V2_MIDTREB_BUSY_TAU_S = 2.0        # sustain-side busyness (bar-scale state)
# x/(x+c) normalization constant for the residual-flux terms (audit F3:
# the draft's activity term was unbounded, making thresholds material-
# and gain-dependent). Grounded empirically 2026-08-18 via the replay
# harness: pooled fast-EMA distribution over 11 mixed real library
# tracks / 72.6k ticks read p25/p50/p75 = 123/181/264, so c = 180 maps
# the pooled median to 0.5 — same grounding discipline bass_flux_norm's
# 0.05 used. Resulting impact_novelty distribution over the same pool:
# p50 0.24, p95 0.44, p99 0.59, max 0.92 (the director's trigger
# threshold defaults sit at ~p99 — triggers are rare events).
_V2_MIDTREB_FLUX_NORM_C = 180.0
_V2_SUSTAIN_BUSY_FLOOR = 0.3        # F9's soft floor: sustain =
#                                     level * (floor + (1-floor)*busyness)

# 2026-08-17, later still: onset-strength history -- raw (pre-compression)
# and compressed (actual envelope-written) strength of every onset, time-
# bounded like _V2_ENERGY_WINDOW_S above. Added because the envelope
# pulse-strength log-compression (_pulse_envelope(), rc.33) had zero
# logged real-session evidence: the only supporting data was a synthetic
# harness (tools/pulse_compression_harness.py). Owner, on realizing the
# gap: "we shouldn't be missing anything! crikey lol." `onset_strength_
# max_raw`/`_max_compressed` expose the window's max of each so a
# training-corpus reader can reconstruct the compression's real-world
# effect at the tail (where it's designed to matter) directly from
# sequence-corpus rows, the same way phase_error_median/iqr closed the
# equivalent gap for phase alignment.
_V2_ONSET_STRENGTH_WINDOW_S = 10.0

# Tempo-pick hardening for sparse/slow material
_V2_RAW_DOMINANCE_RATIO = 1.18
_V2_DENSITY_FAST_RATIO = 1.30
_V2_DENSITY_SCORE_RATIO = 0.45

# 2026-08-13: tactus fold-down disambiguation guard. A candidate must clear
# tactus_preference_ratio on raw comb-filter score AND not be measurably
# less internally self-consistent (_analysis_region_consistency) than the
# lane it would replace -- catches folds where the octave-down candidate
# only wins on score because the fold destination doesn't actually explain
# the recent beat spacing any better. First-cut value, not yet validated
# against real session data -- see docs/adr/vj-system.md. 0.70 chosen
# conservatively (candidate must retain at least 70% of the current lane's
# region-consistency) so it only rejects clearly worse folds rather than
# second-guessing close calls.
_TACTUS_REGION_GUARD_RATIO = 0.70

# 2026-08-13, same day (kr/dbc option B): scales the effective tactus
# fold-eagerness by the caller-supplied kick_regularity reading (0..1,
# raw kick-band-energy consistency, genre-independent -- see
# BeatTracker._kick_regularity and _effective_tactus_ratio()). Only ever
# makes folding *stricter* than the validated tactus_preference_ratio
# baseline, never more eager than it -- at kick_regularity=1.0 the
# effective ratio equals the baseline unchanged (the validated case);
# it climbs toward baseline + this spread as kick_regularity falls
# toward 0.0 (sparse/irregular kicks -- the documented R&B/hip-hop
# triplet-fold risk territory). Retroactively checked against the three
# borderline fold cases found while validating tactus_preference_ratio
# on real ground truth (see docs/adr/vj-system.md): all three had
# below-median kick_regularity (0.34-0.63 vs. a 0.70 library median),
# and this spread would have pushed their effective ratio to 0.66-0.75
# -- meaningfully stricter, in the direction that would have reduced or
# blocked those folds. First-cut value pending live validation once this
# actually drives real sessions, per the "test/tweak/test, decide"
# sequencing agreed for this option.
_TACTUS_KICK_REGULARITY_SPREAD = 0.30


class BeatTracker:
    """ACF-based tempo estimator with phase-locked oscillator (v2).

    Drop-in replacement for ``BeatGridTracker``.  Enable with::

        [auto_vj]
        beat_tracker_engine = "v2"

    Algorithm:
    1. Onset events (from Analyzer.drain_onsets) are accumulated into a
       100 Hz internal envelope ring of length 800 samples (8 seconds).
    2. Every _V2_ACF_INTERVAL frames, numpy.correlate is run on the
       zero-mean envelope to find the dominant periodicity.  A Gaussian
       perceptual prior centred at 120 BPM suppresses octave confusion.
       An octave-down preference resolves fast-half-time ambiguity.
    3. A phase oscillator advances at bpm/60 Hz per second.  When an onset
       lands within ±18% of phase 0, it nudges the phase (phase-lock).
       Off-grid onsets are ignored — no IOI contamination.
    4. Confidence is the rolling fraction of the last 32 onsets that landed
       within the tolerance window (phase coherence).
    5. Energy, slope, and drop_score are inherited from BeatGridTracker
       logic so the director's transition model is unaffected.

    Thread-safety: call only from the main render thread.
    """

    # Semver of this tempo-estimation engine (SemVer 2.0.0; see CLAUDE.md
    # "Versioning & Release Standards"). MAJOR tracks the engine generation
    # (matches the "v2"/"v3" beat_tracker_engine config name); MINOR/PATCH
    # track tuning changes within it. Bump on any behavior-changing edit to
    # this class. Logged into decision-log / sequence-corpus rows so A/B
    # comparisons across engine versions are traceable per session.
    ENGINE_VERSION = '2.0.0'
    # 2026-08-15: separate from ENGINE_VERSION above -- this is the
    # module-level _DETECTOR_VERSION tuning-state counter (bumps on gate/
    # threshold changes; ENGINE_VERSION only moves on an architecture
    # generation change). Exposed as a class attribute, mirroring
    # ENGINE_VERSION's own pattern, so a caller holding a BeatTracker
    # instance (e.g. AutoVJController) can log it without a second
    # dynamic module load. Owner: "add the detector version to something
    # in the training logs" -- comparing a track's BPM behavior across
    # sessions (e.g. "Shake That Monkey") needs to rule out "the code
    # changed" before concluding the ambiguity itself is real.
    DETECTOR_VERSION = _DETECTOR_VERSION

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self._bpm_min: float = float(cfg.get('bpm_min', _V2_BPM_MIN) or _V2_BPM_MIN)
        self._bpm_max: float = float(cfg.get('bpm_max', _V2_BPM_MAX) or _V2_BPM_MAX)
        self._prior_mu: float = float(cfg.get('prior_mu', _V2_PRIOR_MU) or _V2_PRIOR_MU)
        self._prior_sigma: float = max(
            _MIN_PROFILE_PRIOR_SIGMA,
            float(cfg.get('prior_sigma', _V2_PRIOR_SIGMA) or _V2_PRIOR_SIGMA),
        )
        self._phase_tol: float = float(cfg.get('phase_tolerance', _V2_PHASE_TOL) or _V2_PHASE_TOL)
        self._refractory_factor: float = float(cfg.get('refractory_factor', 0.70) or 0.70)
        self._env_window_s: float = float(cfg.get('envelope_seconds', _V2_ENV_WINDOW_S) or _V2_ENV_WINDOW_S)
        self._acf_score_floor: float = float(cfg.get('acf_score_floor', 1e-4) or 1e-4)
        self._min_update_confidence: float = float(
            cfg.get('min_update_confidence', _V2_MIN_UPDATE_CONFIDENCE) or _V2_MIN_UPDATE_CONFIDENCE
        )
        self._startup_confidence: float = float(
            cfg.get('startup_confidence', _V2_STARTUP_CONFIDENCE) or _V2_STARTUP_CONFIDENCE
        )
        self._kick_evidence_alpha: float = float(
            cfg.get('kick_evidence_alpha', _V2_KICK_EVIDENCE_ALPHA) or _V2_KICK_EVIDENCE_ALPHA
        )
        self._min_kick_evidence: float = float(
            cfg.get('min_kick_evidence', _V2_MIN_KICK_EVIDENCE) or _V2_MIN_KICK_EVIDENCE
        )
        self._kick_evidence_smooth: float = 0.0
        self._kick_evidence_reject_count: int = 0
        self._max_bpm_step: float = float(cfg.get('max_bpm_step', _V2_MAX_BPM_STEP) or _V2_MAX_BPM_STEP)
        self._candidate_window: int = int(cfg.get('candidate_window', 5) or 5)
        self._lock_band_pct: float = float(cfg.get('lock_band_pct', _V2_LOCK_BAND_PCT) or _V2_LOCK_BAND_PCT)
        self._lock_band_min: float = float(cfg.get('lock_band_min', _V2_LOCK_BAND_MIN) or _V2_LOCK_BAND_MIN)
        # 2026-08-17: candidate_lock_disagreement's own, deliberately wider
        # band -- see _V2_REFRACTORY_GUARD_BAND_PCT/_MIN's own comment.
        self._refractory_guard_band_pct: float = float(
            cfg.get('refractory_guard_band_pct', _V2_REFRACTORY_GUARD_BAND_PCT) or _V2_REFRACTORY_GUARD_BAND_PCT
        )
        self._refractory_guard_band_min: float = float(
            cfg.get('refractory_guard_band_min', _V2_REFRACTORY_GUARD_BAND_MIN) or _V2_REFRACTORY_GUARD_BAND_MIN
        )
        self._tempo_hold_s: float = float(cfg.get('tempo_hold_s', _V2_TEMPO_HOLD_S) or _V2_TEMPO_HOLD_S)
        self._tempo_hold_until_t: float = -1e9
        # 2026-08-06: floor applied to self._confidence while _tempo_hold_until_t
        # is still fresh (see prime_tempo() and both self._confidence = 0.4*acf +
        # 0.6*phase sites). Without this, prime_tempo()'s confidence boost was
        # purely cosmetic -- the very next onset recomputed self._confidence
        # from the raw ACF/phase blend with no memory a prime had just happened,
        # so a mixer-primed 0.9 would collapse back to ~0.2 within one onset if
        # the live phase-coherence buffer hadn't caught up yet. Real live-session
        # evidence: primed bpm=125 conf=0.90 -> conf=0.23 in 0.5s, same bpm,
        # repeating roughly every recommender eval cycle. See docs/adr/vj-system.md.
        self._primed_confidence: float = 0.0
        self._silence_reset_s: float = float(cfg.get('silence_reset_s', 15.0) or 15.0)
        self._low_bpm_guard: float = float(cfg.get('low_bpm_guard', _V2_LOW_BPM_GUARD) or _V2_LOW_BPM_GUARD)
        self._fast_bpm_guard: float = float(cfg.get('fast_bpm_guard', _V2_FAST_BPM_GUARD) or _V2_FAST_BPM_GUARD)
        self._low_bpm_fast_confidence: float = float(
            cfg.get('low_bpm_fast_confidence', _V2_LOW_BPM_FAST_CONFIDENCE) or _V2_LOW_BPM_FAST_CONFIDENCE
        )
        self._large_jump_confidence: float = float(
            cfg.get('large_jump_confidence', _V2_LARGE_JUMP_CONFIDENCE) or _V2_LARGE_JUMP_CONFIDENCE
        )
        self._tactus_check_bpm: float = float(cfg.get('tactus_check_bpm', 115.0) or 115.0)
        self._tactus_preference_ratio: float = float(cfg.get('tactus_preference_ratio', 0.55) or 0.55)
        # 2026-08-13 (kr/dbc option B): raw kick-band-energy consistency
        # (0..1) supplied by the caller each update() -- see
        # _effective_tactus_ratio() for how it modulates fold eagerness.
        # Defaults to 0.0 (most conservative / least eager to fold) when
        # the caller doesn't supply one, so callers that don't wire this
        # through (tests, the shadow tracker if ever run without it) see
        # the strictest behavior rather than silently getting the most
        # permissive one.
        self._kick_regularity: float = 0.0
        # 2026-08-14: session-cumulative counters for _tactus_fold_accepted()
        # outcomes -- observability for kr/dbc options A/B now that they're
        # about to drive a real session for the first time. Monotonically
        # increasing (never reset mid-session, same convention as
        # beat_index/onset_count) so a corpus row-to-row delta shows fold-
        # guard activity rate. See tactus_fold_accepted_count/
        # tactus_region_reject_count/tactus_score_reject_count properties
        # and _detector_snapshot() in auto_vj.py.
        self._tactus_fold_accepted_count: int = 0
        self._tactus_region_reject_count: int = 0
        self._tactus_score_reject_count: int = 0
        # 2026-08-14, later still: most recent individual fold decision
        # (counters above only tally outcomes, not which fold each one
        # was) -- '' until the first tactus evaluation this session. See
        # _tactus_fold_accepted()'s own docstring and the last_tactus_fold
        # property below.
        self._last_tactus_fold: str = ''
        self._last_onset_t: float = -1e9
        self._audio_dt_max: float = float(cfg.get('audio_dt_max_s', 0.25) or 0.25)

        # Analysis mode: keeps a short rolling beat-position map and uses it
        # to gate downbeats and validate large tempo-lane changes.
        #
        # WARNING (2026-08-14): this was, until now, an opt-in
        # `analysis_mode_enabled` config flag defaulting to False -- and
        # every install that never explicitly enabled it was running a
        # measurably weaker detector without knowing it: downbeats fired
        # unconditionally every bar (no confidence gate at all), the large
        # tempo-jump guard had no beat-position cross-check, and
        # downbeat_confidence was a fake -- just a copy of the top-level
        # confidence value, not an independent signal. Ripped out and
        # hardcoded on (2026-08-14, same session that added the
        # downbeat_regularity confidence-blend term, which depends on this
        # being on to be anything but a flat constant -- see
        # _downbeat_regularity()'s own docstring). Do not reintroduce a way
        # to disable this without a very good reason and the owner's
        # explicit sign-off -- it silently cripples downbeat gating and the
        # jump guard, exactly the kind of regression nobody would notice
        # until asking "wait, was this ever on?" See docs/adr/vj-system.md.
        self._analysis_map_beats: int = int(cfg.get('analysis_map_beats', _V2_ANALYSIS_MAP_BEATS) or _V2_ANALYSIS_MAP_BEATS)
        self._analysis_region_min_beats: int = int(cfg.get('analysis_region_min_beats', _V2_ANALYSIS_REGION_MIN_BEATS) or _V2_ANALYSIS_REGION_MIN_BEATS)
        self._analysis_region_tol: float = float(cfg.get('analysis_region_tol', _V2_ANALYSIS_REGION_TOL) or _V2_ANALYSIS_REGION_TOL)
        self._analysis_region_confidence_min: float = float(cfg.get('analysis_region_confidence_min', _V2_ANALYSIS_REGION_CONFIDENCE_MIN) or _V2_ANALYSIS_REGION_CONFIDENCE_MIN)
        self._analysis_downbeat_confidence_min: float = float(cfg.get('analysis_downbeat_confidence_min', _V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN) or _V2_ANALYSIS_DOWNBEAT_CONFIDENCE_MIN)
        self._beat_position_map: deque[float] = deque(maxlen=max(16, self._analysis_map_beats))
        self._last_downbeat_confidence: float = 0.0

        # P4: onset envelope ring at 100 Hz
        env_len = max(200, int(_V2_ENV_RATE * self._env_window_s))
        self._env_buf: np.ndarray = np.zeros(env_len, dtype=np.float32)
        self._env_len: int = env_len
        self._env_write_idx: int = 0
        self._env_t_acc: float = 0.0            # legacy accumulator, unused after E5 (kept for shadow/telemetry readers)
        self._env_filled: bool = False
        # E5 (2026-09-03, detector rc.41): the envelope is indexed by ABSOLUTE
        # sample index floor((t - t0) * _V2_ENV_RATE). No accumulator, so two
        # advances in one tick cannot double count and a pulse cannot steal a
        # step -- both were measured (95.7-96.3 samples/s against the nominal
        # 100 on real music => tempo ~+1.3% high in v2 and v3; madmom 0.00%).
        self._env_t0: float | None = None       # time of envelope sample 0
        self._env_next_idx: int = 0              # absolute index of the next slot to write
        self._last_t: float = -1e9
        self._phase_last_t: float = -1e9

        # P5: phase oscillator state
        self._bpm: float = 0.0
        self._phase: float = 0.0        # 0..1, wraps at beat boundary
        self._bar_beat_count: int = 0
        self._is_beat: bool = False
        self._is_downbeat: bool = False
        self._beat_phase: float = 0.0   # same as _phase for public API
        # Monotonically increasing count of oscillator beat crossings, used by
        # the training corpus writer to sample on musical time rather than a
        # fixed wall-clock interval.
        self._beat_index: int = -1

        # Confidence — self._confidence is the public blend of two distinct,
        # independently-persisted signals so neither is silently clobbered by
        # the other's update cadence:
        #   _phase_confidence — raw phase coherence, refreshed on every onset
        #   _acf_confidence   — ACF peak-ratio confidence, refreshed only when
        #                       _estimate_tempo_acf() completes a full update
        #                       (throttled to 1-in-_V2_ACF_INTERVAL frames,
        #                       further gated by several early-return guards)
        # 2026-08-14: strength/band-weighted phase coherence (superseding
        # the flat per-onset hit/miss buffer). Two parallel deques instead
        # of one -- _coherence_hit_weight holds the onset's weight if it
        # landed on-beat (else 0.0), _coherence_total_weight holds the
        # onset's weight regardless of outcome. _phase_confidence becomes
        # a weighted hit-rate (sum of hit weights / sum of total weights)
        # instead of a flat count ratio. See _absorb_onset() and
        # docs/adr/vj-system.md.
        self._coherence_hit_weight: deque[float] = deque(maxlen=_V2_COHERENCE_WINDOW)
        self._coherence_total_weight: deque[float] = deque(maxlen=_V2_COHERENCE_WINDOW)
        self._phase_confidence: float = 0.0
        self._acf_confidence: float = 0.0
        self._confidence: float = 0.0
        # Cached so the top-level confidence blend's third term is
        # externally observable (property below) -- previously computed
        # fresh inline and discarded, never logged. See docs/adr/vj-system.md.
        self._downbeat_regularity_value: float = 0.0
        # 2026-08-14, later still: same rationale, for the large-jump
        # accept/reject gate's region-consistency check (property below).
        # 0.0 (not yet computed) until the first large-jump candidate is
        # evaluated -- most updates are small, in-band nudges that never
        # touch this check at all.
        self._region_consistency_value: float = 0.0

        # ACF tempo update throttle
        self._acf_frame_count: int = 0
        # 2026-08-17 (v3 plan Part 2, Phase A item 7 — per-cycle candidate
        # logging): observability only, zero behavior change, no detector
        # version bump. The offline replay harness
        # (training-kit-01/tools/track_replay.py) sets cycle_log_hook to a
        # callable receiving one dict per completed ACF cycle — the raw
        # top candidates, gate counters, and lock state that the ~1 Hz
        # training corpus can never reconstruct (T5 Option C's missing
        # data). Live code never sets it; the hook adds nothing to the
        # frame budget when None.
        self._acf_cycle_count: int = 0
        self.cycle_log_hook: Any = None
        self._candidate_history: deque[float] = deque(maxlen=self._candidate_window)
        self._large_jump_persistence_cycles: int = int(
            cfg.get('large_jump_persistence_cycles', _V2_LARGE_JUMP_PERSISTENCE_CYCLES)
            or _V2_LARGE_JUMP_PERSISTENCE_CYCLES
        )
        # 2026-08-14, round three: A/B test flag for sub-lag peak
        # interpolation -- see _V2_ACF_INTERPOLATION_ENABLED's own comment
        # (default True since 2026-08-17, validated by the library/c vs
        # library/d A/B).
        self._interpolation_enabled: bool = bool(
            cfg.get('acf_peak_interpolation_enabled', _V2_ACF_INTERPOLATION_ENABLED)
        )
        # 2026-08-17, round three close-out -- relative spread components
        # for both persistence checks (see _V2_PERSISTENCE_SPREAD_PCT's
        # field comment). The effective limit each evaluation is
        # max(flat, pct * window_median); the flat floors keep low/mid
        # tempo behavior identical to the validated sessions.
        self._persistence_spread_bpm: float = float(
            cfg.get('persistence_spread_bpm', _V2_PERSISTENCE_SPREAD_BPM) or _V2_PERSISTENCE_SPREAD_BPM
        )
        self._persistence_spread_pct: float = max(0.0, float(
            cfg.get('persistence_spread_pct', _V2_PERSISTENCE_SPREAD_PCT) or 0.0
        ))
        self._candidate_spread_bpm: float = float(
            cfg.get('candidate_spread_bpm', _V2_CANDIDATE_SPREAD_BPM) or _V2_CANDIDATE_SPREAD_BPM
        )
        self._candidate_spread_pct: float = max(0.0, float(
            cfg.get('candidate_spread_pct', _V2_CANDIDATE_SPREAD_PCT) or 0.0
        ))
        # Last effective long-window spread limit (engagement logging --
        # which bound was binding). 0.0 until the first large-jump eval.
        self._persistence_spread_limit: float = 0.0
        # When the long-window median/spread were last actually computed
        # (freshness for candidate_lock_disagreement -- a stale median
        # from minutes ago must not read as live disagreement).
        self._long_candidate_eval_t: float = -1e9
        # 2026-08-17: cold-start confidence-blend guard (see
        # _V2_COLD_START_GUARD_CYCLES). Counts down one per ACF cycle
        # after a cold-start acceptance; while positive, the public blend
        # excludes downbeat_regularity (incumbent-confirming that early).
        self._cold_start_guard_cycles: int = int(
            cfg.get('cold_start_guard_cycles', _V2_COLD_START_GUARD_CYCLES) or _V2_COLD_START_GUARD_CYCLES
        )
        self._cold_start_cycles_left: int = 0
        # 2026-08-17: minimum lock dwell (see _V2_DWELL_BARS). Anchor is
        # the BPM at the last lock event (cold-start accept / accepted
        # large jump); bars are counted on oscillator bar wraps.
        self._dwell_bars: float = max(0.0, float(
            cfg.get('bpm_lock_dwell_bars', _V2_DWELL_BARS) or 0.0
        ))
        self._dwell_drift_pct: float = max(0.0, float(
            cfg.get('bpm_lock_dwell_drift_pct', _V2_DWELL_DRIFT_PCT) or 0.0
        ))
        self._lock_anchor_bpm: float = 0.0
        self._bars_since_lock: int = 0
        self._dwell_gated_count: int = 0
        # 2026-08-17: T5 Option A -- persistence deques cleared on every
        # accepted large jump (see the acceptance tail). Counter only;
        # the cumulative wait/reject/cleared counters are never reset.
        self._persistence_reset_count: int = 0
        # 2026-08-17: genre-fit-weighted candidate scoring (see
        # _V2_GENRE_EVIDENCE_GATE_CONFIDENCE). Evidence is pushed by the
        # recommender via set_genre_tempo_evidence() and expires.
        self._genre_evidence_enabled: bool = bool(
            cfg.get('genre_candidate_scoring_enabled', True)
        )
        _gate = cfg.get('genre_candidate_gate_confidence', None)
        # No `or` fallback here: 0.0 is a legitimate configured value
        # (it disables consultation entirely, since acf_confidence is
        # never negative).
        self._genre_evidence_gate_confidence: float = (
            float(_gate) if _gate is not None else _V2_GENRE_EVIDENCE_GATE_CONFIDENCE
        )
        self._genre_evidence_mu: float = 0.0
        self._genre_evidence_sigma: float = _V2_GENRE_EVIDENCE_MIN_SIGMA
        self._genre_evidence_weight: float = 0.0
        self._genre_evidence_until_t: float = -1e9
        self._genre_evidence_applied_count: int = 0
        # 2026-08-17: tap-tempo trust window (see _V2_TAP_PRIME_WINDOW_S).
        self._tap_prime_until_t: float = -1e9
        self._tap_prime_bpm: float = 0.0
        self._tap_saved_prior: tuple[float, float] | None = None
        self._tap_prime_accept_count: int = 0
        # 2026-08-17: signed phase-error distribution (audit menu #2) --
        # raw signed err from every _absorb_onset() evaluation, so the
        # phase-confidence cap investigation can distinguish "genuinely
        # off-beat onset mix" (median ~0, wide IQR) from a mechanical
        # offset (displaced median). Unweighted deliberately: this is the
        # measurement-error distribution, not the confidence input.
        self._phase_err_buf: deque[float] = deque(maxlen=_V2_COHERENCE_WINDOW)
        self._long_candidate_history: deque[float] = deque(maxlen=self._large_jump_persistence_cycles)
        # 2026-08-14, later still still (the morning after, round two):
        # session-cumulative counters for the long-persistence check's own
        # outcomes -- same "don't let it hide" rationale as the tactus
        # fold counters (2026-08-14 earlier). Owner: "we need to track and
        # tune that persistence window eventually maybe.. let's not let
        # that hide on us like others have." Never reset mid-session (see
        # _reset_tempo_lock()), so a corpus row-to-row delta shows real
        # engagement rate. See docs/adr/vj-system.md and the matching
        # public properties below.
        self._large_jump_persistence_wait_count: int = 0
        self._large_jump_persistence_reject_count: int = 0
        self._large_jump_persistence_cleared_count: int = 0
        # 2026-08-14, round three: the persistence check's own median/
        # spread of the last `_large_jump_persistence_cycles` candidates
        # were computed every evaluation and then discarded -- a real
        # session (see docs/adr/vj-system.md) needed to reconstruct them
        # after the fact from the much coarser (~1 Hz) decision-tick log,
        # and that reconstruction was necessarily imprecise (each corpus
        # row is one sample of roughly 7-8 real ACF cycles at
        # `_V2_ACF_INTERVAL`'s ~7.5 Hz). Cached here so a future session
        # can answer "is the 6.0 BPM spread threshold right?" from ground
        # truth instead of reconstruction. 0.0 until the first large-jump
        # candidate is evaluated, same convention as region_consistency.
        self._long_candidate_spread: float = 0.0
        self._long_candidate_median: float = 0.0
        # 2026-08-14, round three, the morning after (part three): two
        # shorter-window candidates, logged only -- see
        # _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT's own comment.
        # Independent deques (not derived from the real one, since a
        # smaller maxlen needs its own append history, not a slice of the
        # real 25-long one) and their own cleared/reject counters, same
        # session-cumulative convention as the real ones above.
        self._long_candidate_history_short: deque[float] = deque(
            maxlen=_V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT
        )
        self._long_candidate_history_medium: deque[float] = deque(
            maxlen=_V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_MEDIUM
        )
        self._large_jump_persistence_cleared_count_short: int = 0
        self._large_jump_persistence_reject_count_short: int = 0
        self._large_jump_persistence_cleared_count_medium: int = 0
        self._large_jump_persistence_reject_count_medium: int = 0
        # 2026-08-14, round three, A/B test: how much the sub-lag
        # interpolation below moved this cycle's reading off the raw
        # integer-lag grid value, in BPM. 0.0 before the first ACF cycle
        # and at a grid edge (peak_idx at either end of the search range,
        # where interpolation is skipped). See _estimate_tempo_acf().
        self._acf_interpolation_delta_bpm: float = 0.0
        # 2026-08-14, round three: two candidate lock-band shapes, logged
        # only -- see _V2_LOCK_BAND_CANDIDATE_ANALYTICAL_K's own comment.
        # Updated every cycle (unconditionally, cheap arithmetic), unlike
        # long_candidate_spread above which only updates during an actual
        # large-jump evaluation -- these three (this pair plus the real
        # live jump_limit) need to be comparable on every row, not just
        # jump-evaluation rows, to judge the alternate shapes fairly.
        self._lock_band_candidate_analytical: float = 0.0
        self._lock_band_candidate_empirical: float = 0.0
        # Top-N ACF candidates (bpm, normalised_score) from last estimate cycle.
        # Updated alongside _bpm; read by the recommender for multi-hypothesis scoring.
        self._top_candidates: list[tuple[float, float]] = []

        # Energy + slope (same as BeatGridTracker for director compat).
        # See BeatGridTracker's field comment: this is actually a ~4s window
        # in steady state, not the "2s" the name suggests — preset slope
        # thresholds are tuned against that real window.
        self._energy: float = 0.0
        self._energy_alpha: float = 0.08
        self._energy_history: deque[tuple[float, float]] = deque(maxlen=4096)
        # maxlen is a memory backstop only -- the real window is
        # _V2_ENERGY_WINDOW_S seconds, age-pruned at append time
        # (2026-08-17; was maxlen=240 FRAMES, which silently
        # shrank the window on high-refresh displays -- see
        # _V2_ENERGY_WINDOW_S's field comment).
        self._energy_prev_2s: float = 0.0
        # 2026-08-17, later still: (t, raw_strength, compressed_strength)
        # per onset, time-bounded at _V2_ONSET_STRENGTH_WINDOW_S -- see its
        # own comment. maxlen is a memory backstop only, same convention as
        # _energy_history above.
        self._onset_strength_history: deque[tuple[float, float, float]] = deque(maxlen=2048)
        self._drop_score: float = 0.0
        self._flux_smooth: float = 0.0  # EMA-smoothed spectral flux for drop_score
        # 2026-08-09: fast-attack/slower-release envelope for the bass-band
        # transient term (bass_flux_norm) -- deliberately NOT the same
        # symmetric 0.75/0.25 EMA as _flux_smooth above. A big bass hit
        # after near-silence should register within a frame or two, not get
        # smoothed away; see docs/planning/
        # auto-vj-director-detector-refinement-plan-2026-08-09.md section 4b.
        self._bass_flux_fast: float = 0.0

        # Trigger/sustain split state (2026-08-18) — see the _V2_BASS_LEVEL_*
        # constants block for the full design. Independent tracker state:
        # deliberately NOT shared with _norm()'s z-scores or any other
        # consumer (the redesign's separation-of-concerns rule).
        _ring_len = int(_V2_BASS_LEVEL_RING_S * _V2_BASS_LEVEL_RING_RATE)
        self._bass_level_ring: np.ndarray = np.zeros(_ring_len, dtype=np.float32)
        self._bass_level_ring_idx: int = 0
        self._bass_level_ring_filled: int = 0   # valid entries so far
        self._bass_level_ring_t_acc: float = 0.0
        self._bass_level_fast: float = 0.0
        self._bass_level_ref_lo: float = 0.0    # cached ring p20
        self._bass_level_ref_hi: float = 0.0    # cached ring p80
        self._bass_level_pct_t: float = -1e9    # last percentile refresh
        self._midtreb_fast: float = 0.0         # fast-attack/slow-release
        self._midtreb_busy: float = 0.0         # bar-scale symmetric EMA
        self._impact_novelty: float = 0.0
        self._drop_sustain: float = 0.0
        self._bass_level_norm_value: float = 0.0
        self._bass_suppressed_value: float = 0.0
        self._band_alpha: float = float(cfg.get('detector_band_alpha', 0.08) or 0.08)
        self._band_mean_bass: float = 0.0
        self._band_mean_mid: float = 0.0
        self._band_mean_treble: float = 0.0
        self._band_var_bass: float = 1e-4
        self._band_var_mid: float = 1e-4
        self._band_var_treble: float = 1e-4

        # Pending downbeat callbacks
        self._pending_callbacks: list = []

        # Pre-allocate ACF work arrays to avoid hot-path allocation
        self._acf_lags: np.ndarray | None = None
        self._acf_bpms: np.ndarray | None = None
        self._acf_prior: np.ndarray | None = None
        self._setup_acf_arrays()

    # ------------------------------------------------------------------ #
    # Pre-allocation                                                        #
    # ------------------------------------------------------------------ #

    def _setup_acf_arrays(self) -> None:
        """Pre-compute static lag→BPM and prior arrays for the ACF step."""
        lag_min = max(1, int(60.0 / self._bpm_max * _V2_ENV_RATE))
        lag_max = int(60.0 / self._bpm_min * _V2_ENV_RATE)
        lag_max = min(lag_max, self._env_len // 2)
        if lag_max <= lag_min:
            return
        lags = np.arange(lag_min, lag_max + 1, dtype=np.float32)
        bpms = 60.0 / (lags / _V2_ENV_RATE)
        # Log-tempo prior (octave-symmetric). A Gaussian on log2(BPM) gives
        # equal weight to octave-related candidates instead of biasing toward
        # tempos numerically close to the centre, which was structurally
        # under-weighting fast tempos (e.g. 164 BPM scored 3.2x lower than
        # its 2/3 metric ambiguity at 109 BPM).
        log_bpms = np.log2(bpms)
        log_mu = float(np.log2(self._prior_mu))
        prior = np.exp(
            -0.5 * ((log_bpms - log_mu) / self._prior_sigma) ** 2
        ).astype(np.float32)
        self._acf_lag_min = lag_min
        self._acf_lag_max = lag_max
        self._acf_lags = lags
        self._acf_bpms = bpms.astype(np.float32)
        self._acf_prior = prior

    # ------------------------------------------------------------------ #
    # Public update                                                         #
    # ------------------------------------------------------------------ #

    def update(
        self,
        dt: float,
        audio: Any,
        onsets: Any = None,
        t: float | None = None,
        kick_regularity: float | None = None,
    ) -> None:
        """Per-frame update — mirror of BeatGridTracker.update() signature.

        ``kick_regularity`` (2026-08-13, kr/dbc option B): optional 0..1
        kick-band-energy consistency reading from the caller (see
        ``AutoVJController._compute_kick_regularity()``) -- persisted across
        calls when omitted/``None`` so a caller that only computes it every
        few frames doesn't reset the tracker's view of it. See
        ``_effective_tactus_ratio()``.
        """
        if kick_regularity is not None:
            self._kick_regularity = float(kick_regularity)
        now: float = t if t is not None else time.monotonic()
        # Use analyzer event time as clock source when explicit audio-time
        # isn't provided. This keeps phase advancement aligned to audio.
        if t is None and onsets:
            try:
                now = float(onsets[-1].t)
            except Exception:
                pass

        bass = float(getattr(audio, 'bass', 0.0) or 0.0)
        mid = float(getattr(audio, 'mid', 0.0) or 0.0)
        treble = float(getattr(audio, 'treble', 0.0) or 0.0)
        raw_energy = bass + mid + treble

        # Energy + slope (unchanged from legacy for director compat)
        alpha = self._energy_alpha
        self._energy = self._energy * (1.0 - alpha) + raw_energy * alpha
        self._energy_history.append((now, self._energy))
        while (self._energy_history
                and (now - self._energy_history[0][0]) > _V2_ENERGY_WINDOW_S):
            self._energy_history.popleft()

        # O(1) equivalent of the linear scan: entries append in
        # increasing-time order, so the oldest (index 0) has the largest
        # `now - t` — if any entry qualifies, the oldest does; if the oldest
        # doesn't, none do.
        energy_2s_ago = self._energy
        if self._energy_history and (now - self._energy_history[0][0]) >= 2.0:
            energy_2s_ago = self._energy_history[0][1]
        self._energy_prev_2s = energy_2s_ago

        # 2026-08-11: bass_n/mid_n/treble_n read audio.bass_det/mid_det/
        # treble_det, not bass/mid/treble -- see BeatGridTracker.update()'s
        # matching comment above and
        # docs/planning/auto-vj-drop-score-redesign-plan-2026-08-11.md.
        # raw_energy above deliberately keeps reading bass/mid/treble --
        # energy_norm was checked separately and found already calibrated.
        # `is None` (not `or`) -- see BeatGridTracker.update()'s comment
        # above for why: bass_det legitimately reads 0.0 during silence.
        _bass_det = getattr(audio, 'bass_det', None)
        _mid_det = getattr(audio, 'mid_det', None)
        _treble_det = getattr(audio, 'treble_det', None)
        bass_det = float(_bass_det) if _bass_det is not None else bass
        mid_det = float(_mid_det) if _mid_det is not None else mid
        treble_det = float(_treble_det) if _treble_det is not None else treble
        a = min(0.35, max(0.005, self._band_alpha))

        def _norm(x: float, mean: float, var: float) -> tuple[float, float, float]:
            mean = mean + a * (x - mean)
            d = x - mean
            var = max(1e-6, var + a * (d * d - var))
            z = (x - mean) / ((var ** 0.5) + 1e-6)
            v = 0.5 + 0.5 * (z / (1.0 + abs(z)))
            return max(0.0, min(1.0, v)), mean, var

        bass_n, self._band_mean_bass, self._band_var_bass = _norm(
            bass_det, self._band_mean_bass, self._band_var_bass
        )
        mid_n, self._band_mean_mid, self._band_var_mid = _norm(
            mid_det, self._band_mean_mid, self._band_var_mid
        )
        treble_n, self._band_mean_treble, self._band_var_treble = _norm(
            treble_det, self._band_mean_treble, self._band_var_treble
        )

        # Spectral flux: broad-spectrum transient event — qualitatively different
        # from energy slope (which captures sustained rise) so weights are additive.
        # 2026-08-09: rescoped to mid+treble only (spectral_flux - bass_flux,
        # both already computed per-frame in analyzer.py and propagated
        # through AudioManager._copy_audio_into) now that bass_flux_norm
        # below is the dedicated bass-transient term -- letting this term
        # keep the bass band too would double-count it, the same shape of
        # bug as the treble double-count fixed earlier today. There's no
        # separate treble_flux computed, so "mid+treble" is expressed as the
        # broadband residual after removing bass's contribution, not a
        # literal third per-band signal.
        flux = float(getattr(audio, 'spectral_flux', 0.0) or 0.0)
        bass_flux_raw = float(getattr(audio, 'bass_flux', 0.0) or 0.0)
        mid_treble_flux = max(0.0, flux - bass_flux_raw)
        self._flux_smooth = self._flux_smooth * 0.75 + mid_treble_flux * 0.25
        flux_norm = self._flux_smooth / (self._flux_smooth + 0.10)

        # New 2026-08-09: dedicated bass-transient term -- "one big bass hit
        # after next-to-no-bass should hit like a freight train as fast as
        # possible" (owner). Fast-attack/slower-release, not the symmetric
        # EMA flux_smooth uses above -- see _bass_flux_fast's field comment.
        # Starting normalization constant (0.05, half of flux_norm's 0.10,
        # since bass_flux is restricted to fewer FFT bins than full-spectrum
        # flux and runs smaller in raw magnitude) -- provisional, pending
        # section 4d's marathon-week reweight.
        if bass_flux_raw > self._bass_flux_fast:
            self._bass_flux_fast = self._bass_flux_fast * 0.4 + bass_flux_raw * 0.6
        else:
            self._bass_flux_fast = self._bass_flux_fast * 0.85 + bass_flux_raw * 0.15
        bass_flux_norm = self._bass_flux_fast / (self._bass_flux_fast + 0.05)

        energy_slope = self._energy - self._energy_prev_2s
        slope_pos = max(0.0, energy_slope)
        energy_norm = self._energy / (self._energy + 1.0)
        slope_norm = slope_pos / (slope_pos + 0.12)
        # 2026-08-09: rebalanced toward bass (0.45/0.30/0.25 -> 0.7/0.2/0.1)
        # -- see docs/planning/
        # auto-vj-director-detector-refinement-plan-2026-08-09.md section 4a.
        # 2026-08-18: reverted to 0.45/0.30/0.25 (drop-score redesign plan
        # § 4c, owner-decided). The 08-09 tilt toward bass was compensating
        # for the wrong lever -- "wanting bass to matter more" is now solved
        # structurally by the trigger/sustain split below (drop_sustain is a
        # *product* with bass load-bearing by construction, audit F9), so
        # band_blend goes back to being a balanced band-activity blend.
        band_blend = min(1.0, max(0.0, bass_n * 0.45 + mid_n * 0.30 + treble_n * 0.25))
        # 2026-08-10: bass-gated reweight. A real session (favorites/b)
        # surfaced a 0.54 drop_score during a breakdown that was just piano
        # chords + vocals -- zero drums/bass. Root cause: band_blend and
        # bass_flux_norm were the only two terms requiring any bass
        # presence, and only carried 0.40 combined weight; the other three
        # (energy_norm/slope_norm/flux_norm) are genre-agnostic loudness/
        # transient signals that a rising piano+vocal passage satisfies
        # just fine on their own -- slope_norm alone (the prior single
        # largest term at 0.35) got most of the way to 0.54 unassisted.
        # Owner's fix, agreed after discussion: cut slope_norm and
        # flux_norm hard, move the freed weight into band_blend and
        # bass_flux_norm so bass presence becomes load-bearing by
        # construction. Consequence, worth knowing: the maximum possible
        # drop_score with zero bass content is now energy_norm(1.0)*0.15 +
        # slope_norm(1.0)*0.15 + flux_norm(1.0)*0.05 = 0.35 -- below every
        # mood profile's drop_timeout_score_floor (rebooted the same day,
        # see auto_vj.py's _MOOD_PROFILES), so a rhythm-free moment can no
        # longer fire a drop via any path. See docs/adr/vj-system.md
        # "Drop Score Bass-Gated Reweight".
        #
        # 2026-08-11: energy_norm <-> band_blend swap (0.15/0.30 -> 0.30/0.15),
        # owner call after simulating both against two real sessions
        # (favorites/e, 97 real drop_fire events; library/b, 484). Root
        # problem the swap responds to: band_blend's z-score baseline
        # "catches up" to sustained loud bass within ~5-7s (verified via a
        # synthetic constant-input test the same week), fading toward
        # neutral even though the true level never changed -- so a real,
        # unchanging drop was scored *less* drop-like the longer it held.
        # energy_norm (a plain EMA of raw bass+mid+treble, not adaptively
        # normalized) doesn't have that decay, making it a more stable
        # signal for "is this still loud" once weighted higher. Simulated
        # effect, reproduced on both sessions: real drop_fire events clear
        # the raver/normie score floors measurably more often (library/b:
        # 380->437 of 484 at the 0.60 floor); a small, known regression on
        # a rare bass-free-loud-breakdown proxy (11/72198 rows in
        # library/b) was accepted as a real but minor trade, since two
        # gating variants tried against it either didn't help (bass_flux_
        # norm's slow-release EMA defeats a max()-based gate) or overcorrected
        # into a worse regression on real drops (gating on band_blend alone
        # just re-imports its own decay bug). The bass-gated invariant from
        # 2026-08-10 still holds under the new weights, just with a smaller
        # margin: maximum possible drop_score with zero bass content is now
        # energy_norm(1.0)*0.30 + slope_norm(1.0)*0.15 + flux_norm(1.0)*0.05
        # = 0.50 -- still below every mood profile's drop_timeout_score_floor
        # (raver's 0.60, the lowest), but the margin shrank from 0.25 (0.35
        # vs 0.60, prior formula) to 0.10 (0.50 vs 0.60). Still safe, but
        # worth re-checking if the floors themselves are ever loosened.
        # See docs/adr/vj-system.md
        # "Recommender centroid_fit Weight Cut..." sibling entry and the
        # dedicated drop_score entry for the full simulation writeup --
        # band_blend itself is flagged there as a likely elimination
        # candidate, pending what (if anything) replaces its "is there
        # bass" role.
        #
        # Prior (5-term, 2026-08-10 bass-gated reweight):
        #   energy_norm*0.15 + slope_norm*0.15 + band_blend*0.30 + flux_norm*0.05 + bass_flux_norm*0.35
        # Prior (5-term, 2026-08-09 bass_flux_norm addition):
        #   energy_norm*0.15 + slope_norm*0.35 + band_blend*0.15 + flux_norm*0.10 + bass_flux_norm*0.25
        # Prior (4-term, 2026-08-09 treble-double-count fix):
        #   energy_norm*0.25 + slope_norm*0.409 + band_blend*0.182 + flux_norm*0.159
        self._drop_score = min(1.0, max(0.0,
            energy_norm * 0.30
            + slope_norm * 0.15
            + band_blend * 0.15
            + flux_norm * 0.05
            + bass_flux_norm * 0.35
        ))

        # ---- Trigger/sustain split (2026-08-18) ------------------------
        # Computed alongside the legacy composite above, never replacing
        # it — the director chooses which to consume (drop_signal_engine).
        # See the _V2_BASS_LEVEL_* constants block for the full design.
        dt_eff = max(1e-4, float(dt))
        level_raw = float(getattr(audio, 'bass_level_raw', 0.0) or 0.0)

        # Fast level EMA (time-based alpha — dt-independent, audit F7).
        a_fast = 1.0 - np.exp(-dt_eff / _V2_BASS_LEVEL_FAST_TAU_S)
        self._bass_level_fast += a_fast * (level_raw - self._bass_level_fast)

        # Ring write at ~20 Hz of the fast level (the fast EMA, not the raw
        # per-frame value, so ring percentiles describe the same signal the
        # normalization consumes).
        self._bass_level_ring_t_acc += dt_eff
        ring_step = 1.0 / _V2_BASS_LEVEL_RING_RATE
        while self._bass_level_ring_t_acc >= ring_step:
            self._bass_level_ring_t_acc -= ring_step
            self._bass_level_ring[self._bass_level_ring_idx] = self._bass_level_fast
            self._bass_level_ring_idx = (
                (self._bass_level_ring_idx + 1) % len(self._bass_level_ring)
            )
            self._bass_level_ring_filled = min(
                len(self._bass_level_ring), self._bass_level_ring_filled + 1
            )

        # Percentile reference refresh (cheap: ~1800 floats every 0.25 s).
        if (now - self._bass_level_pct_t) >= _V2_BASS_LEVEL_PCT_REFRESH_S \
                and self._bass_level_ring_filled >= int(_V2_BASS_LEVEL_RING_RATE * 2):
            self._bass_level_pct_t = now
            valid = self._bass_level_ring[: self._bass_level_ring_filled]
            self._bass_level_ref_lo = float(np.percentile(valid, _V2_BASS_LEVEL_REF_LO_PCT))
            self._bass_level_ref_hi = float(np.percentile(valid, _V2_BASS_LEVEL_REF_HI_PCT))

        ref_span = max(1e-3, self._bass_level_ref_hi - self._bass_level_ref_lo)

        def _level_norm(x: float) -> float:
            return float(np.clip((x - self._bass_level_ref_lo) / ref_span, 0.0, 1.0))

        self._bass_level_norm_value = _level_norm(self._bass_level_fast)

        # bass_was_suppressed: 1 − normalized recent max, over a long
        # bars-window OR a ~1-bar short window (audit F4 — buildups often
        # keep the kick until the final bars; the short window catches the
        # pre-drop gap). Windowed reads come straight off the ring.
        beat_s = 60.0 / self._bpm if self._bpm > 0.0 else 0.47  # ~128 BPM fallback
        long_n = int(min(
            self._bass_level_ring_filled,
            max(1, _V2_BASS_SUPP_WINDOW_BARS * 4.0 * beat_s * _V2_BASS_LEVEL_RING_RATE),
        ))
        short_n = int(min(
            self._bass_level_ring_filled,
            max(1, _V2_BASS_SUPP_SHORT_BARS * 4.0 * beat_s * _V2_BASS_LEVEL_RING_RATE),
        ))
        if self._bass_level_ring_filled > 0:
            idx = self._bass_level_ring_idx
            ring = self._bass_level_ring
            def _recent_max(n: int) -> float:
                if n <= 0:
                    return 0.0
                start = idx - n
                if start >= 0:
                    return float(ring[start:idx].max()) if idx > start else 0.0
                tail = ring[start % len(ring):]
                head = ring[:idx]
                pieces = [p for p in (tail, head) if len(p)]
                return float(max(p.max() for p in pieces)) if pieces else 0.0
            supp_long = 1.0 - _level_norm(_recent_max(long_n))
            supp_short = 1.0 - _level_norm(_recent_max(short_n))
            self._bass_suppressed_value = max(supp_long, supp_short)
        else:
            self._bass_suppressed_value = 0.0

        # Mid+treble residual flux — trigger (fast asymmetric) and sustain
        # (bar-scale symmetric) trackers, both x/(x+c)-bounded (audit F3).
        residual = max(0.0, flux - bass_flux_raw)
        if residual > self._midtreb_fast:
            a_mt = 1.0 - np.exp(-dt_eff / _V2_MIDTREB_FAST_ATTACK_TAU_S)
        else:
            a_mt = 1.0 - np.exp(-dt_eff / _V2_MIDTREB_FAST_RELEASE_TAU_S)
        self._midtreb_fast += a_mt * (residual - self._midtreb_fast)
        a_busy = 1.0 - np.exp(-dt_eff / _V2_MIDTREB_BUSY_TAU_S)
        self._midtreb_busy += a_busy * (residual - self._midtreb_busy)
        midtreb_fast_norm = self._midtreb_fast / (self._midtreb_fast + _V2_MIDTREB_FLUX_NORM_C)
        midtreb_busy_norm = self._midtreb_busy / (self._midtreb_busy + _V2_MIDTREB_FLUX_NORM_C)

        # The two signals (plan § 4a formula with the audit's corrections;
        # slope stays influence-not-gate — never re-promote it).
        self._impact_novelty = float(np.clip(
            bass_flux_norm
            * midtreb_fast_norm
            * (0.5 + 0.5 * self._bass_suppressed_value)
            * (0.8 + 0.4 * slope_norm),
            0.0, 1.0,
        ))
        self._drop_sustain = float(np.clip(
            self._bass_level_norm_value
            * (_V2_SUSTAIN_BUSY_FLOOR + (1.0 - _V2_SUSTAIN_BUSY_FLOOR) * midtreb_busy_norm),
            0.0, 1.0,
        ))

        # P4: push onset events into internal 100 Hz envelope
        self._is_beat = False
        self._is_downbeat = False

        if onsets:
            for ev in onsets:
                ev_t = float(ev.t)
                ev_strength = float(getattr(ev, 'strength', 1.0))
                ev_band_weight = float(getattr(ev, 'band_weight', 1.0))
                self._last_onset_t = ev_t
                # Advance envelope time to ev_t, then pulse
                self._advance_envelope(ev_t)
                self._pulse_envelope(ev_strength, ev_t)
                # P5: try to absorb onset into phase oscillator
                self._absorb_onset(ev_t, ev_strength, ev_band_weight)
        # E5: always advance to now (onset ticks used to stop at the last onset).
        self._advance_envelope(now)

        # Reset tempo lock after sustained silence/paused source so the next
        # song starts from a clean state instead of inheriting stale BPM.
        if self._bpm > 0.0 and (now - self._last_onset_t) >= self._silence_reset_s:
            self._reset_tempo_lock()

        # 2026-08-17: tap-trust window expiry (plan § 4.5) -- restore the
        # saved profile prior exactly and drop the primed-confidence
        # floor. No permanent state change survives the window.
        if self._tap_saved_prior is not None and now >= self._tap_prime_until_t:
            self._prior_mu, self._prior_sigma = self._tap_saved_prior
            self._tap_saved_prior = None
            self._tap_prime_bpm = 0.0
            self._primed_confidence = 0.0
            self._tempo_hold_until_t = -1e9
            self._recompute_prior_array()

        # P4: re-estimate tempo periodically
        self._acf_frame_count += 1
        if self._acf_frame_count >= _V2_ACF_INTERVAL:
            self._acf_frame_count = 0
            self._estimate_tempo_acf()
            self._acf_cycle_count += 1
            if self.cycle_log_hook is not None:
                try:
                    self.cycle_log_hook(self._cycle_log_snapshot(now))
                except Exception:  # noqa: BLE001 — a logging consumer must never break tracking
                    pass

        # P5: advance phase oscillator by audio-time delta when available.
        phase_dt = max(0.0, float(dt))
        if self._phase_last_t > 0.0 and now > self._phase_last_t:
            phase_dt = now - self._phase_last_t
        phase_dt = min(max(0.0, phase_dt), max(0.01, self._audio_dt_max))
        self._advance_phase(phase_dt, now)
        self._beat_phase = self._phase
        self._phase_last_t = now
        self._last_t = now

    def _reset_tempo_lock(self) -> None:
        """Clear tempo lock and candidate state after sustained silence.

        Does not touch _bpm_min/_bpm_max/_acf_bpms/_acf_prior: since
        set_profile() no longer narrows the search range (P0-A), there is
        no stale range left for a reset to restore -- the ACF always
        searches the full configured range.
        """
        self._bpm = 0.0
        self._confidence = 0.0
        self._phase_confidence = 0.0
        self._acf_confidence = 0.0
        self._kick_evidence_smooth = 0.0
        self._phase = 0.0
        self._beat_phase = 0.0
        self._candidate_history.clear()
        self._long_candidate_history.clear()
        self._long_candidate_history_short.clear()
        self._long_candidate_history_medium.clear()
        self._long_candidate_spread = 0.0
        self._long_candidate_median = 0.0
        self._acf_interpolation_delta_bpm = 0.0
        self._lock_band_candidate_analytical = 0.0
        self._lock_band_candidate_empirical = 0.0
        self._coherence_hit_weight.clear()
        self._coherence_total_weight.clear()
        self._beat_position_map.clear()
        self._last_downbeat_confidence = 0.0
        self._tempo_hold_until_t = -1e9
        self._phase_last_t = -1e9
        self._top_candidates = []
        # 2026-08-17 round-three close-out state (transient per-lock
        # values only -- cumulative engagement counters stay, same
        # convention as the persistence counters above).
        self._persistence_spread_limit = 0.0
        self._long_candidate_eval_t = -1e9
        self._cold_start_cycles_left = 0
        self._lock_anchor_bpm = 0.0
        self._bars_since_lock = 0
        self._phase_err_buf.clear()
        # A silence reset ends any live tap-trust window and restores the
        # saved profile prior -- the next track is a fresh measurement,
        # not the tapped one.
        if self._tap_saved_prior is not None:
            self._prior_mu, self._prior_sigma = self._tap_saved_prior
            self._tap_saved_prior = None
            self._recompute_prior_array()
        self._tap_prime_until_t = -1e9
        self._tap_prime_bpm = 0.0
        self._primed_confidence = 0.0

    def _append_beat_position(self, t: float) -> None:
        """Append a beat timestamp to the short rolling beat-position map."""
        if not np.isfinite(t):
            return
        if self._beat_position_map and self._bpm > 0.0:
            expected = 60.0 / max(1e-6, self._bpm)
            min_sep = expected * 0.45
            if (t - self._beat_position_map[-1]) < min_sep:
                return
        self._beat_position_map.append(float(t))

    def _analysis_region_consistency(self, bpm_candidate: float) -> float:
        """Return a 0..1 consistency score for recent beat positions."""
        if bpm_candidate <= 0.0:
            return 0.0
        if len(self._beat_position_map) < max(3, self._analysis_region_min_beats):
            return 0.0

        expected = 60.0 / max(1e-6, bpm_candidate)
        tol = max(0.05, self._analysis_region_tol)
        positions = list(self._beat_position_map)
        iois: list[float] = []
        prev = positions[0]
        for x in positions[1:]:
            d = x - prev
            if d > 1e-6:
                iois.append(d)
            prev = x
        if len(iois) < max(2, self._analysis_region_min_beats - 1):
            return 0.0

        def _point(ioi: float) -> float:
            families = (expected, expected * 0.5, expected * 2.0)
            best_err = 1e9
            for fam in families:
                err = abs(ioi - fam) / max(1e-6, fam)
                if err < best_err:
                    best_err = err
            if best_err >= tol:
                return 0.0
            return max(0.0, 1.0 - best_err / tol)

        pts = [_point(ioi) for ioi in iois]
        return float(sum(pts) / max(1, len(pts)))

    def _beat_position_density(self, now: float) -> float:
        """Fraction (0..1) of expected beat positions actually observed in
        the last 8 beats' worth of lookback.  Split out of
        _compute_downbeat_confidence() so _downbeat_regularity() below can
        share the exact same calc instead of drifting from a copy.
        """
        if self._bpm <= 0.0 or len(self._beat_position_map) < 2:
            return 0.0
        expected = 60.0 / max(1e-6, self._bpm)
        lookback = expected * 8.0
        recent = [t for t in self._beat_position_map if (now - t) <= lookback]
        if len(recent) < 2:
            return 0.0
        observed = len(recent) - 1
        ideal = max(1.0, lookback / max(1e-6, expected))
        return min(1.0, observed / ideal)

    def _compute_downbeat_confidence(self, now: float) -> float:
        """Blend four independent signals for downbeat gating: beat-position
        region consistency, raw phase coherence, ACF tempo-estimate quality,
        and recent on-beat density.

        `coh` (_phase_confidence) and `base` (_acf_confidence) were formerly
        both read from the same self._confidence value, making them
        numerically identical in practice and silently halving the intended
        four-way blend to a three-way one.  They are now two independently
        persisted signals — see the field comments in __init__.

        NOT used as the dbc term in self._confidence's own top-level blend
        (see _downbeat_regularity() below) — this method reads
        self._phase_confidence/self._acf_confidence directly, which would
        make self._confidence partly echo its own recent history every bar
        if fed back in here.
        """
        region = self._analysis_region_consistency(self._bpm)
        coh = float(self._phase_confidence)
        base = float(self._acf_confidence)
        density = self._beat_position_density(now)
        conf = 0.45 * region + 0.30 * coh + 0.15 * base + 0.10 * density
        return float(min(1.0, max(0.0, conf)))

    def _downbeat_regularity(self, now: float) -> float:
        """dbc term for the top-level self._confidence blend (2026-08-14).

        _last_downbeat_confidence can't be reused directly for this: it
        already contains phase_confidence (30%) and acf_confidence (15%)
        internally (see _compute_downbeat_confidence above), and feeding it
        back into self._confidence would make confidence partly echo its
        own recent history every bar rather than reflect fresh evidence.

        This uses only the two _compute_downbeat_confidence() terms that
        never read phase_confidence/acf_confidence -- region consistency
        and on-beat density -- renormalized to sum 1.0 (0.45/0.55 and
        0.10/0.55). Genuinely independent of acf/phase (no loop possible),
        and a real, dynamic signal now that analysis mode (region
        consistency + the beat-position map it depends on) is always on --
        see the WARNING in the analysis-mode field comment block in
        __init__ for why that's no longer optional.
        """
        region_w, density_w = 0.45, 0.10
        region = self._analysis_region_consistency(self._bpm)
        density = self._beat_position_density(now)
        return (region_w * region + density_w * density) / (region_w + density_w)

    # ------------------------------------------------------------------ #
    # P4 — onset envelope management                                        #
    # ------------------------------------------------------------------ #

    def _advance_envelope(self, target_t: float) -> None:
        """Zero-fill the envelope up to (not including) the slot that covers target_t.

        E5: absolute-index clock. Slot k covers [t0 + k/rate, t0 + (k+1)/rate).
        Idempotent for the same target and monotone in time; multiple calls per
        tick (per onset, then to ``now``) write each slot exactly once.
        """
        if self._last_t < 0:
            self._last_t = target_t
        if self._env_t0 is None:
            self._env_t0 = float(target_t)
            self._env_next_idx = 0
            return
        # +1e-6: (k/rate)*rate can land a hair under k in floating point and
        # would otherwise leave slot k-1 unwritten -- with pulses then dropped
        # on alternate slots (half-tempo reads in the synthetic tests).
        want = int((float(target_t) - self._env_t0) * _V2_ENV_RATE + 1e-6)
        self._advance_env_to_index(want)

    def _advance_env_to_index(self, want: int) -> None:
        while self._env_next_idx < want:
            self._env_buf[self._env_write_idx] = 0.0
            self._env_write_idx = (self._env_write_idx + 1) % self._env_len
            if self._env_write_idx == 0:
                self._env_filled = True
            self._env_next_idx += 1

    def _pulse_envelope(self, strength: float, t: float = 0.0) -> None:
        """Write an onset pulse at the current write position and advance.

        Advancing the write index prevents the next _advance_envelope call
        from overwriting this pulse with zero-fill.

        2026-08-17 (round three close-out, audit menu #6): the written
        pulse is log-compressed -- ``1 + log1p(strength - 1)`` for the
        MAD-z strengths (always >= 1) the analyzer emits. Strengths are
        unbounded z-scores, and a single freak transient (a dropout
        click, a needle hit) could otherwise dominate the zero-mean ACF
        for the entire 8 s envelope window. Compression keeps ordinary
        strong-vs-weak ordering (1.0 -> 1.0, 3 -> ~1.7, 10 -> ~3.2)
        while capping any one event's leverage.

        2026-08-17, later still: records (t, raw, compressed) into
        _onset_strength_history for the onset_strength_max_raw/_max_
        compressed properties -- see _V2_ONSET_STRENGTH_WINDOW_S's own
        comment for why. ``t`` defaults to 0.0 for any caller that still
        passes strength-only (harmless: the row just prunes on the next
        real-timestamped call, same as an entry from the start of a
        session).
        """
        s = float(strength)
        if s > 1.0:
            s = 1.0 + float(np.log1p(s - 1.0))
        # E5: write the pulse into the slot that covers its timestamp. The slot
        # is written (zero-filled) first if the clock has not reached it yet, so
        # the pulse lands at the right time and later zero-fill never clobbers
        # it; a pulse into an already-written slot merges by max().
        if self._env_t0 is None:
            self._advance_envelope(float(t))
        # Nearest slot, not floor: onset timestamps that sit on a slot boundary
        # (beat periods that are integer multiples of 10 ms) otherwise alternate
        # between neighbouring slots in floating point, smearing the ACF peak.
        slot = int(round((float(t) - self._env_t0) * _V2_ENV_RATE))
        # Callers that pass no timestamp (t == 0.0, the documented legacy form)
        # or a stale one (more than half a second behind the clock) get the old
        # behaviour: the pulse lands in the newest slot. Real onsets arrive
        # within the current tick and land in the slot covering their time.
        if float(t) <= 0.0 or slot < self._env_next_idx - int(0.5 * _V2_ENV_RATE):
            slot = max(0, self._env_next_idx - 1)
        if slot >= self._env_next_idx:
            self._advance_env_to_index(slot + 1)   # writes through `slot`, index-exact
        back = self._env_next_idx - 1 - slot                                  # 0 = the newest slot
        if 0 <= back < self._env_len:
            idx = (self._env_write_idx - 1 - back) % self._env_len
            self._env_buf[idx] = max(self._env_buf[idx], s)

        self._onset_strength_history.append((float(t), float(strength), s))
        while (self._onset_strength_history
                and (t - self._onset_strength_history[0][0]) > _V2_ONSET_STRENGTH_WINDOW_S):
            self._onset_strength_history.popleft()

    def _get_envelope(self) -> np.ndarray:
        """Return the envelope as a contiguous array (oldest → newest)."""
        if self._env_filled:
            # Unroll the ring so index 0 is the oldest sample
            idx = self._env_write_idx
            return np.concatenate([
                self._env_buf[idx:],
                self._env_buf[:idx],
            ])
        return self._env_buf[:self._env_write_idx].copy()

    # ------------------------------------------------------------------ #
    # P4 — autocorrelation tempo estimation                                 #
    # ------------------------------------------------------------------ #

    def _acf_rival_score(
        self,
        score: np.ndarray,
        bpms: np.ndarray,
        best_bpm: float,
    ) -> float:
        """Strongest ACF score that is NOT harmonically related to `best_bpm`.

        Used as the rival in the peak-ratio confidence calculation in
        ``_estimate_tempo_acf()``. The comb filter there sums correlation
        at 2x/3x/4x lag multiples of every candidate, which means a lag
        that is itself a near-integer multiple or divisor of the winning
        lag (2x, 3x, 4x, or their reciprocals, within
        ``_V2_HARMONIC_CONF_TOL``) will score highly *because* the true
        pulse is clean and regular -- that is the comb filter agreeing
        with itself, not a genuinely competing tempo. Excluding those lags
        means only an unrelated, independently periodic rival can still
        suppress confidence.
        """
        if best_bpm <= 0.0 or len(bpms) == 0:
            return self._acf_score_floor
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = np.where(bpms > 1e-6, bpms / best_bpm, 0.0)
        ratio_norm = np.where(ratio < 1.0, np.where(ratio > 1e-9, 1.0 / ratio, 0.0), ratio)
        nearest_h = np.round(ratio_norm)
        harmonic_mask = (
            (nearest_h >= 1.0) & (nearest_h <= float(_V2_COMB_HARMONICS))
            & (np.abs(ratio_norm - nearest_h) <= _V2_HARMONIC_CONF_TOL * nearest_h)
        )
        rival_mask = ~harmonic_mask
        if not np.any(rival_mask):
            return self._acf_score_floor
        return float(np.max(score[rival_mask]))

    def _effective_tactus_ratio(self) -> float:
        """Return tactus_preference_ratio, tightened by low kick_regularity.

        2026-08-13 (kr/dbc option B). Interpolates between the configured
        baseline (at ``kick_regularity == 1.0``, e.g. classic four-on-the-
        floor material -- unchanged from the validated default) and
        ``baseline + _TACTUS_KICK_REGULARITY_SPREAD`` (at
        ``kick_regularity == 0.0``, sparse/irregular kicks -- stricter,
        less eager to fold). Never makes folding *more* eager than the
        baseline. ``self._kick_regularity`` defaults to and persists at
        ``0.0`` (most conservative) whenever the caller never supplies a
        reading, so a caller that doesn't wire this through gets the
        strictest behavior rather than silently getting the most
        permissive one. See ``_TACTUS_KICK_REGULARITY_SPREAD``.
        """
        kr = max(0.0, min(1.0, self._kick_regularity))
        return min(1.0, self._tactus_preference_ratio + (1.0 - kr) * _TACTUS_KICK_REGULARITY_SPREAD)

    def _tactus_fold_accepted(
        self,
        cand_score: float,
        best_score: float,
        cur_bpm: float,
        cand_bpm: float,
    ) -> bool:
        """Return True if the tactus descent loop should fold to `cand_bpm`.

        Two conditions, both required: the candidate's raw comb-filter
        score must clear the effective tactus ratio (baseline
        ``tactus_preference_ratio``, tightened by low ``kick_regularity``
        -- see ``_effective_tactus_ratio()``) of the current pick's score,
        and (2026-08-13) the candidate must not be a measurably worse fit
        for the recently observed beat spacing than the lane it would
        replace, via ``_analysis_region_consistency`` -- the same
        beat-grid self-consistency signal ``downbeat_confidence`` and the
        large-jump guard already use. Raw comb-filter score alone can't
        distinguish "this candidate's period is a genuinely better musical
        pulse" from "this candidate's period happens to score well but
        doesn't actually land on the track's real accents";
        region-consistency checks against actual recent onset timing
        rather than just the ACF's own windowed periodicity estimate.
        Inert before enough beat-position history exists to score the
        current lane (``_analysis_region_consistency`` returns ``0.0``
        with no history, so the guard never fires pre-lock). See
        docs/adr/vj-system.md.

        2026-08-14: every outcome increments a session-cumulative counter
        (``_tactus_score_reject_count``/``_tactus_region_reject_count``/
        ``_tactus_fold_accepted_count``) so real session data can show
        whether/how often each guard actually engages, not just whether
        the code path exists -- see the matching public properties below.

        2026-08-14, later still: counters show *how often* each outcome
        happens, but not *which* fold it was -- owner asked to log the
        actual decisions, not just tallies. Every call now also caches a
        compact description of this specific evaluation (cur_bpm ->
        cand_bpm, outcome) via ``last_tactus_fold`` below, overwriting the
        previous one -- last decision this cycle, same "most recent wins"
        convention as region_consistency/downbeat_regularity.
        """
        if cand_score < best_score * self._effective_tactus_ratio():
            self._tactus_score_reject_count += 1
            self._last_tactus_fold = f'score_reject:{cur_bpm:.2f}->{cand_bpm:.2f}'
            return False
        cur_region = self._analysis_region_consistency(cur_bpm)
        if cur_region <= 0.0:
            self._tactus_fold_accepted_count += 1
            self._last_tactus_fold = f'accepted:{cur_bpm:.2f}->{cand_bpm:.2f}'
            return True
        cand_region = self._analysis_region_consistency(cand_bpm)
        if cand_region < cur_region * _TACTUS_REGION_GUARD_RATIO:
            self._tactus_region_reject_count += 1
            self._last_tactus_fold = f'region_reject:{cur_bpm:.2f}->{cand_bpm:.2f}'
            return False
        self._tactus_fold_accepted_count += 1
        self._last_tactus_fold = f'accepted:{cur_bpm:.2f}->{cand_bpm:.2f}'
        return True

    def _estimate_tempo_acf(self) -> None:
        """Re-estimate BPM via autocorrelation of the onset envelope.

        Steps:
        1. Zero-mean the envelope.
        2. Compute autocorrelation across lags in the BPM range.
        3. Weight each lag by the perceptual tempo prior.
        4. Pick the top peak; apply octave-down preference.
        5. EMA-smooth the BPM estimate.
        """
        if self._acf_lags is None or self._acf_bpms is None or self._acf_prior is None:
            return

        env = self._get_envelope()
        if len(env) < self._acf_lag_max + 10:
            return   # not enough data yet

        # Require at least 8 onset pulses for a reliable ACF; fewer onsets
        # produce noisy estimates that can seed the EMA in the wrong direction.
        n_pulses = int(np.sum(env > 0))
        if n_pulses < 8:
            return

        env_zm = env - env.mean()
        norm = float(np.dot(env_zm, env_zm)) + 1e-9

        lag_min = self._acf_lag_min
        lag_max = min(self._acf_lag_max, len(env) - 1)
        n_lags = lag_max - lag_min + 1
        if n_lags < 2:
            return

        # Manual lag loop is comparable in speed to np.correlate for small windows
        #
        # 2026-08-17 (round three close-out, audit menu #5): each lag's
        # correlation is scaled by an unbiased-ACF length correction. The
        # raw sum has (n - lag) terms, so longer lags (slower tempos)
        # summed fewer products and carried a structural few-percent tilt
        # toward faster lanes on every single estimate.
        #
        # 2026-08-17, later still: the textbook n/(n-lag) form measurably
        # increased confidence noise and lock-toggle frequency, worst
        # under harmonic ambiguity -- the training-house-01 c-vs-d
        # regression (10x more within-track toggles on the same 32-track
        # list) traced in real part to this. A controlled A/B (isolated
        # in-memory beat_grid.py copies, synthetic click tracks with a
        # 4:3 competing distractor -- the same ratio family behind
        # Squabble Up/Velvet After Dark/Habits Stay High) confirmed it
        # directly: current 18 toggles vs. 4 for sqrt((n/(n-lag))) at the
        # same two tempos, while a clean slow-tempo check (72 BPM, no
        # distractor) showed the sqrt form still converges correctly and
        # keeps a real (non-zero) correction at the low end where the
        # original bias lives -- unlike a capped variant, which tested as
        # functionally reverted right where the bias is worst. Owner:
        # "go ahead and land #2." sqrt dampens non-linearly, pulling back
        # hardest exactly where the raw ratio is largest, rather than a
        # flat fraction of it. Keeps magnitudes on the same scale as
        # before at lag 0, so _acf_score_floor and every ratio-based
        # consumer (peak-ratio confidence, dominance/tactus/density
        # ratios) keep their tuned meanings.
        acf = np.empty(n_lags, dtype=np.float32)
        n_total = len(env_zm)
        for i in range(n_lags):
            lag = lag_min + i
            acf[i] = (
                float(np.dot(env_zm[lag:], env_zm[:n_total - lag])) / norm
                * (n_total / max(1, n_total - lag)) ** 0.5
            )

        prior = self._acf_prior[:n_lags]
        acf_pos = np.clip(acf, 0.0, None)

        # Aubio-style harmonic comb-filter scoring: a true tempo should have
        # correlation peaks at its fundamental period AND at integer multiples
        # (2x, 3x, 4x lag). Summing those harmonics disambiguates metric
        # confusion (e.g. dotted-half lag of 164 BPM at 109 BPM) because the
        # true tempo's harmonic stack is consistently stronger than a single
        # ambiguous peak.
        env_len_total = len(env_zm)
        comb_score = acf_pos.copy()
        for h in range(2, _V2_COMB_HARMONICS + 1):
            for i in range(n_lags):
                lag = (lag_min + i) * h
                if lag >= env_len_total:
                    break
                # Lag-i in acf is for lag (lag_min + i); harmonic lag h*lag
                # is outside the precomputed acf array, so compute on the fly.
                # Same sqrt-dampened unbiased-length correction as the
                # base-lag loop above (2026-08-17, later still -- see its
                # own comment) so harmonic contributions are comparable
                # across lags too.
                acf_h = (
                    float(np.dot(env_zm[lag:], env_zm[:env_len_total - lag])) / norm
                    * (env_len_total / max(1, env_len_total - lag)) ** 0.5
                )
                if acf_h > 0.0:
                    comb_score[i] += acf_h / h   # diminishing harmonic weight

        # 2026-09-02 (v3 phase 1): retain the raw observation for the
        # HMM engine (BeatTrackerV3 below) — pure telemetry retention,
        # zero effect on v2's own flow. The comb score IS the
        # observation; everything after this line is v2's decision
        # layer, which v3 replaces wholesale.
        self._last_acf_observation = (
            self._acf_bpms[:n_lags], comb_score.copy(), self._acf_cycle_count)

        score = comb_score * prior
        self._last_acf_score = score  # v3 phase 1: post-prior observation option (read-only)

        # 2026-08-17 (round three close-out, plan § 4.2): genre-fit-weighted
        # candidate scoring, consulted ONLY when the previous cycle's ACF
        # confidence was already below the gate -- i.e. exactly when the
        # primary evidence is ambiguous and a second, tempo-independent
        # signal is worth anything. See _V2_GENRE_EVIDENCE_GATE_CONFIDENCE's
        # field comment for the full design; the evidence itself arrives
        # via set_genre_tempo_evidence() and is built exclusively from
        # tempo-independent recommender terms (auto_vj.py excludes
        # tempo_fit/top_cand_fit/onset_fit/kick_regularity_fit).
        if (
            self._genre_evidence_enabled
            and self._genre_evidence_weight > 0.0
            and self._last_t < self._genre_evidence_until_t
            and self._acf_confidence < self._genre_evidence_gate_confidence
        ):
            log_bpms = np.log2(self._acf_bpms[:n_lags])
            d = (log_bpms - float(np.log2(max(1.0, self._genre_evidence_mu)))) / self._genre_evidence_sigma
            boost = 1.0 + (
                _V2_GENRE_EVIDENCE_MAX_BOOST
                * self._genre_evidence_weight
                * np.exp(-0.5 * d * d)
            )
            score = score * boost.astype(np.float32)
            self._genre_evidence_applied_count += 1

        if not np.isfinite(score).all() or score.max() < self._acf_score_floor:
            return   # no clear periodicity; avoid argmax(near-zero) = lag_min

        peak_idx = int(np.argmax(score))
        best_bpm = float(self._acf_bpms[peak_idx])

        # Prevent prior-weighted picks from overriding clearly stronger raw
        # periodicity evidence. This helps slow sparse material where weighted
        # selection may drift into a faster subdivision lane.
        raw_idx = int(np.argmax(comb_score))
        raw_bpm = float(self._acf_bpms[raw_idx])
        if (abs(raw_bpm - best_bpm) >= 8.0
                and float(comb_score[raw_idx]) >= float(comb_score[peak_idx]) * _V2_RAW_DOMINANCE_RATIO):
            peak_idx = raw_idx
            best_bpm = raw_bpm

        # Tactus (octave-down) preference, applied iteratively. On dense
        # electronic material the raw onset envelope often has the strongest
        # periodicity at sub-beat rates (hi-hats, percussion), pulling the
        # lock toward ~150 BPM even when the musical pulse is 75-100 BPM.
        # We descend the period stack: if a 0.5x candidate has comb-filter
        # score >= tactus_preference_ratio of the current pick, switch to it,
        # then check again from the new pick. This catches multi-step traps
        # (e.g. 192 -> 96 -> 48 collapses to 96 when 48 is below bpm_min).
        # 0.5x is checked first because every-other-beat is the most
        # musically reliable signal in 4/4 dance music; 2/3 and 3/4 catch
        # triplet/swing/dotted ambiguity. 2026-08-13: the accept check is
        # now _tactus_fold_accepted() -- see its docstring for the
        # region-consistency guard added that day.
        for _ in range(4):   # bounded descent
            if best_bpm < self._tactus_check_bpm:
                break
            best_score = float(score[peak_idx])
            improved = False
            for factor in (0.5, 2.0 / 3.0, 0.75):
                cand_bpm = best_bpm * factor
                if cand_bpm < self._bpm_min:
                    continue
                cand_lag = int(round(60.0 / cand_bpm * _V2_ENV_RATE))
                cand_idx = cand_lag - lag_min
                if cand_idx < 0 or cand_idx >= n_lags:
                    continue
                cand_score = float(score[cand_idx])
                if not self._tactus_fold_accepted(cand_score, best_score, best_bpm, cand_bpm):
                    continue
                peak_idx = cand_idx
                best_bpm = float(self._acf_bpms[peak_idx])
                improved = True
                break   # restart from new pick
            if not improved:
                break

        # On sparse/slow content the onset density itself is a strong sanity
        # signal: do not stay in a much faster lane unless it is clearly
        # superior in score.
        density_bpm = 60.0 * float(n_pulses) / max(1e-6, self._env_window_s)
        self._last_acf_density_bpm = density_bpm  # v3 phase 4: onset-density channel (read-only retention)
        if density_bpm > 0.0 and best_bpm > density_bpm * _V2_DENSITY_FAST_RATIO:
            base_score = float(score[peak_idx])
            for factor in (0.75, 2.0 / 3.0, 0.5):
                cand_bpm = best_bpm * factor
                if cand_bpm < self._bpm_min:
                    continue
                cand_lag = int(round(60.0 / cand_bpm * _V2_ENV_RATE))
                cand_idx = cand_lag - lag_min
                if cand_idx < 0 or cand_idx >= n_lags:
                    continue
                cand_score = float(score[cand_idx])
                # Accept a slower lane when it is close to onset density and
                # not dramatically worse than the weighted best.
                if (abs(cand_bpm - density_bpm) / max(1e-6, density_bpm) <= 0.35
                        and cand_score >= base_score * _V2_DENSITY_SCORE_RATIO):
                    peak_idx = cand_idx
                    best_bpm = float(self._acf_bpms[peak_idx])
                    break

        # Sub-lag (parabolic) peak interpolation -- proposed in
        # docs/planning/auto-vj-round-three-planning-2026-08-14.md § 6,
        # shipped for an A/B test (owner: "we'll consider my next run the
        # A for this and the one directly after we'll do the B w/that
        # fix"). Root cause this addresses: at _V2_ENV_RATE=100 Hz,
        # BPM = 6000/lag, so d(BPM)/d(lag) = -6000/lag^2 -- the lag grid is
        # coarse at high BPM (3.75 BPM/step at 150 BPM) and fine at low BPM
        # (0.94 BPM/step at 75 BPM). A real session showed ~10 "competing"
        # raw candidates that were actually 10 consecutive integer lags for
        # the SAME underlying periodicity, wandering across a >75 BPM range
        # cycle to cycle purely from grid quantization. Standard technique:
        # fit a parabola through the winning bin and its two neighbors in
        # the same `score` array peak_idx was chosen from, and solve for
        # the true (fractional) peak location. Applied once, after every
        # peak_idx reassignment above (raw-dominance override, tactus
        # fold, density guard) has already settled on a final bin -- does
        # NOT change which bin wins, only refines the reported BPM once
        # one has. self._acf_interpolation_delta_bpm is cached (0.0 when
        # not applied, e.g. at a grid edge) specifically so an A/B
        # comparison can see how much this moved a given cycle's reading,
        # not just the final number. See _DETECTOR_VERSION's own comment.
        pre_interp_bpm = float(self._acf_bpms[peak_idx])
        if self._interpolation_enabled and 0 < peak_idx < n_lags - 1:
            y0 = float(score[peak_idx - 1])
            y1 = float(score[peak_idx])
            y2 = float(score[peak_idx + 1])
            denom = y0 - 2.0 * y1 + y2
            if abs(denom) > 1e-9:
                lag_delta = max(-0.5, min(0.5, 0.5 * (y0 - y2) / denom))
                refined_lag = (lag_min + peak_idx) + lag_delta
                if refined_lag > 0.0:
                    best_bpm = 60.0 * _V2_ENV_RATE / refined_lag
        self._acf_interpolation_delta_bpm = best_bpm - pre_interp_bpm

        # Confidence derived from the ACF itself before any BPM update.
        # If the window is ambiguous, do not let the EMA drift at all.
        #
        # 2026-08-07: the rival used for the peak-ratio excludes lags that
        # are harmonically related to the winning lag -- see
        # _acf_rival_score() for why. Owner-observed live: a house track
        # with very regular kicks scored confidence "crazy low" the whole
        # way through despite locking the right BPM the entire time.
        rival_score = self._acf_rival_score(score, self._acf_bpms[:n_lags], best_bpm)
        acf_peak_ratio = float(score[peak_idx] / (rival_score + 1e-9))
        acf_conf = min(1.0, acf_peak_ratio / 3.0)
        # Persist immediately (independent of whether a BPM update is
        # ultimately accepted below) and refresh the public blend so this
        # signal survives until the next onset instead of being silently
        # discarded by _absorb_onset's per-onset phase-coherence write.
        self._acf_confidence = acf_conf
        # Sparse-evidence EMA (2026-08-14, round three, the morning after,
        # part two): unconditional, same rationale as acf_confidence just
        # above -- must reflect a genuine trend even on cycles where the
        # gate below ultimately rejects the update. See
        # _V2_KICK_EVIDENCE_ALPHA's own comment for why this needs
        # smoothing at all.
        self._kick_evidence_smooth = (
            (1.0 - self._kick_evidence_alpha) * self._kick_evidence_smooth
            + self._kick_evidence_alpha * max(0.0, min(1.0, self._kick_regularity))
        )
        # 2026-08-10: 0.4/0.6 -> 0.5/0.5, same night as _V2_PHASE_TOL's
        # 0.18 -> 0.12 tightening -- owner call, for tonight's session, not
        # yet a settled value pending real acf_confidence/phase_confidence
        # data (both now logged separately -- see _detector_snapshot() in
        # auto_vj.py). Same formula duplicated in _absorb_onset() below.
        #
        # 2026-08-11: 0.5/0.5 -> 0.7/0.3, TEMPORARY, pending a proper fix
        # tomorrow. Real data from a live session showed phase_confidence
        # structurally capped ~0.3-0.4 even during genuinely stable, locked
        # stretches (69% of the session): it's a hit-rate over every onset
        # landing on-beat, and real music generates plenty of legitimately
        # off-beat onsets (hi-hats, syncopation, fills) that a correct lock
        # has no business explaining away. acf_confidence reaches 1.0
        # regularly on the same stable stretches, so the 50/50 blend was
        # dragging overall confidence down for a reason that has nothing to
        # do with lock quality. Real fix (agreed, not built yet): weight
        # phase coherence by onset strength/band -- kick/bass-region onsets
        # should count, hi-hat/fill onsets shouldn't be expected to land on
        # the beat at all, so they shouldn't count against it either. This
        # ratio bump is explicitly a stopgap standing in for that, not a
        # resolution -- owner, on record: "i'm violating my own policy
        # [flag+confirm before detector changes] but it's due to consensus
        # and this is just a temp fix while we work on phase confidence."
        # 2026-08-14: 0.7/0.3 -> 0.8/0.2. The strength/band-weighted phase-
        # coherence rework landed the same day and was validated live: BPM
        # and genre both nailed correctly from the first song, but
        # confidence still read too low. Owner's pre-stated fallback (see
        # the rc.54 commit message) if the rework alone didn't fix
        # discrimination enough was 0.8/0.2, not a revert toward 0.5/0.5 --
        # applying that now rather than a fresh guess.
        # 2026-08-14, later still: three-term blend. 0.8/0.2 ACF/phase felt
        # "kinda hot" on the next live session -- a downbeat-regularity term
        # folded in at 0.2, ACF cut from 0.8 to 0.6 to make room (phase left
        # at 0.2, unchanged). Sums to 1.0. Uses _downbeat_regularity(), NOT
        # _last_downbeat_confidence -- the latter already contains
        # phase_confidence/acf_confidence internally, which would make
        # confidence partly echo its own recent history. See
        # docs/adr/vj-system.md.
        # Downbeat regularity confidence idea & math by Jason. ;D
        # 2026-08-14, later still: weights re-tuned 0.6/0.2/0.2 -> 0.65/0.1/
        # 0.25 -- phase_confidence chronically capped ~0.30 even on locked,
        # correct stretches (confirmed against real session data the same
        # night; see docs/adr/vj-system.md), so its share was trimmed and
        # shifted onto acf_confidence and downbeat_regularity, the two
        # terms actually showing real dynamic range. Root cause of the
        # phase_confidence cap flagged as a separate, still-open
        # investigation -- this is a weight re-tune around it, not a fix.
        self._downbeat_regularity_value = self._downbeat_regularity(self._last_t)
        self._confidence = (
            0.65 * self._acf_confidence
            + 0.1 * self._phase_confidence
            + 0.25 * self._downbeat_regularity_value
        )
        # 2026-08-17 (round three close-out, audit menu #8): cold-start
        # blend guard -- for the first _V2_COLD_START_GUARD_CYCLES ACF
        # cycles after a cold-start acceptance, downbeat_regularity is
        # excluded from the blend (its share given to acf_confidence):
        # that early, regularity only measures the just-established
        # grid's self-consistency, which a WRONG lock satisfies perfectly
        # (see the constant's field comment and the 17:56 incident).
        # Same formula mirrored in _absorb_onset(); the counter only
        # decrements here (once per ACF cycle).
        if self._cold_start_cycles_left > 0:
            self._cold_start_cycles_left -= 1
            self._confidence = (
                0.9 * self._acf_confidence + 0.1 * self._phase_confidence
            )
        if self._last_t < self._tempo_hold_until_t:
            self._confidence = max(self._confidence, self._primed_confidence)
        if self._bpm <= 0.0:
            if acf_conf < self._startup_confidence:
                return
        else:
            if acf_conf < self._min_update_confidence:
                return
            # Sparse-evidence gate (2026-08-14, round three, the morning
            # after, part two): see _V2_MIN_KICK_EVIDENCE's own comment.
            # Holds the current lock rather than chasing a candidate the
            # ACF is technically confident about but the recent audio
            # doesn't have the rhythmic structure to support.
            if self._kick_evidence_smooth < self._min_kick_evidence:
                self._kick_evidence_reject_count += 1
                return

        # 2026-08-14 (the morning after): the hold-skip gate that used to
        # live here (added 2026-08-13, refined same day -- "prevents high-
        # frequency re-locking on steady songs") is removed entirely. Its
        # own logic was backwards for a track-boundary tempo change: it
        # blocked re-evaluation specifically when acf_conf >= 0.45 --
        # strong evidence got blocked, weak evidence is what got through
        # to the rest of the gate stack -- and _tempo_hold_until_t (still
        # refreshed below, still used for the primed_confidence floor
        # above) got refreshed on every accepted update including a
        # max_bpm_step-capped partial step mid-jump. Net effect on a real
        # tempo change: confident evidence about the new tempo repeatedly
        # blocked by the mechanism meant to protect a *stable* lock, real
        # convergence only happening on cycles where confidence happened
        # to dip. Simulated all 20 ordered pairs among {86, 112, 124, 132,
        # 148} BPM (lock 60s, transition 90s): with the gate, 4/20 pairs
        # converged within 90s (tol 3 BPM), most crawling to a final value
        # far short of target; with it removed, 20/20 converged, almost
        # all within 5-9 seconds. See docs/adr/vj-system.md.
        #
        # P5 hardening: require candidate persistence across multiple ACF
        # refreshes so a single noisy frame cannot re-pick a new tempo lane.
        self._candidate_history.append(best_bpm)
        if len(self._candidate_history) < 3:
            return
        candidate_median = float(np.median(np.asarray(self._candidate_history, dtype=np.float32)))
        candidate_spread = float(np.max(np.abs(np.asarray(self._candidate_history, dtype=np.float32) - candidate_median)))
        # 2026-08-17: relative spread limit (see _V2_CANDIDATE_SPREAD_PCT's
        # field comment) -- the flat 4.0 floor keeps low/mid-tempo behavior
        # identical; the pct term only loosens above the ~133 BPM crossover
        # where the lag grid's own quantization step exceeds the flat value.
        candidate_limit = max(
            self._candidate_spread_bpm,
            self._candidate_spread_pct * candidate_median,
        )
        if candidate_spread > candidate_limit:
            return
        best_bpm = candidate_median

        # 2026-08-17: tap-tempo trust window fast path (plan § 4.5). A
        # candidate median matching the operator's confirmed tap (within
        # _V2_TAP_PRIME_BAND_PCT) while the window is live skips the
        # large-jump gate stack and the EMA crawl entirely -- the operator
        # just told us the answer; three agreeing ACF cycles (the short
        # persistence above, retained) is enough corroboration.
        tap_fast_path = (
            self._tap_prime_bpm > 0.0
            and self._last_t < self._tap_prime_until_t
            and abs(best_bpm - self._tap_prime_bpm)
                <= _V2_TAP_PRIME_BAND_PCT * self._tap_prime_bpm
        )

        # P5 hardening: large jumps are rejected unless ACF confidence is
        # strong. This blocks low-confidence lane creep (e.g. 120 -> 150
        # drift) while still allowing true tempo changes to break through.
        #
        # 2026-08-14, later still still: self._long_candidate_history is a
        # SEPARATE, much longer-window version of the persistence check
        # above (candidate_window's default 5 cycles is under a second at
        # ~7.5 Hz; this is large_jump_persistence_cycles, default 25,
        # ~3.3s), appended every cycle regardless of in-/out-of-band, but
        # only consulted here -- gating large jumps specifically against a
        # multi-second wobble the short window can't see. See this
        # constant's own field comment for the incident that motivated it.
        self._long_candidate_history.append(best_bpm)
        self._long_candidate_history_short.append(best_bpm)
        self._long_candidate_history_medium.append(best_bpm)
        dwell_escalated = False
        accepted_large_jump = False
        if self._bpm > 0.0 and not tap_fast_path:
            jump_limit = max(self._lock_band_min, self._bpm * self._lock_band_pct)
            # 2026-08-14, round three: candidate lock-band shapes, logged
            # only -- computed alongside the real jump_limit above on
            # every cycle that reaches this point (self._bpm already
            # established, candidate already cleared the earlier gates)
            # so all three stay directly comparable. See
            # _V2_LOCK_BAND_CANDIDATE_ANALYTICAL_K's own comment.
            self._lock_band_candidate_analytical = (
                _V2_LOCK_BAND_CANDIDATE_ANALYTICAL_K * (self._bpm * self._bpm)
                / (60.0 * _V2_ENV_RATE)
            )
            self._lock_band_candidate_empirical = _V2_LOCK_BAND_CANDIDATE_EMPIRICAL_BPM
            out_of_band = abs(best_bpm - self._bpm) > jump_limit
            # 2026-08-17: minimum lock dwell (plan § 1.2, design sketch
            # option (c)). During the first `bpm_lock_dwell_bars` bars
            # after a lock anchor, an in-band candidate whose CUMULATIVE
            # drift from the anchor exceeds the dwell budget is escalated
            # into the large-jump gate stack below instead of being freely
            # accepted -- closing the accumulating-in-band-nudges gap the
            # lock-band tightenings alone can't (a sequence of
            # individually-legal steps eroding 122 -> 88). A genuine early
            # tempo change still has a path: it just needs the same
            # persistence + confidence evidence a large jump does.
            if (
                not out_of_band
                and self._dwell_bars > 0.0
                and self._lock_anchor_bpm > 0.0
                and self._bars_since_lock < self._dwell_bars
                and abs(best_bpm - self._lock_anchor_bpm)
                    > self._dwell_drift_pct * self._lock_anchor_bpm
            ):
                dwell_escalated = True
                self._dwell_gated_count += 1
            if out_of_band or dwell_escalated:
                # 2026-08-14, round three, the morning after (part three):
                # short/medium candidate windows evaluated here,
                # unconditionally, BEFORE the real gate's own wait/reject
                # returns below -- so they log on every cycle this branch
                # is reached, not just the ones where the real 25-cycle
                # gate happens to also be ready. Same spread<=6.0/
                # agreement<=6.0 criteria as the real gate, just against a
                # shorter window; logged only, never gates anything. See
                # _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT's own
                # comment.
                if len(self._long_candidate_history_short) >= _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT:
                    short_arr = np.asarray(self._long_candidate_history_short, dtype=np.float32)
                    short_median = float(np.median(short_arr))
                    short_spread = float(np.max(np.abs(short_arr - short_median)))
                    # Same max(flat, pct*median) limit as the real gate
                    # below (2026-08-17) so the window-size comparison
                    # stays apples-to-apples.
                    short_limit = max(
                        self._persistence_spread_bpm,
                        self._persistence_spread_pct * short_median,
                    )
                    if short_spread > short_limit or abs(best_bpm - short_median) > short_limit:
                        self._large_jump_persistence_reject_count_short += 1
                    else:
                        self._large_jump_persistence_cleared_count_short += 1
                if len(self._long_candidate_history_medium) >= _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_MEDIUM:
                    medium_arr = np.asarray(self._long_candidate_history_medium, dtype=np.float32)
                    medium_median = float(np.median(medium_arr))
                    medium_spread = float(np.max(np.abs(medium_arr - medium_median)))
                    medium_limit = max(
                        self._persistence_spread_bpm,
                        self._persistence_spread_pct * medium_median,
                    )
                    if medium_spread > medium_limit or abs(best_bpm - medium_median) > medium_limit:
                        self._large_jump_persistence_reject_count_medium += 1
                    else:
                        self._large_jump_persistence_cleared_count_medium += 1
                if len(self._long_candidate_history) < self._large_jump_persistence_cycles:
                    self._large_jump_persistence_wait_count += 1
                    return
                long_arr = np.asarray(self._long_candidate_history, dtype=np.float32)
                long_median = float(np.median(long_arr))
                long_spread = float(np.max(np.abs(long_arr - long_median)))
                self._long_candidate_median = long_median
                self._long_candidate_spread = long_spread
                self._long_candidate_eval_t = self._last_t
                # 2026-08-17: max(flat, pct*median) -- see
                # _V2_PERSISTENCE_SPREAD_PCT's field comment. The flat 6.0
                # floor binds below ~171 BPM (unchanged behavior across
                # every session this round validated); the pct term gives
                # the fast lanes the relative allowance the lag-grid math
                # says they need.
                long_limit = max(
                    self._persistence_spread_bpm,
                    self._persistence_spread_pct * long_median,
                )
                self._persistence_spread_limit = long_limit
                if long_spread > long_limit or abs(best_bpm - long_median) > long_limit:
                    self._large_jump_persistence_reject_count += 1
                    return
                # Cleared the persistence check itself -- the large-jump
                # confidence/region-consistency check right below still
                # has the final say on whether this specific candidate is
                # accepted.
                self._large_jump_persistence_cleared_count += 1
                # Mixxx-inspired constant-region guard, OR'd with the
                # large-jump confidence check above rather than AND'd
                # (2026-08-14, later still). Previously a large jump
                # needed BOTH acf_conf >= large_jump_confidence AND
                # region-consistency against *recent* beat positions --
                # but recent beat positions are necessarily built under
                # the OLD tempo, so a genuinely new tempo (e.g. right
                # after a track change) can never have "recent history
                # consistent with it" until it's already been accepted.
                # That chicken-and-egg made large jumps far harder to
                # accept than the confidence gate alone would suggest --
                # confirmed live (the Juri -> Music Sounds Better With
                # You carry-over: BPM frozen at 83.35, confidence 0.91+,
                # straight through the track change). Now: strong direct
                # ACF confidence is sufficient on its own -- region-
                # consistency can't refute evidence it structurally can't
                # yet have. Region-consistency remains a valid ALTERNATE
                # path for a jump that doesn't clear the confidence bar
                # alone but does fit recent beat-position structure (a
                # subtle, already-in-progress tempo drift). See
                # docs/adr/vj-system.md.
                self._region_consistency_value = self._analysis_region_consistency(best_bpm)
                if (acf_conf < self._large_jump_confidence
                        and self._region_consistency_value < self._analysis_region_confidence_min):
                    return
                accepted_large_jump = True

        # Additional low-BPM guard: when currently in a low lane, do not
        # accept a jump into a fast lane without very strong confidence.
        # Skipped on the tap fast path (2026-08-17): a confirmed human tap
        # outranks the lane heuristic by design.
        if (self._bpm > 0.0 and not tap_fast_path
                and self._bpm <= self._low_bpm_guard and best_bpm >= self._fast_bpm_guard):
            if acf_conf < self._low_bpm_fast_confidence:
                return

        # NOTE: octave-down fold preference is intentionally omitted here.
        # For sparse onset envelopes (typical with noisy detectors), the ACF
        # at the 2× lag (0.5× BPM) is equal to the ACF at the base lag, so
        # a fold preference based on raw ACF would fire almost every time and
        # consistently halve the estimated BPM.  The perceptual prior already
        # provides the necessary bias toward musically-common tempos.  A
        # profile-aware fold preference may be reintroduced in P7 once
        # confidence calibration provides a reliable quality signal.

        # Smooth BPM with slow EMA; start cold from first confident estimate.
        # Cap alpha lower during cold start (ring not yet filled) to prevent
        # early noisy estimates from seeding the EMA in the wrong direction.
        if self._bpm <= 0.0:
            self._bpm = best_bpm
            # 2026-08-17: lock-anchor + cold-start bookkeeping. The dwell
            # gate measures cumulative in-band drift against this anchor
            # for the next `bpm_lock_dwell_bars` bars, and the confidence
            # blend excludes downbeat_regularity for the next
            # _V2_COLD_START_GUARD_CYCLES cycles (see the blend site).
            self._lock_anchor_bpm = self._bpm
            self._bars_since_lock = 0
            self._cold_start_cycles_left = self._cold_start_guard_cycles
        elif tap_fast_path or accepted_large_jump:
            # 2026-08-17: snap, don't crawl. A candidate that cleared the
            # full large-jump path is a 25-cycle-stable median that also
            # cleared the confidence/region gate -- crawling toward it at
            # max_bpm_step per cycle adds nothing but lag, and (worse)
            # interacted badly with the T5 Option A reset below: with the
            # deques freshly cleared, each subsequent crawl step's
            # out-of-band evaluation would stall in the persistence
            # window's warm-up for another ~3.3s. A tap-window match is
            # the operator literally telling us the answer. In-band
            # nudges (the else branch) keep the EMA + step cap unchanged.
            self._bpm = best_bpm
            if tap_fast_path:
                self._tap_prime_accept_count += 1
            # T5 Option A (plan § 8.3/§ 8.4): clear all four candidate
            # deques the moment a large jump is actually accepted, so the
            # newly-locked tempo starts from a clean slate instead of
            # having to outvote leftover contamination from the old lane
            # for the next N cycles (the observed 88.44 -> 93 -> 108
            # creep-back). Removes stale evidence only -- never fabricates
            # new evidence toward acceptance (the cleared deques make the
            # NEXT jump strictly harder, not easier). Cumulative
            # wait/reject/cleared counters deliberately untouched.
            self._candidate_history.clear()
            self._long_candidate_history.clear()
            self._long_candidate_history_short.clear()
            self._long_candidate_history_medium.clear()
            self._persistence_reset_count += 1
            self._lock_anchor_bpm = self._bpm
            self._bars_since_lock = 0
        else:
            conf = float(score[peak_idx] / (score[:n_lags].sum() + 1e-9))
            alpha = min(0.35, max(0.05, conf * 0.3))
            if not self._env_filled:
                alpha = min(alpha, 0.10)  # dampen cold-start oscillations
            candidate_bpm = self._bpm * (1.0 - alpha) + best_bpm * alpha
            # P4 hardening: cap any single update so one bad frame cannot
            # yank the estimate by 10-15 BPM.
            delta = candidate_bpm - self._bpm
            if delta > self._max_bpm_step:
                candidate_bpm = self._bpm + self._max_bpm_step
            elif delta < -self._max_bpm_step:
                candidate_bpm = self._bpm - self._max_bpm_step
            self._bpm = candidate_bpm

        # Refresh tempo hold window after each accepted BPM update.
        self._tempo_hold_until_t = self._last_t + self._tempo_hold_s

        # Clamp to valid range
        self._bpm = float(np.clip(self._bpm, self._bpm_min, self._bpm_max))

        # Save top-3 ACF candidates (bpm, normalised score) for the recommender.
        # Deliberately sourced from the RAW comb_score (no prior applied),
        # not the prior-weighted `score` used for the lock decision above:
        # the recommender scores every candidate profile's own prior
        # against these hypotheses, so pre-weighting them by whichever
        # profile is *currently* active would suppress tempo lanes the
        # active profile disagrees with, even when a different profile
        # would score them highly. See P1-C in
        # docs/audits/2026-08-04-bpm-detector-audit.md.
        raw_scored = comb_score[:n_lags]
        total = float(raw_scored.sum()) + 1e-9
        top_n = min(3, len(raw_scored))
        top_indices = np.argpartition(raw_scored, -top_n)[-top_n:]
        top_indices = top_indices[np.argsort(raw_scored[top_indices])[::-1]]
        self._top_candidates = [
            (float(self._acf_bpms[i]), float(raw_scored[i] / total))
            for i in top_indices
        ]

    def _cycle_log_snapshot(self, now: float) -> dict:
        """One per-ACF-cycle observation row for cycle_log_hook consumers.

        Built entirely from state the cycle just wrote — counters are
        cumulative (consumers diff adjacent rows to get per-cycle gate
        outcomes), candidates are the raw comb-score top-3 the
        recommender also sees.
        """
        return {
            't': round(float(now), 4),
            'cycle': self._acf_cycle_count,
            'bpm': round(float(self._bpm), 3),
            'confidence': round(float(self._confidence), 4),
            'acf_confidence': round(float(self._acf_confidence), 4),
            'phase_confidence': round(float(self._phase_confidence), 4),
            'top_candidates': [
                (round(b, 3), round(s, 5)) for b, s in self._top_candidates
            ],
            'interp_delta_bpm': round(float(self._acf_interpolation_delta_bpm), 4),
            'candidate_median': round(float(self.long_candidate_median), 3),
            'candidate_spread': round(float(self.long_candidate_spread), 3),
            'bars_since_lock': int(self._bars_since_lock),
            'dwell_gated_count': int(self._dwell_gated_count),
            'persistence_reset_count': int(self._persistence_reset_count),
            'tactus_fold_accepted_count': int(self.tactus_fold_accepted_count),
            'tactus_region_reject_count': int(self.tactus_region_reject_count),
            'tactus_score_reject_count': int(self.tactus_score_reject_count),
            'genre_evidence_applied_count': int(self._genre_evidence_applied_count),
            'cold_start_guard_active': bool(self.cold_start_guard_active),
            'candidate_lock_disagreement': bool(self.candidate_lock_disagreement),
            'tap_prime_active': bool(self.tap_prime_active),
        }

    # ------------------------------------------------------------------ #
    # P5 — phase oscillator                                                 #
    # ------------------------------------------------------------------ #

    def _absorb_onset(self, ev_t: float, strength: float, band_weight: float = 1.0) -> None:
        """Attempt to phase-lock to an onset.

        If the onset lands within ±phase_tol of beat phase 0, nudge the
        phase toward 0 and record a coherence hit.  Off-grid onsets are
        silently discarded — they cannot corrupt the tempo estimate.

        2026-08-14: the onset's contribution to phase confidence is
        weighted by ``band_weight`` (bass fraction of its flux, 0..1) and
        a saturating function of ``strength`` -- see
        ``_V2_PHASE_STRENGTH_SATURATION``'s field comment. A strong,
        bass-heavy onset (a kick) that hits confirms the lock strongly; a
        weak or treble-heavy onset (a hi-hat, a fill) barely moves
        confidence either way, hit or miss -- it isn't expected to land
        on the beat at all, so it shouldn't be evidence against the lock
        when it doesn't. A strong, bass-heavy onset that *misses* still
        drags confidence down hard, same as before -- that is real
        evidence of a bad lock, not something this weighting excuses.
        """
        if self._bpm <= 0.0:
            return
        weight = (
            max(0.0, min(1.0, band_weight))
            * min(1.0, max(0.0, strength) / _V2_PHASE_STRENGTH_SATURATION)
        )
        # Measure phase error (signed, wrapping at ±0.5)
        err = self._phase if self._phase < 0.5 else self._phase - 1.0
        # 2026-08-17 (audit menu #2): raw signed error recorded for every
        # onset, hit or miss, unweighted -- the distribution's median/IQR
        # (properties below) discriminate the phase-confidence cap's two
        # candidate causes (off-beat onset mix vs. mechanical offset).
        self._phase_err_buf.append(float(err))
        if abs(err) <= self._phase_tol:
            self._phase -= _V2_PHASE_NUDGE * err
            self._phase = max(0.0, min(0.999, self._phase))
            self._coherence_hit_weight.append(weight)
            self._append_beat_position(ev_t)
        else:
            self._coherence_hit_weight.append(0.0)
        self._coherence_total_weight.append(weight)
        # Refresh phase confidence, then recompute the public blend so an ACF
        # update since the last onset isn't silently discarded. Skip the
        # update (leave _phase_confidence at its last value) when the
        # window holds no diagnostic evidence at all -- e.g. a stretch of
        # nothing but weak, treble-only onsets -- rather than let a
        # near-zero denominator produce a noisy, meaningless ratio.
        total = sum(self._coherence_total_weight)
        if total > 1e-9:
            self._phase_confidence = float(sum(self._coherence_hit_weight)) / total
        # 2026-08-10: 0.4/0.6 -> 0.5/0.5; 2026-08-11: 0.5/0.5 -> 0.7/0.3,
        # TEMPORARY -- see the field comment in _estimate_tempo_acf() above.
        # 2026-08-14: phase_confidence itself is now strength/band-weighted
        # (see this method's docstring) rather than a flat per-onset hit
        # rate -- the real fix this blend ratio was standing in for. Live
        # validation the same day: BPM/genre correct from the first song,
        # confidence still too low, so 0.7/0.3 -> 0.8/0.2 per the owner's
        # pre-stated fallback in the rc.54 commit message.
        # 2026-08-14, later still: three-term blend, dbc folded in at 0.2,
        # ACF cut 0.8 -> 0.6 to make room. See _estimate_tempo_acf() above
        # (same formula, same _downbeat_regularity() rationale) and
        # docs/adr/vj-system.md.
        # Downbeat regularity confidence idea & math by Jason. ;D
        # 2026-08-14, later still: weights re-tuned 0.6/0.2/0.2 -> 0.65/0.1/
        # 0.25 -- see the matching call site in _estimate_tempo_acf() above
        # for the full rationale.
        self._downbeat_regularity_value = self._downbeat_regularity(self._last_t)
        self._confidence = (
            0.65 * self._acf_confidence
            + 0.1 * self._phase_confidence
            + 0.25 * self._downbeat_regularity_value
        )
        # Cold-start blend guard -- mirror of the _estimate_tempo_acf()
        # site (2026-08-17); the counter decrements only there.
        if self._cold_start_cycles_left > 0:
            self._confidence = (
                0.9 * self._acf_confidence + 0.1 * self._phase_confidence
            )
        if self._last_t < self._tempo_hold_until_t:
            self._confidence = max(self._confidence, self._primed_confidence)

    def _advance_phase(self, dt: float, now: float) -> None:
        """Advance phase oscillator by dt seconds at current BPM.

        Fires is_beat and is_downbeat when phase wraps past 0.  Loops so a
        single long/hitched frame spanning multiple beat periods processes
        every crossing (and its downbeat check) instead of silently folding
        them into one clamped wrap and losing the rest.
        """
        if self._bpm <= 0.0:
            return
        self._phase += dt * (self._bpm / 60.0)
        while self._phase >= 1.0:
            self._phase -= 1.0
            self._is_beat = True
            self._beat_index += 1
            self._append_beat_position(now)
            self._bar_beat_count = (self._bar_beat_count + 1) % 4
            if self._bar_beat_count == 0:
                # 2026-08-17: bar-relative dwell clock (plan § 1.2) --
                # counts musical bars since the current lock anchor,
                # independent of the downbeat confidence gate below (bars
                # elapse whether or not is_downbeat fires publicly).
                if self._lock_anchor_bpm > 0.0:
                    self._bars_since_lock += 1
                db_conf = self._compute_downbeat_confidence(now)
                self._last_downbeat_confidence = db_conf
                if db_conf >= self._analysis_downbeat_confidence_min:
                    self._is_downbeat = True
                    callbacks = self._pending_callbacks[:]
                    self._pending_callbacks.clear()
                    for cb in callbacks:
                        try:
                            cb()
                        except Exception:
                            pass
        # Clamp only after the loop settles below 1.0 — guards float precision
        # (e.g. phase landing at 0.99999999999998 on the boundary).
        self._phase = max(0.0, min(0.999, self._phase))

    # ------------------------------------------------------------------ #
    # Profile integration                                                  #
    # ------------------------------------------------------------------ #

    def set_profile(self, profile: object) -> None:
        """Apply a genre profile's BPM prior and recompute ACF weights --
        but ONLY before any tempo has been established (``self._bpm <=
        0.0``); a complete, unconditional no-op every call after that.

        2026-08-14, round three: this guard was `BeatTrackerV3`'s one and
        only behavioral difference from v2 for several weeks; folded
        directly in here and the subclass retired once real session data
        confirmed it made zero
        difference to any decision `BeatTrackerV3` was still exercising
        in production (100% BPM agreement, v2 shadow vs v3 active, across
        a full live session -- the one call site that ever fed a
        genre-specific profile into a locked tracker had already been
        removed at `_DETECTOR_VERSION` rc.20's one-way-flow cut). "v3" is
        retained purely as a `beat_tracker_engine` config alias for
        `_load_beat_grid_cls()` (now resolving to this same class, with a
        deprecation log line) so existing configs keep working; the name
        is free for the next real architecture generation. See
        docs/adr/vj-system.md.

        Root cause this guard fixes (see docs/adr/vj-system.md, the
        2026-07-18 "20 BPM hot" investigation, the 2026-08-12 overnight
        compounding incident, and the 2026-08-13 addendum that reframed
        both): a genre/profile is inferred *from* BPM among other signals
        (``tempo_fit`` is a recommender scoring term) -- BPM sits higher
        in that dependency chain than genre does. Unconditionally
        re-priming the ACF's Gaussian tempo prior (``_prior_mu``/
        ``_prior_sigma``) on every call, including when the profile
        recommender auto-applies a new genre mid-track, let truth flow
        *backward*, from an inference back into the measurement it was
        inferred from. A profile disagreeing with the current tempo
        reading means other scoring terms are outweighing tempo for that
        candidate, not that the tempo reading is wrong; the tempo hasn't
        changed just because the recommender's opinion did. Real session
        logs (both incidents above) showed this backward flow drags an
        already correctly-locked BPM toward a new profile's prior over
        the following seconds to hours even though the track's actual
        tempo never changed.

        2026-08-12's fix was a freeze with acquire/release hysteresis,
        gating re-priming on confidence. That closed one incident but was
        still treating a symptom: it only blocked the backward flow
        *while confidently locked*, so a cold start or a lock loss still
        let a wrong guess get re-asserted, and it added real state-
        machine complexity (paired thresholds, a sticky flag) to manage a
        coupling that should not exist in the first place. 2026-08-13,
        superseding that fix entirely: priming only ever happens *before*
        any tempo has been established -- there is no reading to protect
        yet, so a rough genre-informed starting point is reasonable
        disambiguation, not truth-reversal. The instant a real
        ``self._bpm`` is established, every subsequent call is a complete
        no-op, unconditionally -- no confidence check, no hysteresis, no
        freeze/unfreeze state at all. ``_reset_tempo_lock()`` (silence /
        new track) zeroes ``_bpm`` back to ``0.0``, so the next real track
        legitimately gets a fresh cold-start prime.

        Deliberately does NOT narrow ``_bpm_min``/``_bpm_max`` (the ACF's
        candidate search range) -- only the log2-Gaussian prior that
        weights candidates *within* that range. A genre profile is soft
        evidence, not ground truth: hard-clamping the search range here
        (formerly via ``bpm_hint_min``/``bpm_hint_max``) meant a wrongly
        applied profile could permanently hide the true tempo from the
        search, and the detected BPM confirming the wrong profile back to
        the recommender. There is still no search-range clamp (P0-A/P1-D,
        docs/audits/2026-08-04-bpm-detector-audit.md). ``prime_tempo()``
        (external ground-truth BPM, e.g. from the DJ mixer's own
        analysis) is a separate mechanism and unaffected by this guard --
        that source is genuinely authoritative, not an inference from the
        same detector loop, so it is not the backward-flow case this
        guard exists to prevent.
        """
        if profile is None or self._bpm > 0.0:
            return
        # 2026-08-17: a live tap-trust window outranks a genre prior even
        # at cold start -- the operator's real-time tap is stronger
        # evidence than a genre label (plan § 4.5). The profile prior is
        # applied normally once the window expires/restores.
        if self._tap_saved_prior is not None and self._last_t < self._tap_prime_until_t:
            return
        mu = float(getattr(profile, 'bpm_prior_mu', self._prior_mu) or self._prior_mu)
        sigma = max(
            _MIN_PROFILE_PRIOR_SIGMA,
            float(getattr(profile, 'bpm_prior_sigma', self._prior_sigma) or self._prior_sigma),
        )
        self._prior_mu = mu
        self._prior_sigma = sigma
        if self._acf_bpms is not None:
            log_bpms = np.log2(self._acf_bpms.astype(np.float32))
            log_mu = float(np.log2(mu))
            self._acf_prior = np.exp(
                -0.5 * ((log_bpms - log_mu) / sigma) ** 2
            ).astype(np.float32)

    def prime_tempo(self, bpm: float, *, confidence: float = 0.9) -> None:
        """Prime the tempo directly from an external ground-truth BPM.

        Used when a fresh reading is available on the shared BPM bus (e.g.
        the DJ mixer's own per-track analysis, via ``vj_api.get_bpm()``) --
        that source's detection is authoritative when present, so this
        short-circuits the ACF estimator rather than competing with it.
        Confidence (both the ACF and phase components feeding the public
        blend) is only ever raised, never lowered. Refreshes the tempo-hold
        window so the ACF's own continuity guards don't immediately fight
        the primed value on the next update. See P0-B in
        docs/audits/2026-08-04-bpm-detector-audit.md.

        2026-08-06: also sets self._primed_confidence, a floor applied to
        self._confidence for as long as _tempo_hold_until_t stays fresh.
        Previously the conf bump here was purely cosmetic: the very next
        onset recomputed self._confidence from the raw ACF/phase blend with
        no memory a prime had just happened, so an authoritative 0.9 could
        (and on live sessions did) collapse back toward ~0.2 within one
        onset if the phase-coherence buffer hadn't caught up to the newly
        primed tempo yet -- "authoritative when present" wasn't actually
        being honoured past the moment of the call. See docs/adr/vj-system.md.
        """
        bpm = float(bpm)
        if bpm <= 0.0:
            return
        self._bpm = float(np.clip(bpm, self._bpm_min, self._bpm_max))
        conf = float(confidence)
        self._acf_confidence = max(self._acf_confidence, conf)
        self._phase_confidence = max(self._phase_confidence, conf)
        self._confidence = max(self._confidence, conf)
        self._primed_confidence = conf
        self._tempo_hold_until_t = self._last_t + self._tempo_hold_s

    def _recompute_prior_array(self) -> None:
        """Rebuild the cached lag->prior array from _prior_mu/_prior_sigma.

        Factored out 2026-08-17 so the tap-trust window (tap_prime /
        expiry / silence reset) and set_profile() share one
        implementation of the Gaussian-prior refresh.
        """
        if self._acf_bpms is None:
            return
        log_bpms = np.log2(self._acf_bpms.astype(np.float32))
        log_mu = float(np.log2(max(1.0, self._prior_mu)))
        sigma = max(1e-3, float(self._prior_sigma))
        self._acf_prior = np.exp(
            -0.5 * ((log_bpms - log_mu) / sigma) ** 2
        ).astype(np.float32)

    def set_genre_tempo_evidence(
        self, mu_bpm: float, sigma_log2: float, weight: float
    ) -> None:
        """Provide tempo-independent genre evidence for candidate scoring.

        Called by the recommender (auto_vj.py) with the winning candidate
        profile's tempo band, where the win was computed EXCLUSIVELY from
        tempo-independent terms (band/centroid/zcr/spectral-shape/vocal
        fits -- tempo_fit, top_cand_fit, onset_fit and kick_regularity_fit
        are excluded on the caller side; see plan § 4.2/§ 6.5). Consulted
        by _estimate_tempo_acf() only while the previous cycle's ACF
        confidence sits below _V2_GENRE_EVIDENCE_GATE_CONFIDENCE, as a
        bounded multiplicative reweight -- influence, never a gate.
        Evidence expires after _V2_GENRE_EVIDENCE_STALE_S. weight <= 0
        clears any stored evidence.
        """
        weight = float(weight)
        if weight <= 0.0 or mu_bpm <= 0.0:
            self._genre_evidence_weight = 0.0
            self._genre_evidence_until_t = -1e9
            return
        self._genre_evidence_mu = float(mu_bpm)
        self._genre_evidence_sigma = max(
            _V2_GENRE_EVIDENCE_MIN_SIGMA, float(sigma_log2)
        )
        self._genre_evidence_weight = min(1.0, weight)
        self._genre_evidence_until_t = self._last_t + _V2_GENRE_EVIDENCE_STALE_S

    def tap_prime(self, bpm: float, *, window_s: float | None = None) -> bool:
        """Open a tap-tempo trust window around an operator-confirmed BPM.

        Plan § 4.5 ("cheater mode" #2): a human tapping the actual beat is
        genuine external ground truth, categorically different from the
        recommender's own inference (there is no automatic path to a
        keyboard tap, so the backward-flow bug class cannot apply). For
        the window: the Gaussian tempo prior is re-centered on the tapped
        value at _V2_TAP_PRIME_SIGMA, candidates within
        _V2_TAP_PRIME_BAND_PCT of the tap take a fast path through the
        gate stack (see _estimate_tempo_acf()), and the primed-confidence
        floor holds at _V2_TAP_PRIME_CONFIDENCE. On expiry (update()) or
        silence reset, the saved prior is restored exactly. Returns False
        for an implausible tap value.
        """
        bpm = float(bpm)
        if not (40.0 <= bpm <= 220.0):
            return False
        bpm = float(np.clip(bpm, self._bpm_min, self._bpm_max))
        if self._tap_saved_prior is None:
            self._tap_saved_prior = (self._prior_mu, self._prior_sigma)
        self._tap_prime_bpm = bpm
        window = float(window_s) if window_s is not None else _V2_TAP_PRIME_WINDOW_S
        self._tap_prime_until_t = self._last_t + max(1.0, window)
        self._prior_mu = bpm
        self._prior_sigma = _V2_TAP_PRIME_SIGMA
        self._recompute_prior_array()
        self._primed_confidence = _V2_TAP_PRIME_CONFIDENCE
        self._tempo_hold_until_t = self._tap_prime_until_t
        self._confidence = max(self._confidence, _V2_TAP_PRIME_CONFIDENCE)
        return True

    # ------------------------------------------------------------------ #
    # Properties — identical interface to BeatGridTracker                   #
    # ------------------------------------------------------------------ #

    @property
    def bpm(self) -> float:
        """Current BPM estimate (0.0 if not yet locked)."""
        return self._bpm

    @property
    def confidence(self) -> float:
        """BPM confidence 0..1 (phase coherence + ACF peak ratio blend)."""
        return self._confidence

    @property
    def acf_confidence(self) -> float:
        """The blend's ACF-search half, 0..1, on its own (2026-08-10).

        min(1.0, acf_peak_ratio / 3.0) -- how decisively the winning tempo
        candidate beat its best genuinely-competing rival (harmonics of the
        winner excluded). Refreshed only when the ACF re-runs (~every
        _V2_ACF_INTERVAL frames), unlike phase_confidence below which
        updates on every onset. Exposed so a corpus consumer can judge the
        0.4/0.6 blend weighting against real data instead of only ever
        seeing the combined confidence -- see docs/adr/vj-system.md
        "Drop Score Bass-Gated Reweight" § coherence-window follow-up.
        """
        return self._acf_confidence

    @property
    def phase_confidence(self) -> float:
        """The blend's phase-lock half, 0..1, on its own (2026-08-10).

        Rolling hit-rate over the last _V2_COHERENCE_WINDOW onsets that
        landed within ±_V2_PHASE_TOL of predicted beat phase. Same
        exposure rationale as acf_confidence above.
        """
        return self._phase_confidence

    @property
    def phase_confidence_calibrated(self) -> float:
        """`phase_confidence` rescaled to a true 0..1 quantity
        (2026-08-14, round three, audit cross-check item 12.8 #3).

        A completely random onset-to-phase relationship still lands
        inside a `±_phase_tol` window `2 * _phase_tol` of the time by
        chance -- `phase_confidence`'s zero point is that chance floor,
        not `0.0` (`docs/audits/2026-08-13-bpm-tempo-detection-audit.md`
        finding T2). `max(0, (hit_rate - 2*tol) / (1 - 2*tol))` maps the
        chance floor to `0.0` and `1.0` stays `1.0`, so this reads as a
        genuine 0..1 quantity and stops silently shifting scale every
        time `_phase_tol`/`phase_tolerance` is retuned (each historical
        change -- 0.18 -> 0.12 -> 0.14 -- moved the raw chance floor too:
        0.36 -> 0.24 -> 0.28 -- contaminating any before/after
        comparison done on the raw number). `phase_confidence` itself is
        left unchanged -- this is an additional reporting-only field, not
        a replacement; nothing in the confidence blend or any gate reads
        it. See docs/planning/auto-vj-round-three-planning-2026-08-14.md
        § 12.4.
        """
        chance = 2.0 * self._phase_tol
        denom = 1.0 - chance
        if denom <= 1e-9:
            return 0.0
        return max(0.0, (self._phase_confidence - chance) / denom)


    @property
    def phase_error_median(self) -> float:
        """Median signed phase error over the recent onset window (2026-08-17).

        Beat-period fraction in [-0.5, 0.5]. With phase_error_iqr below,
        the discriminator for the phase-confidence-cap investigation: a
        median near 0 with a wide IQR says the onset mix is genuinely
        off-beat (musical); a displaced median says the measurement
        itself carries a systematic offset (mechanical). 0.0 until
        enough onsets exist. See plan § 6.4 / audit menu #2.
        """
        if len(self._phase_err_buf) < 4:
            return 0.0
        return float(np.median(np.asarray(self._phase_err_buf, dtype=np.float32)))

    @property
    def phase_error_iqr(self) -> float:
        """Interquartile range of the signed phase error window (2026-08-17)."""
        if len(self._phase_err_buf) < 4:
            return 0.0
        arr = np.asarray(self._phase_err_buf, dtype=np.float32)
        q75, q25 = np.percentile(arr, [75.0, 25.0])
        return float(q75 - q25)

    @property
    def onset_strength_max_raw(self) -> float:
        """Max raw (pre-compression) onset strength in the recent window
        (2026-08-17, later still -- see _V2_ONSET_STRENGTH_WINDOW_S's own
        comment). 0.0 when no onsets are in the window."""
        if not self._onset_strength_history:
            return 0.0
        return max(raw for _t, raw, _compressed in self._onset_strength_history)

    @property
    def onset_strength_max_compressed(self) -> float:
        """Max compressed (actual envelope-written) onset strength in the
        recent window -- the counterpart to onset_strength_max_raw. The
        two together let a training-corpus reader reconstruct the log-
        compression's real effect at the tail directly from real sessions,
        without needing a synthetic harness."""
        if not self._onset_strength_history:
            return 0.0
        return max(compressed for _t, _raw, compressed in self._onset_strength_history)

    @property
    def persistence_spread_limit(self) -> float:
        """Effective long-window spread limit at the last large-jump eval.

        max(flat, pct * median) (2026-08-17) -- logged so which bound was
        binding is observable per evaluation. 0.0 until the first eval.
        """
        return self._persistence_spread_limit

    @property
    def bars_since_lock(self) -> int:
        """Musical bars elapsed since the current lock anchor (2026-08-17)."""
        return self._bars_since_lock

    @property
    def acf_cycle_count(self) -> int:
        """Completed ACF cycles — the cycle_log_hook cadence (2026-08-17)."""
        return self._acf_cycle_count

    @property
    def dwell_gated_count(self) -> int:
        """Cumulative in-band evaluations escalated by the dwell gate (2026-08-17)."""
        return self._dwell_gated_count

    @property
    def persistence_reset_count(self) -> int:
        """Cumulative T5 Option A deque resets on accepted large jumps (2026-08-17)."""
        return self._persistence_reset_count

    @property
    def cold_start_guard_active(self) -> bool:
        """True while the cold-start confidence-blend guard is engaged (2026-08-17)."""
        return self._cold_start_cycles_left > 0

    @property
    def genre_evidence_weight(self) -> float:
        """Current genre-evidence weight, 0.0 when absent/expired (2026-08-17)."""
        if self._last_t >= self._genre_evidence_until_t:
            return 0.0
        return self._genre_evidence_weight

    @property
    def genre_evidence_applied_count(self) -> int:
        """Cumulative cycles the genre-evidence reweight actually applied (2026-08-17)."""
        return self._genre_evidence_applied_count

    @property
    def tap_prime_active(self) -> bool:
        """True while a tap-tempo trust window is live (2026-08-17)."""
        return self._tap_prime_bpm > 0.0 and self._last_t < self._tap_prime_until_t

    @property
    def tap_prime_accept_count(self) -> int:
        """Cumulative candidates accepted via the tap fast path (2026-08-17)."""
        return self._tap_prime_accept_count

    @property
    def candidate_lock_disagreement(self) -> bool:
        """True when fresh long-window candidate evidence disagrees with the lock.

        2026-08-17 (plan § 6.2's refractory guard): the long persistence
        window's median sits outside the lock band relative to the
        published BPM, and that median was computed within the last 5
        seconds (stale evidence from minutes ago must not read as live
        disagreement). auto_vj.py reads this to suspend the BPM-fed
        analyzer refractory while the estimate is contested, so the
        onset stream cannot be thinned into agreement with a wrong lock
        (the last remaining self-confirmation channel -- audit T4).

        2026-08-17, later still: band widened from the jump-gate's
        _V2_LOCK_BAND_PCT/_MIN (0.03/4.0) to this property's own
        _refractory_guard_band_pct/_min (0.16/10.0 by default) -- real
        session data showed the guard engaging ~9-11 times/sec against the
        tight band, essentially continuous rather than the rare wrong-lock
        rescue it was designed to be. See _V2_REFRACTORY_GUARD_BAND_PCT's
        own comment and docs/adr/vj-system.md.
        """
        if self._bpm <= 0.0 or self._long_candidate_median <= 0.0:
            return False
        if (self._last_t - self._long_candidate_eval_t) > 5.0:
            return False
        band = max(self._refractory_guard_band_min, self._bpm * self._refractory_guard_band_pct)
        return abs(self._long_candidate_median - self._bpm) > band

    @property
    def downbeat_regularity(self) -> float:
        """The blend's third term, 0..1, on its own (2026-08-14).

        (0.45*region_consistency + 0.10*beat_position_density) / 0.55 --
        see _downbeat_regularity()'s own docstring. Cached from the most
        recent confidence-blend computation rather than recomputed here
        (recomputing would need `now`, not available on a property). Same
        exposure rationale as acf_confidence/phase_confidence above --
        previously computed inline and discarded, never observable outside
        the blend. See docs/adr/vj-system.md.
        """
        return self._downbeat_regularity_value

    @property
    def region_consistency(self) -> float:
        """The large-jump accept/reject gate's own region-consistency
        check, 0..1, on its own (2026-08-14, later still).

        NOT the same call as downbeat_regularity's internal region term
        (that one checks self._bpm, the currently-locked tempo, every
        confidence-blend cycle; this one checks a large-jump *candidate*
        tempo, only when a jump outside the lock band is being evaluated
        -- see _estimate_tempo_acf()'s large-jump gate). Stays at its last
        computed value (0.0 if never computed) between large-jump
        evaluations, most updates being small in-band nudges that never
        touch this check. See docs/adr/vj-system.md.
        """
        return self._region_consistency_value

    @property
    def long_candidate_spread(self) -> float:
        """The large-jump persistence check's own last-computed spread
        (max absolute deviation from the median, in BPM) across the last
        `large_jump_persistence_cycles` raw candidates (2026-08-14, round
        three).

        This is the exact number `_estimate_tempo_acf()` compares against
        the hardcoded `6.0` BPM threshold -- logged now so a future
        session can judge that threshold from ground truth instead of
        reconstructing it from the much coarser decision-tick log (each
        corpus row is one sample of roughly 7-8 real ACF cycles). Stays at
        its last computed value (0.0 if never computed) between large-jump
        evaluations. See docs/adr/vj-system.md.
        """
        return self._long_candidate_spread

    @property
    def long_candidate_median(self) -> float:
        """The large-jump persistence check's own last-computed median
        BPM across the last `large_jump_persistence_cycles` raw
        candidates. Paired with `long_candidate_spread` above."""
        return self._long_candidate_median

    @property
    def lock_band_bpm(self) -> float:
        """The REAL, currently-live lock band in BPM --
        `max(_V2_LOCK_BAND_MIN, self._bpm * _V2_LOCK_BAND_PCT)` -- the
        only one of the three lock-band values that actually gates
        anything. Paired with `lock_band_candidate_analytical`/
        `lock_band_candidate_empirical` below for a same-row, three-way
        comparison. 0.0 before a tempo is established."""
        return max(self._lock_band_min, self._bpm * self._lock_band_pct) if self._bpm > 0.0 else 0.0

    @property
    def lock_band_candidate_analytical(self) -> float:
        """Candidate lock-band replacement, LOGGED ONLY -- does not gate
        anything. `k` lag-grid steps at the current BPM (see
        `_V2_LOCK_BAND_CANDIDATE_ANALYTICAL_K`'s own comment for the
        derivation and why this is being compared against the real
        `lock_band_bpm` and the empirical candidate below)."""
        return self._lock_band_candidate_analytical

    @property
    def lock_band_candidate_empirical(self) -> float:
        """Candidate lock-band replacement, LOGGED ONLY -- does not gate
        anything. A flat constant derived from real measured jitter (see
        `_V2_LOCK_BAND_CANDIDATE_EMPIRICAL_BPM`'s own comment)."""
        return self._lock_band_candidate_empirical

    @property
    def acf_interpolation_delta_bpm(self) -> float:
        """How much the sub-lag parabolic peak interpolation moved the
        most recent cycle's BPM reading off the raw integer-lag grid
        value (2026-08-14, round three A/B test). 0.0 before the first
        ACF cycle and whenever the winning peak sat at a search-range
        edge (interpolation skipped there). See _estimate_tempo_acf()."""
        return self._acf_interpolation_delta_bpm

    @property
    def top_candidates(self) -> list[tuple[float, float]]:
        """Top-3 ACF BPM candidates as (bpm, normalised_score) pairs.

        Ordered highest-score first.  Empty until the first ACF cycle completes.
        The recommender uses these to score profiles against multiple tempo
        hypotheses rather than only the locked BPM.
        """
        return self._top_candidates

    @property
    def beat_phase(self) -> float:
        """Phase within the current beat interval, 0..1."""
        return self._beat_phase

    @property
    def is_beat(self) -> bool:
        """True for exactly one frame per oscillator beat crossing."""
        return self._is_beat

    @property
    def is_downbeat(self) -> bool:
        """True for one frame per 4-beat bar boundary."""
        return self._is_downbeat

    @property
    def beat_index(self) -> int:
        """Monotonically increasing count of oscillator beat crossings (-1 before the first)."""
        return self._beat_index

    @property
    def energy(self) -> float:
        """Low-pass smoothed sum of bass+mid+treble."""
        return self._energy

    @property
    def energy_slope(self) -> float:
        """Energy delta over ~2 s window (positive = rising)."""
        return self._energy - self._energy_prev_2s

    @property
    def drop_score(self) -> float:
        """Composite drop-likelihood signal 0..1 (legacy — see drop_sustain)."""
        return self._drop_score

    @property
    def impact_novelty(self) -> float:
        """Drop TRIGGER 0..1 (2026-08-18 split): bass transient × broadband
        activity × was-bass-suppressed × slope influence. Event/boundary
        signal — spikes at the slam-back moment, not a level."""
        return self._impact_novelty

    @property
    def drop_sustain(self) -> float:
        """Drop SUSTAIN 0..1 (2026-08-18 split): normalized raw-path bass
        level × busyness (product — zero bass forces zero, audit F9).
        State signal — stays high for the whole held drop by construction."""
        return self._drop_sustain

    @property
    def bass_level_norm(self) -> float:
        """Percentile-normalized raw-path bass level 0..1 (the F4 primitive)."""
        return self._bass_level_norm_value

    @property
    def bass_was_suppressed(self) -> float:
        """1 − normalized recent-max bass level over the bars-window (0..1)."""
        return self._bass_suppressed_value

    @property
    def downbeat_confidence(self) -> float:
        """Current analysis-mode downbeat confidence (0..1)."""
        return self._last_downbeat_confidence

    @property
    def kick_regularity(self) -> float:
        """Last kick_regularity reading passed to update() (0..1, default 0.0)."""
        return self._kick_regularity

    @property
    def effective_tactus_ratio(self) -> float:
        """Current tactus fold-eagerness ratio -- see _effective_tactus_ratio()."""
        return self._effective_tactus_ratio()

    @property
    def tactus_fold_accepted_count(self) -> int:
        """Session-cumulative count of tactus folds actually taken."""
        return self._tactus_fold_accepted_count

    @property
    def tactus_region_reject_count(self) -> int:
        """Session-cumulative count of folds blocked by the region-consistency guard (2026-08-13)."""
        return self._tactus_region_reject_count

    @property
    def tactus_score_reject_count(self) -> int:
        """Session-cumulative count of candidates that never cleared the score-ratio check."""
        return self._tactus_score_reject_count

    @property
    def last_tactus_fold(self) -> str:
        """Most recent individual tactus fold decision (2026-08-14, later
        still), e.g. 'accepted:150.00->75.00' / 'score_reject:150.00->75.00'
        / 'region_reject:150.00->75.00'. '' before the first evaluation
        this session. The counters above tally outcomes; this shows which
        specific fold each one was."""
        return self._last_tactus_fold

    @property
    def large_jump_persistence_wait_count(self) -> int:
        """Session-cumulative count of large-jump candidates rejected because
        _long_candidate_history hasn't reached large_jump_persistence_cycles
        entries yet -- the check hasn't had enough time to form an opinion."""
        return self._large_jump_persistence_wait_count

    @property
    def large_jump_persistence_reject_count(self) -> int:
        """Session-cumulative count of large-jump candidates rejected because
        the long-window history was too inconsistent (spread > 6 BPM) or
        disagreed with this cycle's candidate by > 6 BPM -- the check saw
        enough history and decided it doesn't support this jump."""
        return self._large_jump_persistence_reject_count

    @property
    def large_jump_persistence_cleared_count(self) -> int:
        """Session-cumulative count of large-jump candidates that cleared the
        long-window persistence check (the confidence/region-consistency
        check right after it still has final say on acceptance)."""
        return self._large_jump_persistence_cleared_count

    @property
    def large_jump_persistence_cleared_count_short(self) -> int:
        """Same as large_jump_persistence_cleared_count, LOGGED-ONLY
        candidate using a 10-cycle window instead of the real 25. See
        _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_SHORT's own comment."""
        return self._large_jump_persistence_cleared_count_short

    @property
    def large_jump_persistence_reject_count_short(self) -> int:
        """Same as large_jump_persistence_reject_count, LOGGED-ONLY
        candidate using a 10-cycle window instead of the real 25."""
        return self._large_jump_persistence_reject_count_short

    @property
    def large_jump_persistence_cleared_count_medium(self) -> int:
        """Same as large_jump_persistence_cleared_count, LOGGED-ONLY
        candidate using a 15-cycle window instead of the real 25. See
        _V2_LARGE_JUMP_PERSISTENCE_CYCLES_CANDIDATE_MEDIUM's own comment."""
        return self._large_jump_persistence_cleared_count_medium

    @property
    def large_jump_persistence_reject_count_medium(self) -> int:
        """Same as large_jump_persistence_reject_count, LOGGED-ONLY
        candidate using a 15-cycle window instead of the real 25."""
        return self._large_jump_persistence_reject_count_medium

    @property
    def kick_evidence_smooth(self) -> float:
        """EMA-smoothed kick_regularity (0..1) -- the signal the sparse-
        evidence update gate checks against _min_kick_evidence. See
        _V2_KICK_EVIDENCE_ALPHA's own comment for why this is smoothed
        rather than gating on raw kick_regularity directly."""
        return self._kick_evidence_smooth

    @property
    def kick_evidence_reject_count(self) -> int:
        """Session-cumulative count of already-locked BPM updates rejected
        because kick_evidence_smooth fell below _min_kick_evidence -- the
        recent audio lacked enough rhythmic structure to trust a tempo
        change. See _V2_MIN_KICK_EVIDENCE's own comment."""
        return self._kick_evidence_reject_count

    @property
    def spectral_flux_smooth(self) -> float:
        """EMA-smoothed mid+treble spectral flux as fed into drop_score (0..unbounded)."""
        return self._flux_smooth

    @property
    def bass_flux_fast(self) -> float:
        """Fast-attack/slower-release bass flux as fed into drop_score (0..unbounded)."""
        return self._bass_flux_fast

    def schedule_for_next_downbeat(self, callback: Any) -> None:
        """Queue a callable to fire on the next detected bar downbeat."""
        self._pending_callbacks.append(callback)

    def clear_pending(self) -> None:
        """Discard all queued downbeat callbacks."""
        self._pending_callbacks.clear()

    # 2026-08-14, round three: BeatTrackerV3 retired -- its one and only
    # override (set_profile()'s pre-lock-only guard) is now BeatTracker's
    # own default behavior, above. See that method's docstring for the
    # full history and docs/adr/vj-system.md for the empirical
    # confirmation (100% BPM agreement, v2 shadow vs v3 active, across a
    # full live session) that motivated folding it in. The "v3" name is
    # retained only as a beat_tracker_engine config alias in auto_vj.py's
    # _load_beat_grid_cls() -- free for the next real architecture
    # generation.


# --------------------------------------------------------------------------- #
# BeatTracker v3 — the HMM generation (phase 1, 2026-09-02)
# --------------------------------------------------------------------------- #

# v3 phase-1 tunables (the "one matrix" replacing v2's seven-gate stack;
# SIZING RULE (2026-09-02, sweep rounds 1-4): the ACF observation cycles at
# ~7.4 Hz, so a lane survives N cycles of contrary evidence only while
# L**N * m < 1 -- L = per-cycle likelihood ratio (~1/_V3_OBS_FLOOR at power 1),
# m = fold escape mass. v2's dwell 32 cycles needs L < ~1.2 at m = 2e-3, or
# m ~ 1e-6 at floor 0.7. Defaults below = offline config "I" (steadiest);
# each maps to a validated v2 lesson — see the engine bake-off + tuning
# experiment in the session ledger and docs/adr/vj-system.md):
_V3_LATTICE_MIN_BPM = 55.0     # below the store's old 70 clamp: 54-59 tags exist
_V3_LATTICE_MAX_BPM = 210.0    # HMM DESIGN REQUIREMENT #1: fast lanes are
                               # first-class — v2's fold-down cost dnb -50pt exact
_V3_LATTICE_STEP_LOG2 = 0.01   # ~0.7% per state (~193 states)
_V3_DRIFT_SIGMA_LOG2 = 0.006   # per-cycle tempo drift kernel width (v2's
                               # 4% dwell drift budget spread over a window)
_V3_FOLD_PROB_OCTAVE = 1e-6    # transition mass to 2:1 / 1:2 lanes,
_V3_FOLD_PROB_TRIPLET = 5e-7   # ... and to 3:2 / 2:3 / 4:3 / 3:4 lanes —
                               # SYMMETRIC up/down by construction (the
                               # asymmetric fold-DOWN-only descent was v2's
                               # measured dnb failure)
_V3_NOVELTY_LEAK = 1e-8        # uniform mass so no state is ever unreachable
_V3_OBS_POWER = 1.0            # observation sharpening (comb score exponent)
_V3_OBS_FLOOR = 0.70           # likelihood floor: sets the per-cycle evidence
                               # dynamic range (floor**power : 1) against the
                               # transition's stickiness -- the memory dial
_V3_OBS_SOURCE = 'template'    # 'template' (phase 2 default: cosine match vs the ideal
                               # beat-train comb profile per lattice tempo) | 'comb' raw
                               # comb score (phase 1) | 'score' v2 post-prior | 'hybrid'
                               # shape x magnitude (tested worse, kept for experiments)
                               # post-prior score (comb * prior, what v2 argmaxes)
# Phase 2 (2026-09-03): template observation. For each lattice tempo s, the
# predicted comb profile of an ideal beat train at s (spikes at k*P_s, weaker
# ones at half-beats) is precomputed over the ACF grid; the likelihood is the
# cosine match between the observed comb and that template. The true tempo's
# template explains its own harmonic aliases (4/3, 5/4, 3-beat); an alias's
# template predicts peaks the observation lacks. Selected by _V3_OBS_SOURCE.
# Phase 2 (2026-09-03): where the profile prior enters. 'percycle' multiplies
# a bounded prior bias into every observation (phase-1 behaviour) -- at 7.4 Hz
# that compounds to prior**N and pulled 7/18 ambient tracks to mu=120.4
# regardless of tag. 'init' seeds the posterior with the prior ONCE (the
# textbook filter) and leaves each cycle's evidence unbiased.
_V3_PRIOR_MODE = 'percycle'
_V3_PRIOR_GAIN = 1.0           # exponent on the per-cycle prior bias: 1.0 = phase 1
                               # (bias range 0.5-1.0 per cycle, out-ranges a floored
                               # observation); 0.1-0.3 makes the prior a slow, steady
                               # pull that accumulates over tens of cycles instead
_V3_TMPL_SIGMA_LAGS = 1.5      # spike width on the 100 Hz lag grid (samples)
_V3_TMPL_SUBBEAT = 0.0         # half-beat spikes OFF: with them, 2T's template matches a
                               # track with hats as well as T's own (bake 3 / sweep W)
_V3_TMPL_DECAY = 0.90          # per-beat decay of the ideal ACF spikes
_V3_TMPL_BEATS = 12            # beat multiples modelled in the ideal ACF
_V3_FOLD_OBS_WEIGHT = 0.0      # extra observation support from comb score at
                               # the state's double/half tempo (0 = off)
_V3_CONF_BAND = 0.04           # confidence = posterior mass within +-4% of MAP
# Phase 3 (2026-09-03): observation apply mode + fold-suspect telemetry.
# 'tick' (default, the behaviour bake 3 validated): the template-family
# likelihood AND the transition step run on every 60 Hz update() with the
# latest ACF observation held -- held-observation filtering at frame rate.
# Effect per ~7.4 Hz cycle: evidence ~8x sharper, prior ~8x stronger, drift
# x sqrt(8), escape mass x8 -> sharp confidence (few Schmidt lock flips) and
# cheap late corrections. Applying once per cycle ('cycle') halves tick
# jitter but leaves the posterior broad: bake 4 measured lock churn 3-8x
# worse on every list, and no constant-factor re-sizing reproduced 'tick'
# (rounds 3-4). The comb/score sources always apply once per cycle (the
# phase-1 validated regime). Lane hysteresis and any comb-magnitude term
# were tried in phase 3 and rejected (see docs/adr/vj-system.md).
_V3_OBS_APPLY = 'tick'
# Phase 4 (2026-09-03): onset-density observation channel -- v2's density guard
# (density_bpm = onsets/min over the envelope window; lane > 1.3x that rate is
# suspect) expressed as evidence: per lattice tempo s, q = s / density_bpm;
# likelihood 1 for q <= FAST_RATIO, log-Gaussian fall-off above (sigma in log2),
# floored. Lanes faster than the onset rate (the 2T and 4/3 aliases) lose;
# slower lanes stay plausible (subdivisions are normal). Weight 0 = off. In
# tick mode it compounds ~8x per cycle like the rest of the observation.
_V3_DENSITY_WEIGHT = 0.0       # phase 4: measured NO leverage on the octave/4:3 residue
                               # (raw onsets sit at the alias rate); kept inert as a
                               # documented negative -- see docs/adr/vj-system.md
_V3_DENSITY_FAST_RATIO = 1.30  # same threshold as _V2_DENSITY_FAST_RATIO
_V3_DENSITY_SIGMA = 0.35       # fall-off width in log2 units above the ratio
_V3_DENSITY_FLOOR = 0.90       # per-application floor (sized for tick mode)
# Phase 4 (2026-09-03): external prime. prime_tempo() is the one-way ground-
# truth channel (mixer analysis, tap tempo). v2 only sets bpm + a confidence
# hold; a v3 posterior would overturn that within a second. So v3 also SEEDS
# the posterior at the primed tempo and RE-CENTRES the per-cycle prior bias on
# it (tight sigma) for a hold window -- the octave/4:3 residue is a notated-vs-
# sounding ambiguity that audio evidence cannot settle (three signals, two
# bands, and the prior centre all measured without leverage), but a tagged
# local file or the mixer's analysis can.
_V3_PRIME_SIGMA = 0.20         # log2 width of the primed prior / posterior seed
_V3_PRIME_HOLD_S = 20.0        # seconds the primed prior centre stays in force after
                               # the LAST prime (refreshed by every re-prime; the live
                               # path re-primes every recommender eval while the bus
                               # hint is fresh). 0 = until the next prime.
_V3_FOLD_SUSPECT_RATIOS = (2.0, 0.5, 1.5, 2.0 / 3.0, 4.0 / 3.0, 0.75)


class BeatTrackerV3(BeatTracker):
    """The HMM tempo engine — v2's observation, one probabilistic decision.

    Phase 1 architecture (roadmap Thread 1): v2 runs untouched as the
    observation extractor and phase/onset machinery (``super().update()``
    computes the raw comb-filter score, retained via
    ``_last_acf_observation``); this class then re-decides the tempo by a
    forward-filtered hidden-state posterior over a log-spaced tempo
    lattice and OVERWRITES ``self._bpm`` / ``self._confidence`` with the
    posterior's answer. v2's own gate-stack verdict is computed and
    discarded — wasteful by a fraction of a millisecond, and worth it:
    v2 stays byte-identical (the protected-baseline ground rule) while
    every downstream consumer (auto_vj's Schmidt trigger, the phase
    oscillator, corpus telemetry) sees the ordinary interface.

    The transition model IS the centralized tweakable set: a local drift
    kernel (stay/wander), explicit symmetric fold-jump mass at the
    musical ratios, and a novelty leak. Seven interacting v2 gates
    (persistence, jump confidence, lock bands, dwell, tactus descent,
    density guard, raw-dominance) collapse into those four numbers plus
    the observation sharpening power.

    Confidence is a real probability: posterior mass within +-4% of the
    MAP state — consumed by auto_vj's existing 0.45/0.2 Schmidt trigger
    unchanged.
    """

    ENGINE_VERSION = '3.0.0'

    def __init__(self, cfg: dict | None = None) -> None:
        super().__init__(cfg or {})
        c = cfg or {}
        lo = float(c.get('v3_lattice_min_bpm', _V3_LATTICE_MIN_BPM))
        hi = float(c.get('v3_lattice_max_bpm', _V3_LATTICE_MAX_BPM))
        step = float(c.get('v3_lattice_step_log2', _V3_LATTICE_STEP_LOG2))
        n = max(8, int(math.log2(hi / lo) / step) + 1)
        self._v3_bpms = lo * (2.0 ** (np.arange(n) * step))
        self._v3_log_bpms = np.log2(self._v3_bpms)
        self._v3_posterior = np.full(n, 1.0 / n, dtype=np.float64)
        self._v3_drift_sigma = float(c.get('v3_drift_sigma_log2', _V3_DRIFT_SIGMA_LOG2))
        self._v3_fold_octave = float(c.get('v3_fold_prob_octave', _V3_FOLD_PROB_OCTAVE))
        self._v3_fold_triplet = float(c.get('v3_fold_prob_triplet', _V3_FOLD_PROB_TRIPLET))
        self._v3_novelty = float(c.get('v3_novelty_leak', _V3_NOVELTY_LEAK))
        self._v3_obs_power = float(c.get('v3_obs_power', _V3_OBS_POWER))
        self._v3_obs_floor = float(c.get('v3_obs_floor', _V3_OBS_FLOOR))
        self._v3_fold_obs_weight = float(c.get('v3_fold_obs_weight', _V3_FOLD_OBS_WEIGHT))
        self._v3_obs_source = str(c.get('v3_obs_source', _V3_OBS_SOURCE))
        self._v3_tmpl_sigma = float(c.get('v3_tmpl_sigma_lags', _V3_TMPL_SIGMA_LAGS))
        self._v3_tmpl_subbeat = float(c.get('v3_tmpl_subbeat', _V3_TMPL_SUBBEAT))
        self._v3_tmpl_decay = float(c.get('v3_tmpl_decay', _V3_TMPL_DECAY))
        self._v3_tmpl_beats = int(c.get('v3_tmpl_beats', _V3_TMPL_BEATS))
        self._v3_templates: np.ndarray | None = None   # (n_states, n_acf_grid), lazy
        self._v3_templates_key: tuple | None = None
        self._v3_prior_mode = str(c.get('v3_prior_mode', _V3_PRIOR_MODE))
        self._v3_prior_gain = float(c.get('v3_prior_gain', _V3_PRIOR_GAIN))
        self._v3_obs_apply = str(c.get('v3_obs_apply', _V3_OBS_APPLY))
        self._v3_density_weight = float(c.get('v3_density_weight', _V3_DENSITY_WEIGHT))
        self._v3_density_fast = float(c.get('v3_density_fast_ratio', _V3_DENSITY_FAST_RATIO))
        self._v3_density_sigma = float(c.get('v3_density_sigma', _V3_DENSITY_SIGMA))
        self._v3_density_floor = float(c.get('v3_density_floor', _V3_DENSITY_FLOOR))
        self._v3_density_engaged_count = 0    # engagement: cycles where the channel bit (< 1 somewhere in the top band)
        self._v3_prime_sigma = float(c.get('v3_prime_sigma', _V3_PRIME_SIGMA))
        self._v3_prime_hold_s = float(c.get('v3_prime_hold_s', _V3_PRIME_HOLD_S))
        self._v3_prime_mu: float = 0.0        # primed prior centre (0 = none)
        self._v3_prime_until_t: float = -1.0
        self._v3_prime_count = 0              # engagement: primes honoured
        self._v3_fold_suspect_mass: float = 0.0  # posterior mass on fold lanes of the MAP one
        if self._v3_prior_mode == 'init':
            mu0 = float(getattr(self, '_prior_mu', 120.0) or 120.0)
            sg0 = max(0.35, float(getattr(self, '_prior_sigma', 0.55) or 0.55))
            z0 = (self._v3_log_bpms - math.log2(max(1.0, mu0))) / sg0
            init = np.exp(-0.5 * z0 * z0) + 1e-3
            self._v3_posterior = init / init.sum()
        self._v3_seen_cycle = -1
        self._v3_transition = self._v3_build_transition(n)
        # Engagement counters per the new-tunables rule.
        self._v3_cycle_applied_count = 0
        self._v3_fold_jump_count = 0

    # ------------------------------------------------------------------ #

    def _v3_build_transition(self, n: int) -> np.ndarray:
        """Dense transition matrix: drift kernel + symmetric fold jumps
        + novelty leak. Built once (a few hundred states — cheap)."""
        lb = self._v3_log_bpms
        d = lb[None, :] - lb[:, None]                     # log2 tempo delta
        t = np.exp(-0.5 * (d / self._v3_drift_sigma) ** 2)
        for ratio, mass in ((2.0, self._v3_fold_octave),
                            (1.5, self._v3_fold_triplet),
                            (4.0 / 3.0, self._v3_fold_triplet)):
            lr = math.log2(ratio)
            # symmetric: up AND down get identical mass (requirement #1)
            t += mass * np.exp(-0.5 * ((np.abs(d) - lr) / self._v3_drift_sigma) ** 2)
        t += self._v3_novelty
        t /= t.sum(axis=1, keepdims=True)
        return t

    def _v3_build_templates(self, acf_bpms_full: np.ndarray) -> np.ndarray:
        """Predicted comb profile per lattice tempo over the ACF grid.

        Mirrors v2's comb exactly: comb(x) = sum_h A(h * lag_x) / h with
        lag_x = 60 * _V2_ENV_RATE / x, where A is the ideal ACF of a beat
        train at tempo s: Gaussian spikes at k * P_s (decaying) plus weaker
        ones at the half-beats. Rows are L2-normalised so a cosine match
        is one matvec per cycle.
        """
        lag_x = 60.0 * _V2_ENV_RATE / acf_bpms_full.astype(np.float64)   # (G,)
        p_s = 60.0 * _V2_ENV_RATE / self._v3_bpms                          # (S,)
        sig2 = 2.0 * self._v3_tmpl_sigma ** 2
        tmpl = np.zeros((len(p_s), len(lag_x)), dtype=np.float64)
        for h in range(1, _V2_COMB_HARMONICS + 1):
            lag_h = h * lag_x                                              # (G,)
            for k in range(1, self._v3_tmpl_beats + 1):
                w = self._v3_tmpl_decay ** (k - 1)
                centre = k * p_s[:, None]                                  # (S,1)
                tmpl += (w / h) * np.exp(-((lag_h[None, :] - centre) ** 2) / sig2)
                half = (k - 0.5) * p_s[:, None]
                tmpl += (w * self._v3_tmpl_subbeat / h) * np.exp(-((lag_h[None, :] - half) ** 2) / sig2)
        norms = np.linalg.norm(tmpl, axis=1, keepdims=True)
        return tmpl / np.maximum(norms, 1e-12)

    def prime_tempo(self, bpm: float, *, confidence: float = 0.9) -> None:
        """External ground-truth prime: v2 behaviour plus a posterior seed and a
        held prior centre at the primed tempo (phase 4)."""
        super().prime_tempo(bpm, confidence=confidence)
        b = float(bpm)
        if not (self._v3_bpms[0] <= b <= self._v3_bpms[-1]):
            return
        z = (self._v3_log_bpms - math.log2(b)) / max(1e-6, self._v3_prime_sigma)
        seed = np.exp(-0.5 * z * z) + 1e-4
        self._v3_posterior = seed / seed.sum()
        self._v3_prime_mu = b
        now = float(getattr(self, '_last_t', 0.0) or 0.0)
        # Hold starts at the first update when primed before the clock runs
        # (-1 = resolve lazily); every re-prime refreshes it, so a source that
        # keeps republishing (tagged track) holds, and one that stops (next
        # track untagged, hint stale) lets the correction lapse after hold_s.
        self._v3_prime_until_t = (now + self._v3_prime_hold_s) if now > 0.0 else -1.0
        self._v3_prime_count += 1

    def _v3_prior_centre(self) -> tuple[float, float]:
        """(mu, sigma) for the per-cycle prior bias: the primed centre while its
        hold is in force, otherwise the profile prior (floored sigma)."""
        now = float(getattr(self, '_last_t', 0.0) or 0.0)
        if self._v3_prime_mu > 0.0:
            if self._v3_prime_until_t < 0.0 and now > 0.0:
                self._v3_prime_until_t = now + self._v3_prime_hold_s   # clock started after the prime
            if self._v3_prime_hold_s <= 0.0 or self._v3_prime_until_t < 0.0 or now <= self._v3_prime_until_t:
                return self._v3_prime_mu, self._v3_prime_sigma
        mu = float(getattr(self, '_prior_mu', 120.0) or 120.0)
        sigma = max(0.35, float(getattr(self, '_prior_sigma', 0.55) or 0.55))
        return mu, sigma

    def _v3_density_likelihood(self) -> np.ndarray | None:
        """Onset-density channel (phase 4): penalise lattice tempos faster than
        _V3_DENSITY_FAST_RATIO x the observed onset rate. None when off or
        when no density measure is available yet."""
        if self._v3_density_weight <= 0.0:
            return None
        dens = float(getattr(self, '_last_acf_density_bpm', 0.0) or 0.0)
        if dens <= 0.0:
            return None
        excess = self._v3_log_bpms - math.log2(dens * self._v3_density_fast)   # > 0 = too fast
        fall = np.exp(-0.5 * (np.clip(excess, 0.0, None) / max(1e-6, self._v3_density_sigma)) ** 2)
        like_d = np.clip(fall, self._v3_density_floor, 1.0) ** self._v3_density_weight
        return like_d

    def _v3_apply_density(self, like: np.ndarray) -> np.ndarray:
        like_d = self._v3_density_likelihood()
        if like_d is None:
            return like
        idx = int(np.argmax(like))
        if like_d[idx] < 1.0:
            self._v3_density_engaged_count += 1
        return like * like_d

    def _v3_observation_likelihood(self) -> np.ndarray | None:
        obs = getattr(self, '_last_acf_observation', None)
        if obs is None:
            return None
        acf_bpms, comb, cycle = obs
        # Once per ACF cycle (~7.4 Hz), never per 60 Hz tick. 2026-09-03: the
        # template/hybrid branch used to sit ABOVE this check and was applied
        # on every tick (~8x per cycle, evidence to the 8th power) -- found
        # by a probe during phase 3; bake 3 ran with that behaviour.
        if len(comb) < 4:
            return None
        per_cycle = self._v3_obs_apply != 'tick' or self._v3_obs_source in ('comb', 'score')
        if per_cycle and cycle == self._v3_seen_cycle:
            return None
        self._v3_seen_cycle = int(cycle)
        if self._v3_obs_source in ('template', 'hybrid'):
            n = len(comb)
            key = (n, float(acf_bpms[0]), float(acf_bpms[n - 1]))
            if self._v3_templates is None or self._v3_templates_key != key:
                # Keyed on the observation's OWN grid (in production a prefix of
                # self._acf_bpms; an observation on any other grid must not
                # silently mis-match -- found writing the phase-2 tests).
                self._v3_templates = self._v3_build_templates(np.asarray(acf_bpms[:n], dtype=np.float64))
                self._v3_templates_key = key
            obs = np.clip(comb.astype(np.float64), 0.0, None)
            on = float(np.linalg.norm(obs))
            if on <= 0.0:
                return None
            t = self._v3_templates[:, :n]
            tn = np.linalg.norm(t, axis=1)
            match = (t @ obs) / (np.maximum(tn, 1e-12) * on)        # cosine in [0,1]
            if self._v3_obs_source == 'hybrid':
                # Shape match alone cannot settle the octave (a track's comb
                # looks like 2T's template too); the comb's own magnitude at
                # s can (1/h harmonic weights favour T over 2T). Multiply.
                order = np.argsort(acf_bpms[:n])
                xb = np.log2(acf_bpms[:n][order].astype(np.float64))
                yc = obs[order] / max(1e-12, float(obs.max()))
                mag = np.interp(self._v3_log_bpms, xb, yc, left=0.0, right=0.0)
                match = match * np.clip(mag, 0.05, None)
            floor = self._v3_obs_floor
            like = np.clip(match / max(1e-9, float(match.max())), floor, None) ** self._v3_obs_power
            if self._v3_prior_mode == 'percycle':
                mu, sigma = self._v3_prior_centre()
                z = (self._v3_log_bpms - math.log2(max(1.0, mu))) / sigma
                like *= (np.exp(-0.5 * z * z) * 0.5 + 0.5) ** self._v3_prior_gain
            return self._v3_apply_density(like)
        if self._v3_obs_source == 'score':
            sc = getattr(self, '_last_acf_score', None)
            if sc is not None and len(sc) == len(comb):
                comb = sc
        # comb is indexed by ACF lag (descending bpm) — resample onto the
        # lattice over log-tempo. Outside the ACF's bpm span, fall back
        # to the observation floor rather than zero (those lattice states
        # live on fold evidence + transitions until in-span).
        order = np.argsort(acf_bpms)
        xb = np.log2(acf_bpms[order].astype(np.float64))
        yc = np.clip(comb[order].astype(np.float64), 0.0, None)
        peak = float(yc.max())
        if peak <= 0.0:
            return None
        yc /= peak
        floor = self._v3_obs_floor
        like = np.interp(self._v3_log_bpms, xb, yc, left=floor, right=floor)
        # Fold-aware observation: a state whose DOUBLE or HALF tempo has
        # comb support is itself supported (the observation analog of the
        # comb's own harmonic stacking, extended symmetrically so fast
        # lanes see the evidence that v2's descent only ever used to
        # fold DOWN).
        up = np.interp(self._v3_log_bpms + 1.0, xb, yc, left=0.0, right=0.0)
        down = np.interp(self._v3_log_bpms - 1.0, xb, yc, left=0.0, right=0.0)
        like = like + self._v3_fold_obs_weight * np.maximum(up, down)
        like = np.clip(like, floor, None) ** self._v3_obs_power
        # Weak profile prior (phase 1: same role as v2's floored prior,
        # expressed as an observation bias; evidence gating is phase 2).
        if self._v3_prior_mode == 'percycle':
            mu, sigma = self._v3_prior_centre()
            z = (self._v3_log_bpms - math.log2(max(1.0, mu))) / sigma
            like *= (np.exp(-0.5 * z * z) * 0.5 + 0.5) ** self._v3_prior_gain   # bounded bias, never a veto
        return self._v3_apply_density(like)

    def update(self, *args, **kwargs):  # noqa: ANN002, ANN003
        result = super().update(*args, **kwargs)
        like = self._v3_observation_likelihood()
        if like is not None:
            post = self._v3_transition.T @ self._v3_posterior
            post *= like
            total = float(post.sum())
            if total > 0:
                self._v3_posterior = post / total
                prev_bpm = self._bpm
                idx = int(np.argmax(self._v3_posterior))
                half_band = math.log2(1.0 + _V3_CONF_BAND)
                lb = self._v3_log_bpms
                map_bpm = float(self._v3_bpms[idx])
                band = np.abs(lb - lb[idx]) <= half_band
                conf = float(self._v3_posterior[band].sum())
                fs = 0.0
                for ratio in _V3_FOLD_SUSPECT_RATIOS:
                    fb = np.abs(lb - (lb[idx] + math.log2(ratio))) <= half_band
                    fs += float(self._v3_posterior[fb].sum())
                self._v3_fold_suspect_mass = fs
                self._v3_cycle_applied_count += 1
                if prev_bpm > 0 and abs(math.log2(max(1e-6, map_bpm / prev_bpm))) > 0.2:
                    self._v3_fold_jump_count += 1
                # The override: the posterior IS the decision.
                self._bpm = map_bpm
                self._confidence = conf
        return result
