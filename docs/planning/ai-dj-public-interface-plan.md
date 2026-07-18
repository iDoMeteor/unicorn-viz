---
Owner: Planning
Status: APPROVED (architecture + owner decisions §10 recorded 2026-07-17); no
code yet, M0 not started. Ships as the commercial `dj-mixer-pro` drop-in.
Supersedes the "AI v Human mode" placeholder noted in the dj-mixer plan.
Last updated: 2026-07-17
---

# AI DJ + Public System Interface — Plan

An **AI DJ** that can *actually run the decks* — pick tracks, beatmatch,
harmonic-mix, ride EQ/FX, throw transitions — and, because it needs to reach so
much, a **public system-control interface** that exposes the whole rig
(mixer + visuals + analysis + library) through one bounded, documented surface.
Built to work **tightly but not dependently** with `auto-vj-01`: they share
signals and can orchestrate each other, but either runs fine alone.

This document is the authoritative scope + build order. Update the **Status**
header and milestone checkboxes as work lands.

---

## 1. Vision & goals

- A DJ can hand the set to the machine and it keeps a **musically coherent,
  harmonically-aware, beatmatched** flow going — the auto-play + SYNC + KEY +
  scratch-transition primitives already in `dj-mixer-01`, orchestrated with
  taste instead of a fixed end-of-track trigger.
- The same control surface is **public**: the AI DJ is one client; a human tool,
  a remote agent, or a test harness are others. One API, many drivers.
- **Tight, not dependent** with `auto-vj-01`: the visual director and the audio
  DJ share beat/energy/structure/now-playing signals and can hint each other
  ("building to a drop", "just dropped a banger"), but neither imports the other
  and each degrades gracefully when the other is absent.
- **Human always wins.** The AI operates through a bounded vocabulary with hard
  guardrails, a global enable, an instant hard-stop, and full manual override.

**Non-goals (v1):** replacing the human's creative direction; streaming/network
control from the open internet; training a bespoke mix-selection model. These
are later phases or explicitly out of scope.

---

## 2. Prior art in this repo (what we build on)

The patterns are already established — the AI DJ should extend them, not invent
parallel ones.

- **`VJApi`** (`unicornviz/vj_api.py`, ~1.8k lines) is the canonical public
  control surface for the *visual* side: effect selection, projectM, postfx,
  audio-source/MIDI selectors, modals, `publish_bpm`/`get_bpm`,
  `register_now_playing`, and a generic dotted-path **runtime-state bus**
  (`get/set_runtime_state`). Drop-ins reach it via `app.vj_api` **only** — never
  app internals (see the `auto_vj.py` docstring: *"app … accessed only via
  app.vj_api"*).
- **Subsystem registry** — `vj_api.register_subsystem/get_subsystem/
  has_subsystem/list_subsystems`. This is the sanctioned way for drop-ins to
  find each other at runtime without hard imports: exactly the "tight but not
  dependent" mechanism.
- **`auto-vj-01`** is the reference automation controller: a
  `BeatGridTracker` (BPM/phase/energy/drop-score), a director state machine
  (Cruise → Build → Drop → Breakdown/Impact/Climax → Ping-Pong), an
  `ActionEngine` with per-action cooldowns and a JSONL decision log, mood
  profiles, and a "manual grace period" that respects user control. Its
  numeric decisions are tracked in `docs/adr/vj-system.md`.
- **`dj-mixer-01`** already has the DJ *primitives*: four decks, transport,
  3-band EQ, filter, per-channel FX (un-master-bussed), crossfade, SYNC/beatmatch,
  KEY harmonic-match, 🔒 set-and-forget locks, auto-play (cut/crossfade), the new
  scratch-transition, a hash-keyed track store (BPM/key/cues/grid), and a
  library/browser with harmonic + tempo compatibility signals.

The AI DJ is the **conductor** over those primitives; the public interface is
the **baton** it (and others) hold.

---

## 3. Architecture

### 3.1 Three layers

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Drivers   AI-DJ controller │ human tools │ remote client    │
   │            (new drop-in)    │             │ (later phase)     │
   └───────────────┬─────────────────────────────────────────────┘
                   │  bounded action vocabulary + telemetry
   ┌───────────────▼─────────────────────────────────────────────┐
   │  DjApi  (new public facade — registered as a subsystem)      │
   │   • composes: MixerEngine control + VjApi visuals +          │
   │     analysis (beat/energy/structure) + library/now-playing   │
   │   • one read (telemetry) surface + one write (action) surface│
   │   • guardrails, rate limits, audit log, authority arbitration│
   └───────────────┬─────────────────────────────────────────────┘
                   │  public methods only (no private state)
   ┌───────────────▼─────────────────────────────────────────────┐
   │  Existing systems                                            │
   │   dj-mixer-01 engine │ VjApi/effects/postfx │ auto-vj signals│
   └──────────────────────────────────────────────────────────────┘
```

- **`DjApi`** is a new public facade (analogous to `VjApi`, sitting beside it).
  It is **registered as a subsystem** (`vj_api.register_subsystem('dj_api', …)`)
  so any driver reaches it with `vj_api.get_subsystem('dj_api')` — no hard
  import, graceful absence.
- The **AI-DJ controller** is a **separate drop-in** (`dj-mixer-pro`, private repo +
  submodule, per the Drop-In Source Policy). It drives the set through `DjApi`
  (mix/decks/FX) and `VjApi` (visuals), and **never** touches
  `dj-mixer-01`/app internals directly.
- **`DjApi` composes, it doesn't reimplement.** Deck/mix control forwards to the
  mixer engine's public methods; visual actions forward to `VjApi`; analysis
  reads from whichever beat tracker is authoritative (see §5).

### 3.2 Why a new facade instead of stuffing it into `VjApi`

`VjApi` is the *visual* runtime's surface and is already large. The DJ domain
(decks, tracks, mix, cue, transitions) is a distinct bounded context with its
own vocabulary and guardrails. A separate `DjApi` keeps each surface coherent,
lets the mixer own its control contract, and means the AI DJ can be developed
and versioned on its own cadence. The two facades **compose** at the driver
layer, they don't merge.

### 3.3 Read/write split

- **Telemetry (read):** a single snapshot the driver polls or subscribes to —
  per-deck state (loaded track, position, bpm, key, pitch, playing, level,
  sync/lock flags, stems), master/crossfader/VU, beat phase + energy + section
  estimate, the library's compatible-next candidates, now-playing. Cheap,
  allocation-light, safe to call every tick.
- **Actions (write):** a **closed vocabulary** of intents, each idempotent and
  guard-checked. Examples: `load(deck, track_id)`, `play/pause(deck)`,
  `set_tempo/pitch/eq/filter/gain(deck, …)`, `crossfade_to(deck, seconds,
  curve)`, `sync(deck)`, `key_match(deck)`, `select_fx(unit, slot)`,
  `engage_fx(unit, wet)`, `scratch_transition(...)`, `cue(deck)`,
  `suggest_next(constraints) -> candidates`. Higher-level composite intents
  (`mix_into(track_id, bars, style)`) are built from these.

---

## 4. Capabilities the interface must expose

| Domain | Read (telemetry) | Write (actions) |
|---|---|---|
| Decks | track, pos, bpm, key, pitch, playing, level, sync/lock, stems | load, play/pause, cue, set pitch/tempo/eq/filter/gain, key-shift |
| Mix | crossfader, master, per-channel levels, VU | crossfade_to (timed, curved), set crossfader, master gain |
| Sync | per-deck synced/keyed/locked, anchor | sync, key_match, set/clear 🔒 locks, auto-desync toggles |
| FX (per-channel) | selected slot, on, lock, dry/wet, macro | select slot, engage/lock, set wet/macro, (later) per-stem FX mask |
| Transitions | — | cut, timed crossfade, scratch-transition (backspin/spin-up) |
| Stems | per-deck stems present, gains, solo | set stem gain/mute/solo, (later) stem-FX send mask |
| Library | compatible-next candidates (key+tempo+energy), history | search/filter, suggest_next(constraints), reveal/select |
| Analysis | bpm, beat phase, downbeat, energy, section (intro/build/drop/break) | (read-only; publish hints, see §5) |
| Visuals | current effect, projectM state (via VjApi) | goto/lock effect, postfx, overlay hits (via VjApi) |
| Now-playing | current track + change counter | — |
| Meta | AI-DJ enabled, authority owner, last-action log tail | enable/disable, hard-stop, set authority |

Anything not on the write list is **not** AI-reachable in v1 (e.g. no file
deletion, no config writes, no destructive library ops).

---

## 5. Coordination with `auto-vj-01` (tight, not dependent)

Both consume audio and make musical decisions; they must not fight or double up.

- **Shared analysis, single authority.** Beat/energy/section detection should
  have **one** authoritative producer per run, published on a bus the other
  reads — reuse `publish_bpm`/`get_bpm` and add a small **structure/energy
  channel** on the runtime-state bus (`set_runtime_state('music.section', …)`,
  `music.energy`, `music.downbeat_at`). When the mixer is live it is the natural
  authority (it *has* the decoded tracks, grids, and cue points); auto-vj
  consumes those instead of re-deriving from the room mic. When the mixer is
  idle, auto-vj's `BeatGridTracker` is authority. Whoever is authoritative
  declares it via a registry flag; the other follows. (ADR-worthy — see §8.)
- **Director hints, not commands.** The AI DJ publishes intent hints
  ("building", "drop in N beats", "breakdown") that `auto-vj-01` *optionally*
  consumes to pre-arm a visual Build/Drop — and vice versa, auto-vj can expose
  its director state for the DJ to sync a transition to a visual climax.
  Consumed opportunistically; neither blocks on the other.
- **Absence is graceful.** No hard imports: discovery via `get_subsystem`,
  every cross-call guarded, sensible fallback when the peer is missing (exactly
  the drop-in independence rule). auto-vj already degrades without postfx-01 /
  unicorn-tears-01; the DJ↔VJ link follows the same discipline.

---

## 6. The controller: heuristic first, LLM later

- **Phase A — deterministic auto-DJ.** A rules engine over the primitives:
  pick a harmonically-compatible, tempo-close next track (the browser already
  scores green/magenta/±BPM); load to the idle deck; pre-sync via the 🔒 locks
  (already lands on load); at a musically sensible point run a timed crossfade
  (or the scratch-transition when incompatible); ride a filter/echo on the
  outgoing tail. This is largely *orchestration* of shipped features + the
  auto-vj `ActionEngine` cooldown/grace pattern. Fully testable offline.
- **Phase B — LLM planner on top.** The LLM issues **high-level intents** over a
  short horizon ("mix the next 8 bars into an energy build, harmonic step up,
  8-bar blend, filter sweep on the outgoing") given a compact telemetry
  snapshot + candidate list. `DjApi` executes and reports back; the LLM never
  touches audio in the hot path — it plans on a slow loop (seconds), the
  deterministic layer handles beat-accurate execution. Model default per repo
  standard (latest Claude). This is where the "*thinking*, not just smart"
  behavior the owner wants lives.
- **Reuse auto-vj scaffolding:** per-action cooldowns, the manual grace period,
  the JSONL decision log, mood/energy profiles, and a `toggle()` hotkey.

---

## 7. Safety, authority & guardrails

- **Global enable + hard-stop.** `[ai_dj] enabled = false` by default; a hotkey
  toggle; an instant hard-stop that releases control to the human mid-action.
- **Authority arbitration.** One owner of each deck at a time
  (`human` | `ai_dj`); any human input on a deck **immediately** reclaims it and
  arms an auto-vj-style grace period before the AI may touch it again.
- **Bounded vocabulary + rate limits.** Only the §4 write list; per-action
  cooldowns; clamped parameter ranges; no destructive ops; no config/file
  writes; no network from the runtime (repo security rule).
- **Auditability.** Every AI action logged (JSONL, timestamped) like auto-vj,
  for review and offline tuning.
- **Fail safe, not silent.** If `DjApi` or a peer is unavailable the AI DJ
  disables itself with a clear log line and hands back to the human.

---

## 8. Standards this must follow

- **Drop-in independence:** `dj-mixer-pro` is its own private repo + submodule; core
  never hard-depends on it; all cross-drop-in access via `get_subsystem` +
  try/except with graceful fallback.
- **Public-surface discipline:** drivers touch only `DjApi`/`VjApi` public
  methods, never `app._private` or `mixer._private`. Any new capability is a new
  public method on the facade first (the `# noqa: SLF001` owner-module rule).
- **MIDI policy:** all controller work stays in the owning drop-in; the DJ API
  exposes *logical* actions, not raw MIDI.
- **Versioning:** SemVer per component; `DjApi` and `dj-mixer-pro` versioned
  independently; changelog + README header per change.
- **ADRs:** add an AI-DJ section (or a new ADR) for the authority-arbitration
  model, the analysis-authority handoff between mixer and auto-vj, and any
  numeric thresholds (grace period, transition timing, energy bands) — mirror
  `docs/adr/vj-system.md`.
- **Docs SOP:** this plan lives in `docs/planning/`, linked from
  `docs/README.md`; the drop-in keeps `operations/configuration/integration/
  troubleshooting.md` under `drop-ins/dj-mixer-pro/docs/`.

---

## 9. Milestones (proposed build order)

- [ ] **M0 — `DjApi` read surface.** A registered subsystem exposing the
  telemetry snapshot (decks, mix, sync, FX, stems, analysis, candidates). No
  writes. Lets any driver *observe* the whole system. Unit-testable headless.
- [ ] **M1 — `DjApi` write surface.** The bounded action vocabulary forwarding
  to mixer/VjApi public methods, with guardrails, clamps, rate limits, authority
  arbitration, and the audit log. Still no autonomous controller.
- [ ] **M2 — `dj-mixer-pro` deterministic auto-DJ.** Harmonic/tempo track selection
  + pre-synced load + timed/scratch transitions + tail FX, driven purely through
  `DjApi`. Cooldowns + manual grace. The first hands-free set.
- [ ] **M3 — DJ↔VJ coordination bus.** Structure/energy/section channel +
  director hints; analysis-authority handoff; auto-vj consumes DJ hints and
  vice-versa. Both still run independently.
- [ ] **M4 — LLM planner.** High-level intent planning on a slow loop over the
  telemetry + candidate snapshot; deterministic layer executes beat-accurately.
- [ ] **M5 — external/public interface.** Out-of-process access (local IPC /
  socket) so non-in-process clients can drive `DjApi` — scoped, authenticated,
  read-first. (Design only until earlier phases are solid.)

---

## 10. Decisions (owner, 2026-07-17)

1. **Analysis authority — DECIDED.** Mixer wins when a deck is live, auto-vj
   when idle. (ADR-worthy handoff.)
2. **`DjApi` home — DECIDED.** Lives **inside `dj-mixer-01`** (it wraps that
   engine), registered on `vj_api` so it's globally discoverable.
3. **LLM leash — DECIDED: full autonomy.** The planner gets full track
   selection + transitions from the start — no "suggest, human confirms" gate.
   The safety rails still stand (global enable, instant hard-stop, per-deck
   authority arbitration that any human touch reclaims, clamps, audit log): the
   *human can always seize control*, but the AI isn't asked to pre-clear moves.
4. **"Others" / M5 scope — OPEN.** Owner flagged M5 as undecided ("m5??").
   Parked: the external/out-of-process interface is design-later, and whether
   it's owner-tools-only or a shared/public surface (which sets the auth bar) is
   still to be settled. Earlier milestones don't depend on it.
5. **Move vocabulary — DECIDED: all of them in v1.** The full flourish set is
   AI-selectable from the start — scratch-transition (backspin/spin-up), filter
   sweeps, echo/reverb tails, loop rolls, and later per-stem FX. "We've got
   time" — build the vocabulary broad.
6. **Packaging — DECIDED: `dj-mixer-pro`, commercial.** The AI DJ ships as the
   **`dj-mixer-pro`** drop-in — the paid/pro tier over the free `dj-mixer-01`.
   Same drop-in standards (private repo + submodule, independence, versioning);
   the monetization boundary is the AI conductor + `DjApi`-driven autonomy, not
   the base mixer.
7. **Cross-registration — DECIDED.** The link is **bidirectional**: `DjApi`
   registers on `vj_api`, *and* the VJ side (auto-vj) is discoverable to the DJ.
   Recorded in the VJ plan too (see `docs/planning/` auto-vj docs / ADR) so both
   sides document the handshake. Discovery via `get_subsystem`, every cross-call
   guarded — neither hard-depends on the other.
8. **Training kit — LEAN: extend `training-kit-01`.** The DJ needs a training
   pipeline like the VJ's, and `training-kit-01` already owns the packaging /
   scorecard / session-log machinery. Proposal: **add a DJ track to
   `training-kit-01`** (shared tooling, DJ-specific corpus schema + scorecard
   metrics: beatmatch accuracy, harmonic-compatibility rate, transition
   smoothness, crowd-energy proxy) rather than spin up a parallel kit — split
   only if it grows unwieldy. Owner to confirm extend-vs-new.

---

## 11. Relationship to the platter-spin (worth-it note)

The scratch-transition cost the pipeline very little (a decayed `_spin_vel`
term in `render`; the platter visual is free since it tracks the playhead) and
it's exactly the kind of **human-feel flourish the AI DJ will want in its
vocabulary**. It earns its keep less as an auto-play gimmick and more as a
*named move* the conductor can call — which is precisely why it's worth having
now, ahead of the AI DJ that will wield it.
