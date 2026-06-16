# Unicorn Viz — Feature Enhancement Suggestions (2026-05-09)

These suggestions are intentionally outside the items already listed in
`plan.md`. They are organized by theme and tagged with rough scope.

Scope tags: `S` small, `M` medium, `L` large, `XL` multi-phase.

---

## A. Live performance / VJ workflow

1. (M) Tap-tempo hotkey
   - Press a key 4+ times to lock BPM; expose to effects via `audio.bpm`.
   - Useful when source signal lacks clear onsets (ambient sets, classical).

2. (M) Beat-locked transitions
   - Optional flag: only fire transition on the next detected beat.
   - Smoothes pacing during high-energy sets.

3. (M) Favorites / scene banks
   - Star current effect+parameters into a numbered slot; recall instantly.
   - Persistable to a `presets.toml`.

4. (M) Snapshot / restore show state
   - Save current effect, parameters, reactivity, playlist, transition.
   - Resume after reboot or app crash.

5. (S) Quick-search effect overlay
   - `/` opens an overlay that filters effects by name/tag.

6. (S) On-the-fly playlist reorder hotkeys
   - Move current scene up/down in the playlist while running.

7. (M) Show segments with energy targets
   - Define low / build / peak / breakdown sections; effect rotation auto-tunes
     intensity and reactivity per segment.

8. (M) Show timeline mode
   - Read a simple `show.toml` with timestamps and scene cues for synced sets.

---

## B. Real-world I/O

9. (M) OSC input alongside MIDI
   - Many controllers and DAWs prefer OSC for richer parameter ranges.

10. (L) DMX / Art-Net output
    - Send beat / band envelopes to lighting fixtures via Art-Net.
    - Native VJ + lighting integration.

11. (M) Web UI remote control
    - Local WebSocket server; phone-friendly buttons for next/prev, scene jump,
      reactivity reset, parameter sliders.

12. (S) Hotkey + MIDI learn mode
    - Press learn, hit any controller / key, bind it to the next action chosen.

13. (M) Sidechain ducking input
    - Optional secondary audio source for ambient effects to react inversely
      (calmer visuals when a vocal channel ducks).

---

## C. Recording / output

14. (L) Built-in MP4 recording
    - Pipe rendered frames to ffmpeg via stdin; toggleable hotkey + indicator.

15. (M) Looping GIF / WebM clip exporter
    - Capture last N seconds to a clip on demand; great for socials.

16. (S) Screenshot bursts / sequence
    - Hold S to capture a sequence at fixed cadence.

17. (M) Spout / Syphon-equivalent output (Linux PipeWire video)
    - Share the rendered surface to OBS or other apps via PipeWire video output.

---

## D. Visual / artistic systems

18. (M) Global color-temperature LUT
    - Warm/cool/neutral global tone presets (no per-effect changes needed).

19. (M) Effect chain / layering pipeline
    - Bottom + overlay + post composite of multiple effects; alpha and blend modes.

20. (M) Live shader hot-reload
    - Watch effect files; recompile on save; surface compile errors as overlay.

21. (S) ANSI cycle randomization
    - Shuffle ANSI viewer's slide order each launch.

22. (M) ANSI in-app editor
    - Minimal tile-based editor with CP437 palette + save to `assets/ansi/own/`.

23. (M) Dynamic palette extraction
    - When the audio source supplies metadata (e.g., MPRIS art), extract a
      palette and feed effects via a uniform.

24. (M) Captions / lyric overlay
    - Show synced text from a sidecar `.lrc` or external LRC source.

---

## E. Reliability, observability, perf safety

25. (S) Crash-safe shader compile dump
    - On compile failure, write the failing shader source + GLSL log under
      `logs/shader_errors/<timestamp>.glsl` for offline inspection.

26. (M) Profile / benchmark mode
    - Run each effect for N seconds at startup, record GPU/CPU times, write
      a markdown table; optional auto-disable of effects that exceed budget.

27. (S) Performance HUD with per-effect average frame time
    - Already in plan.md as "Performance HUD"; this is the per-effect detail
      sub-feature, not a duplicate of the headline overlay.

28. (M) Dynamic resolution scaling
    - Auto adjust internal render scale to maintain target frame time.

29. (S) GPU memory budget reporter
    - Sum live texture/VBO bytes; warn if approaching configured budget.

30. (S) Auto-detect SDL driver instead of forcing Wayland-first
    - Reduce startup warning noise on X11 sessions.

---

## F. Authoring / dev experience

31. (M) Effect scaffolder
    - `tools/new_effect.py MyEffect` writes a working starter file in `effects/`.

32. (S) Effect screenshot collage
    - Run all effects briefly; save a contact-sheet PNG to `docs/`.

33. (M) Parameter UI panel
    - Optional Imgui-style overlay listing every parameter of the current
      effect with sliders (gated behind a hotkey for stage privacy).

34. (S) Per-effect parameter snapshot
    - `S+P` writes current parameter values to `[effects.<ClassName>]` block
      in a draft `presets.toml`.

35. (S) Replay from log
    - Logs already include scene changes and times; tool to replay a setlist.

---

## G. Integration / metadata

36. (M) MPRIS now-playing pickup (Linux)
    - Read current track title/artist; show a tasteful overlay during transitions.

37. (M) Spotify / Music local-only metadata bridge
    - Same idea, vendor-specific fallback.

38. (S) BPM display in HUD
    - Show estimated BPM and downbeat indicator; mostly visual confirmation.

---

## H. Accessibility / usability

39. (S) Photosensitive-safe mode
    - Cap flash intensity, tame strobing transitions, reduce beat flashes.

40. (S) Reduced-motion mode
    - Slow camera shakes / parallax for venues with motion-sensitive audiences.

41. (S) High-contrast HUD theme
    - For bright stages where current overlay is hard to read.

---

## I. Miscellaneous distinctive ideas

42. (M) Audience-driven mode
    - Webcam-based light/motion sense to subtly tilt parameters from crowd movement.

43. (M) Microphone tap mode
    - Use the laptop mic as an additional onset detector during sets.

44. (S) Surprise effect roulette
    - Hotkey instantly throws to a random effect not seen this session.

45. (M) "Encore" buffer
    - Track which effects produced the loudest reactions (audio energy in the
      40s after switching to them) and suggest replays at the end.

46. (S) Voice command quick toggle
    - One-shot keyword (`unicorn next`, `unicorn pause`) via a small offline
      VAD + keyword model. Optional.

---

## Top picks if you want a short list

Highest impact for live use, low-to-moderate effort:
- 1 Tap-tempo
- 2 Beat-locked transitions
- 3 Favorites / scene banks
- 11 Web UI remote
- 14 Built-in MP4 recording
- 19 Effect chain / layering
- 26 Profile / benchmark mode
- 28 Dynamic resolution scaling
- 39 Photosensitive-safe mode
