# Scorecard — unicorn-viz vs the visualizer / VJ field

Owner: DJ Unicorn Tears
Status: preliminary (core 1.0.0-beta.44, pre-RC1)
Last updated: 2026-08-07

Honest grades, not homerism: the plan is to find every category where a
competitor holds an A that we don't, and flip it — or decide out loud that
we're not in that fight. **Bold** = roadmap item already on the open list.

Compared: **Resolume** (Avenue €299 / Arena €799 — the industry standard),
**Synesthesia** ($199 / $399 Pro — the closest thing to a direct rival),
**Magic Music Visuals** (~$45, node-based), **TouchDesigner** (free
non-commercial / $600 commercial — the generative-art heavyweight),
**projectM** (free/LGPL — the open-source MilkDrop engine we also embed),
and **VDMX** ($199 / $349 Plus — Mac-only, the Mac VJ standard).
Competitor facts were web-researched 2026-08-07 with sources listed at the
bottom; anything that could not be verified from a real source is called out
as *unverified* rather than graded confidently. A dash (—) means the product
does not have the feature at all.

**A+** is reserved for a category where the field has *nothing comparable* —
not "we do it better", but "no shipping product does this". Everything else
tops out at A. Competitor grades stay conservative.

**A note on what this table is measuring.** Most of these products are
*VJ instruments* — a human drives them, and the software's job is to be
expressive under their hands. unicorn-viz is a **self-driving visual rig
attached to a DJ setup**. Several rows below are therefore ours by default,
and several are theirs by default. That asymmetry is the most useful thing
in the table, and §"Currently non-compete" is where the honesty lives.

| Category | Us | Resolume | Synesthesia | Magic | TouchDesigner | projectM | VDMX | Notes |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| **Overall grade** | **B+** | **A** | **A−** | **B+** | **A** | **B+** | **A−** | Us: three genuine A+ rows (musical intelligence, DJ/set integration, unattended operation) and a free, open, hackable architecture — held back from A by **maturity** (13 weeks old), a **missing video-interop path** (no NDI/Spout/Syphon, the one row where we're beaten by everybody), and **OS reality** (Linux-solid, Windows rough, macOS absent).<br>Resolume: the industry standard for live visual performance — deepest content ecosystem, mature interop, projection mapping in Arena. The benchmark.<br>Synesthesia: purpose-built music visualizer, closest in *intent* to us; strong shader ecosystem and audio uniforms, weaker on autonomy and output-format breadth.<br>Magic: node-based visual synth, remarkable value, but a smaller ecosystem and a dated UI.<br>TouchDesigner: not a visualizer but a visual *programming environment* — can build anything here given enough weeks, which is exactly its cost.<br>projectM: the open MilkDrop engine (LGPL, 2003). Unmatched preset library, runs everywhere; a rendering library rather than a show rig.<br>VDMX: the Mac VJ standard — modular, deeply configurable, superb interop. Mac-only is its whole story. |
| **Years in development** (as of 2026) | <1 (pre-RC1) | ~24 | ~9 | ~13 | ~26 | ~23 | ~22 | Us: first commit 2026-05-05.<br>Resolume: 2002 lineage.<br>Synesthesia: ~2017.<br>Magic: ~2013.<br>TouchDesigner: Derivative founded 2000, TD lineage from Houdini-era tooling.<br>projectM: initiated 2003, LGPL v2.1.<br>VDMX: VIDVOX shipped VDMX in the early 2000s; VDMX6 is current. |
| **OS support** | **C+** | B+ | B+ | B+ | B+ | **A** | C | Us: **Linux is excellent** (Fedora/Arch, Wayland-native, PipeWire) and is where all development happens. **Windows is the declared primary release target but is the weakest link today** — it runs, but the dependency stack still needs a MinGW toolchain and a hand-patched `python-rtmidi` on current Python, the installer is ★1 of 5, and DPI/multi-head fixes shipped only this week and are *not yet hardware-verified*. **macOS: planned, nothing shipped.** Graded on delivered reality, not intent — this is the row most likely to move before 1.0.<br>Resolume / Synesthesia / Magic / TouchDesigner: Windows + macOS with polished installers; **no Linux** on any of them (TouchDesigner explicitly Windows/macOS only; Linux via Wine is unofficial).<br>projectM: **the breadth winner** — Linux, Windows, macOS, Android, and OpenGL-ES embedded targets. Nobody else here spans that.<br>VDMX: **macOS only.** |
| **Price** | **A** | C | C+ | B+ | B | **A** | B− | Us: free, MIT-licensed, no tiers, no gates.<br>Resolume: Avenue €299 / Arena €799, perpetual.<br>Synesthesia: $199 Standard / $399 Pro (Syphon/Spout/NDI + OSC are **Pro-gated**); free tier is watermarked.<br>Magic: ~$45 one-time — the value pick of the paid field.<br>TouchDesigner: genuinely free non-commercial but **capped at 1280×1280 output**, which rules out real shows; $600 commercial, $300 education.<br>projectM: free, LGPL — ties us.<br>VDMX: $199 / $349 Plus. |
| **Musical intelligence** (tempo, genre, structure → *decisions*) | **A+** | C | C+ | C− | C | C− | C | Us: this is the whole thesis. In-house BPM/beat-grid tracker (ACF + phase-locked oscillator, comb-filter harmonic scoring, tactus fold-down), **20 genre audio profiles** with per-genre priors that the recommender selects *from the audio*, drop/build/breakdown detection with a phrase clock, and an **Auto VJ director** that uses all of it to decide what to show and when to cut. It consumes the DJ mixer's own deck analysis as ground truth when a deck is playing.<br>**The distinction that earns the A+:** every product below can make a parameter *follow* audio. None of them makes a *decision* from it. FFT-to-parameter is a wire; choosing the next effect because the track is 128 BPM peak-time house entering a breakdown is a judgement, and no shipping product in this table attempts it.<br>Resolume: mature FFT band routing (bass/low-mid/high-mid/treble to any parameter) + BPM sync via Ableton Link/SMPTE/ProDJLink — excellent *plumbing*, no autonomy.<br>Synesthesia: rich audio uniforms (`syn_BassLevel`, `syn_HighHits`, `syn_Presence`) — the best audio-feature vocabulary of the rivals, still parameter-level.<br>Magic / TouchDesigner / VDMX: FFT + envelope followers you wire yourself.<br>projectM: per-preset beat detection, no cross-preset intelligence. |
| **DJ / set integration** | **A+** | B− | — | — | — | — | — | Us: ships **with a two-deck DJ mixer** (`dj-mixer-01`, DDJ-REV1 + S4 MK3) that publishes deck BPM, song structure, a **set clock**, and a **grand-finale hand-off** — the visuals know the last track has started, how long is left, and where its biggest drop lands.<br>Resolume: the best of the rivals here — SMPTE timecode (two simultaneous inputs), Ableton Link, ProDJLink — but these are *clock* protocols. They tell Resolume the tempo and position; they do not tell it that the set is ending, that this is the final track, or where the drop is.<br>Everyone else: no DJ integration beyond generic audio input.<br>This row exists because the two halves ship together. It is the clearest case in the table of the product being worth more than its parts. |
| **Unattended / autonomous operation** | **A+** | C− | C | D | C | B | C | Us: designed to run a whole night with nobody at the keyboard — auto-advance, Auto VJ direction, playlist/set awareness, `--media-source` headless boot, auto-play, session-end detection, crash containment that **quarantines a broken effect and keeps the show running**, and a training daemon for unattended capture.<br>Resolume/VDMX/TouchDesigner/Magic: can loop a composition indefinitely, but the *selection* is a fixed playlist or a human. A crash is a stopped show.<br>projectM: closest of the field — it will happily cycle presets forever as a screensaver, which is real autonomy, just not *directed* autonomy (B).<br>Nobody else treats "the operator walked away and the show must still be good in an hour" as the design centre. |
| **Video output interop** (NDI / Spout / Syphon) | **D** | **A** | A | B+ | A | — | **A** | **The one row we lose to almost everybody, and it is not close.** Us: **nothing.** No NDI, no Spout, no Syphon. Output is our own window(s), a recording file, or an RTMP stream. To get unicorn-viz into OBS today you screen-capture a window — which works, but costs a copy and hands the compositor a job it shouldn't have.<br>Resolume: Spout/Syphon/NDI in and out, the reference implementation.<br>Synesthesia: full Syphon/Spout/NDI — but **Pro tier ($399) only**.<br>Magic: Spout/Syphon output (*NDI unverified*).<br>TouchDesigner: everything, plus SDI/Blackmagic hardware I/O.<br>VDMX: Syphon is native to how Mac VJs work; excellent.<br>projectM: a rendering library — interop is whatever the host app provides.<br>**This is the highest-value single flip on the board.** Spout (Windows) and NDI would put us inside every OBS/Resolume rig in the world, and Windows is our declared primary target. |
| Effects / content library | A− | **A** | A− | B+ | B | **A** | B+ | Us: **64 effects across 12 packs** — raymarched scenes, CPU-simulated arcade games, particle systems, ANSI/demoscene, plus **the entire MilkDrop preset universe via the embedded projectM host** (130k+ presets exist in the community MegaPack). Every effect is audio-reactive by construction and randomizes per activation, so the same effect twice is never the same picture. Conceded: no commercial content marketplace, and our shaders are ours alone — nobody is selling packs for us.<br>Resolume: 100+ built-in effects/sources **plus the largest commercial VJ content ecosystem that exists** — that market is why this is an A and ours is an A−.<br>Synesthesia: 100+ scenes from 20+ artists, Shadertoy/ISF import — strong.<br>Magic: solid module library, smaller community.<br>TouchDesigner: no "library" — you build it. Enormous ceiling, empty floor.<br>projectM: **130k+ presets**; unmatched by volume, though MilkDrop-idiom only.<br>VDMX: ISF ecosystem + Shadertoy import. |
| Shader authoring / extensibility | A | A− | A | A− | **A** | B+ | A | Us: effects are plain Python + GLSL 330 files auto-discovered from drop-in packs — write a file, it appears in the browser. No SDK, no build step, no plugin registry. Conceded: no in-app live shader editor (edit, restart, see).<br>Resolume: ISF plugins + VST hosting; not a general programming surface.<br>Synesthesia: **first-class shader authoring** with Shadertoy/ISF converters and live editing — arguably the best pure shader workflow here.<br>Magic: node graph + GLSL modules.<br>TouchDesigner: **the ceiling** — GLSL, Python, C++ CHOPs, full node programming.<br>projectM: MilkDrop preset language (its own idiom, huge corpus, but not general-purpose).<br>VDMX: ISF authoring + live coding, excellent. |
| Multi-display output | A− | **A** | B | B | **A** | C | A− | Us: single / span-included / span-all / mirror-included / mirror-all, per-display viewport tiling, exclude-list, hot-plug rebuild — driven from config or hotkeys. Conceded: **the display-state re-derivation shipped this week and is not yet hardware-verified on mixed-DPI Windows**, and span mode never requests true compositor fullscreen (so the taskbar/panel can sit above it).<br>Resolume: multi-screen output with per-screen slicing; Arena adds projection mapping/edge blending. The reference.<br>TouchDesigner: arbitrary multi-window/multi-GPU output topology.<br>VDMX: strong multi-output on Mac.<br>Synesthesia/Magic: multi-monitor works, less topology control.<br>projectM: whatever the host window does. |
| MIDI control | A | **A** | A− | B+ | A | — | A | Us: full MIDI learn surface, CC→parameter and note→action maps in TOML, **plus deep hardware integration on the Akai APC mini mk2** (LED feedback via direct libusb writes, working around a kernel `snd_ump` regression) and the DDJ-REV1 through the mixer.<br>Resolume: comprehensive MIDI/OSC/DMX mapping, the standard.<br>Synesthesia: MIDI-mappable controls throughout.<br>TouchDesigner: MIDI/OSC/DMX/Art-Net as first-class operators.<br>VDMX: deep MIDI + OSC.<br>Magic: MIDI reactive, mapping less deep (*unverified* depth).<br>projectM: none natively. |
| OSC control | A− | A | A− | C | **A** | — | A | Us: `osc-bridge-01` — inbound UDP server on a daemon thread, enqueue-only, default **off** so no port opens unasked. Conceded: inbound-focused; we don't publish a rich outbound OSC state tree.<br>Resolume: full OSC in/out, documented address space.<br>Synesthesia: OSC in **and** out — **Pro tier only**.<br>TouchDesigner: OSC in/out as native operators, arbitrary schemas.<br>VDMX: deep OSC. |
| Recording / streaming | **A** | B+ | D | B | A− | — | B | Us: ffmpeg-backed capture with a **non-blocking bounded-queue writer thread** (a stalled encoder drops frames instead of freezing the show), plus **built-in RTMP streaming** with Rumble/YouTube/custom presets and stream-key masking in logs and HUD. Both survive a dead encoder now (kill escalation, failure surfaced to the operator).<br>Resolume: records composition output; streaming via NDI/Spout into OBS rather than a built-in RTMP path.<br>Synesthesia: **no recording** — it expects Syphon/Spout/NDI into something else.<br>Magic: renders to video file.<br>TouchDesigner: full record/stream pipelines, you build them.<br>VDMX: recording built in; RTMP typically via an external.<br>Ours wins on *built-in and direct* — no rival ships a one-key "go live to Rumble". |
| Projection-mapping-adjacent | C | **A** | C | B | **A** | — | A− | Kept in the scored table (unlike the mixer's non-competes) because it is the single biggest *capability* gap, even though it is out of scope for us. Us: viewport tiling and per-display placement only — no warping, no edge blending, no mesh mapping.<br>Resolume **Arena**: full mapping, warping, edge blending, SMPTE — the reason Arena costs €799.<br>TouchDesigner: arbitrary mapping via geometry.<br>VDMX: mapping via plugins/quad warping.<br>Magic: basic mapping.<br>Synesthesia: none.<br>**Not on the roadmap** — see non-compete. |
| Open architecture / hackability | **A** | C | C+ | C | A− | **A** | B− | Us: 39 independently versioned drop-in repos, TOML config, JSON runtime state, readable Python, a documented `VJApi` surface, and a core that **must** start cleanly with every drop-in absent (enforced by tests). Anyone can add an effect pack without touching core.<br>Resolume: closed; ISF plugins + VST hosting are the extension points.<br>Synesthesia: closed app, but scene/shader authoring is genuinely open-ended.<br>Magic: closed, module-based.<br>TouchDesigner: closed source but *infinitely* programmable — Python + C++ SDK (A−).<br>projectM: **LGPL open source** — ties us; embeddable as a library anywhere.<br>VDMX: closed, ISF/plugin extensible. |
| Demoscene / ANSI art | **A+** | — | — | — | — | — | — | Us: a full **CP437 ANSI art** subsystem — SAUCE-aware parser, authentic 8×16 VGA font atlas, GL texture builder, and committed art from the 16colo.rs ACiD packs, presented as a first-class effect with scroll and cycling.<br>**No product in this table has anything comparable**, and it isn't an oversight on their part — it's a deliberate heritage choice on ours. The BBS artscene is a 40-year-old visual tradition that no modern VJ tool represents at all. |
| Stability under long unattended runs | B+ | A | A− | B+ | A | A− | A− | Us: **1,413 green tests**, crash-containment that quarantines a failing effect rather than dying, idempotent teardown, faulthandler forensics, and a fixed float32 precision class that was silently killing effect layers over long sessions. Conceded honestly: **13 weeks old**, and the audit found real leaks (FBO attachments) and freezes (synchronous encoder writes) *this month*. Maturity is earned in rooms, not in test suites.<br>The paid field has 9–26 years of shipping and touring behind it. This row is theirs until we have the hours. |
| Documentation | A− | A | B+ | B | **A** | B | B+ | Us: a canonical `docs/` tree with user/developer guides, per-drop-in `operations`/`configuration`/`integration`/`troubleshooting` sets, ADRs recording *why* numeric constants are what they are, and dated audits. Conceded: internal-facing in places, and there is no video tutorial anywhere.<br>Resolume: excellent manuals plus a huge tutorial culture.<br>TouchDesigner: a legendary wiki + the largest learning community in this space.<br>Others: adequate-to-good docs, community-supplemented. |

## Currently non-compete

Different product, different fight — **not scored above** (except projection
mapping, which is scored precisely because it is the honest capability gap).
These are deliberate scope choices:

| Category | Us | The field | Why it's out of scope |
|---|:-:|---|---|
| Projection mapping & media-server duty | — | Resolume Arena, TouchDesigner, VDMX, HeavyM, MadMapper | Mapping a building is a different craft with different hardware. We aim at **one screen (or a mirrored wall of them) driven by the music**, not geometry correction on a venue façade. Scored above anyway, so the gap is visible rather than hidden. |
| DMX / Art-Net lighting control | — | Resolume, TouchDesigner (native), others via plugins | A lighting-desk fight. Our structural/phrase data is *published* for a lighting consumer to use — we would rather feed a light rig than become one. |
| Commercial content marketplace | — | Resolume (the largest), Synesthesia, VJ Galaxy et al. | An ecosystem/licensing play, not a code gap. Our answer is 64 open effects plus the entire MilkDrop preset corpus through projectM. |
| Hardware video I/O (SDI, capture cards) | — | TouchDesigner, Resolume (Blackmagic/AJA) | Broadcast-grade capture hardware we neither own nor can validate against. |

## Summary

- **Our A+ rows — the field has nothing comparable:** **musical
  intelligence** (genre/structure/tempo turned into *decisions*, not just
  parameter modulation), **DJ/set integration** (a mixer in the same product,
  publishing a set clock and a finale hand-off), **unattended operation**
  (built to run the night alone), and **ANSI/demoscene art** (a tradition
  nobody else represents).
- **The one row we lose to everybody: video output interop.** No NDI, no
  Spout, no Syphon. Every rival except projectM has at least one. **This is
  the highest-leverage flip available** — Spout + NDI would drop unicorn-viz
  into every OBS and Resolume rig in existence, and it's a well-trodden
  integration, not research.
- **The honest second gap is OS reality.** Windows is the declared primary
  release target and is currently the *worst-supported* platform we ship —
  rough dependency install, ★1 installer, and this week's DPI/multi-head
  fixes still unverified on hardware. projectM's A in that row is a
  standing rebuke: an open-source project from 2003 runs cleanly on more
  platforms than we do.
- **The real peers are Synesthesia and Resolume, not TouchDesigner.**
  Synesthesia shares our *intent* (make music look like something, live) and
  beats us on shader workflow and interop while having nothing like our
  autonomy. Resolume is the standard we'd be measured against in a club, and
  wins on content ecosystem, interop and mapping. TouchDesigner is a
  different category — it can become anything, which is both why it wins its
  rows and why it is not what a DJ opens at 11pm.
- **What keeps the overall at B+ rather than A** is not capability — it is
  three things: interop (fixable in weeks), OS delivery (fixable, in
  progress), and **maturity** (only fixable in rooms, over time).

## Flip list — competitor A's we could realistically take

1. **NDI + Spout output** (beats a D → A− across a whole row; Windows-first,
   which matches the release target). **Highest value on the board.**
2. **Windows delivery** — bundled runtime + prebuilt wheels gets OS support
   C+ → B+ and removes the last real barrier to a public release.
3. **macOS** — Syphon comes with it; would take OS support to A−.
4. **In-app live shader editing** — the one place Synesthesia's authoring
   workflow is genuinely nicer than ours.
5. **Outbound OSC state tree** — cheap, and makes us a good citizen in a
   rig that already speaks OSC.

## Sources

Researched 2026-08-07:

- [Resolume software & shop](https://www.resolume.com/shop/) — Avenue €299, Arena €799
- [Resolume Avenue & Arena features](https://www.resolume.com/software/avenue-arena)
- [Resolume SMPTE support](https://resolume.com/support/en/smpte) · [Ableton Link](https://resolume.com/support/en/link) · [ProDJLink](https://www.prodjlink.com/help/resolume)
- [Synesthesia pricing](https://synesthesia.live/pricing) — $199 Standard / $399 Pro; Syphon/Spout/NDI and OSC are Pro-gated
- [Synesthesia docs](https://synesthesia.live/docs/index.html) — audio uniforms, Shadertoy/ISF import
- [Magic Music Visuals](https://en.wikipedia.org/wiki/Magic_Music_Visuals) — Windows/macOS, node-based
- [TouchDesigner products & licensing](https://derivative.ca/UserGuide/TouchDesigner_Products) — free non-commercial capped at 1280×1280, $600 commercial, $300 education
- [TouchDesigner platform support](https://en.wikipedia.org/wiki/TouchDesigner) — Windows/macOS only, no official Linux
- [projectM](https://github.com/projectM-visualizer/projectm) · [project site](https://projectm-visualizer.org/) — LGPL v2.1, initiated 2003, cross-platform incl. OpenGL-ES
- [VDMX6 announcement](https://cdm.link/vdmx6/) and [VIDVOX](https://www.vidvox.net/) — $199 / $349 Plus, macOS only
- [VJ software landscape 2026](https://vjgalaxy.com/blogs/resources-digital-assets/vj-software-guide-2026-from-vjing-to-generative-art) · [live-visuals roundup](https://www.heavym.net/best-software-for-live-music-visuals/)

## Changelog

- 2026-08-07: initial scorecard (core 1.0.0-beta.44, pre-RC1). Opens at
  **B+ overall** with three A+ rows (musical intelligence, DJ/set
  integration, unattended operation) plus ANSI/demoscene as a fourth, and
  one **D** — video output interop, the only row where the entire field
  beats us. OS support graded **C+** on delivered reality (Linux strong,
  Windows rough, macOS absent) rather than on stated intent.
