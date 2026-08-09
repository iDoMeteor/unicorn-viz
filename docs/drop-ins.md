# Drop-in Documentation Registry

Owner: Studio Documentation
Status: active
Last updated: 2026-07-01

This page tracks canonical documentation coverage for each drop-in.

## Required Baseline

Every drop-in must include:

- `README.md` with overview, controls, configuration, dependencies, and troubleshooting.

Complex drop-ins should also include:

- `docs/operations.md`
- `docs/configuration.md`
- `docs/integration.md`
- `docs/troubleshooting.md`

## Current Coverage

| Drop-in | README | Structured docs | Notes |
| --- | --- | --- | --- |
| audio-out-01 | Yes | Yes | Audio output / SFX-injection subsystem |
| auto-vj-01 | Yes | Yes | Automation subsystem |
| banner-01 | Yes | Yes | Bottom marquee/banner subsystem |
| beat-flash-01 | Yes | Yes | BPM-locked strobe (safety-governed) post subsystem |
| candy-frame-01 | Yes | Not required | Candy frame border overlay subsystem |
| chat-01 | Yes | Yes | Live chat overlay subsystem (Ably Realtime; opt-in) |
| control-room-01 | Yes | Yes | Operator/control subsystem |
| color-grade-01 | Yes | Yes | Global colour-grade / LUT post subsystem |
| cosmic-01 | Yes | Not required | Effect pack: Cosmos, Black Hole Cathedral, Wavey Gravy, Alien Invasion, Sun Ship 3000 |
| cta-01 | Yes | Not required | Call-to-action overlay subsystem (extracted CTA editor/slots) |
| dj-mixer-01 | Yes | Yes | Two-deck DJ mixer window + Pioneer DDJ-REV1 input |
| feature-01 | Yes | Not required | Effect pack: Hexy Stars, Rainbow Trance, Metaballs |
| flying-01 | Yes | Not required | Effect pack: Warp Drive, Cloud Surfer, Canyon Run, Wingsuit Dive, Nebula Drift, Asteroid Run, Portal Flight |
| games-01 | Yes | Not required | Effect pack: Breakout, Neon Pac, Galaga, Joust, Tetris, Missile Command, Donkey Kong, Q*bert |
| midi-controllers-01 | Yes | Yes | Controller presets + APC mini mk2 LED feedback subsystem |
| grand-finale-01 | Yes | Not required | Focused sequence drop-in |
| holiday-01 | Yes | Not required | Effect pack: America 250 (seasonal/event) |
| images-01 | Yes | Not required | Media effect drop-in |
| immersive-01 | Yes | Not required | Effect pack: Tunnel, Wormhole, Cathedral of Bass |
| lyrics-01 | Yes | Yes | Synced lyrics overlay subsystem (LRCLIB) |
| media-01 | Yes | Yes | Local audio-file playback subsystem (python-vlc/mpv/ffplay) |
| multi-head-01 | Yes | Yes | Display subsystem |
| osc-bridge-01 | Yes | Yes | OSC control-surface subsystem |
| particles-01 | Yes | Not required | Effect pack: Starfield, Fireworks, Particle Storm |
| postfx-01 | Yes | Yes | Post-processing subsystem |
| projectm-01 | Yes | Yes | External engine integration |
| psychedelic-01 | Yes | Not required | Effect pack: Plasma, Kaleidoscope, Psychedelic |
| retro-01 | Yes | Not required | Effect pack: Copper Bars, ANSI Viewer, Fractal Zoom, Escher, Dali, Van Gogh |
| sims-01 | Yes | Not required | Media/effect drop-in |
| spotify-01 | Yes | Yes | Spotify metadata subsystem |
| streaming-01 | Yes | Yes | Streaming subsystem |
| tech-01 | Yes | Not required | Effect pack: Tron Grid, Cyber War, Hacker Terminal, Hacker Terminal 2.0, Threat Matrix |
| textures-01 | Yes | Not required | Media effect drop-in |
| training-kit-01 | Yes | Yes | Auto VJ training tools: corpus packaging, scoring, daemon |
| unicorn-tears-01 | Yes | Not required | Effect drop-in |
| video-out-01 | Yes | Not required | Video output interop: v4l2loopback virtual camera (PipeWire/NDI planned) |
| video-postfx-01 | Yes | Yes | Chroma-keyed video overlay stack post subsystem |
| vector-01 | Yes | Not required | Effect pack: 3D Cube, Vector, Disco Ball |
| video-clips-01 | Yes | Not required | Video Clips: audio-reactive clip montage (directory-group selection) |
| videos-01 | Yes | Not required | Video Player: whole videos with audio (ffpyplayer); manual-only |
| webcam-01 | Yes | Not required | Focused subsystem with limited surface; planning doc added |

## Structured Docs Links (Complex Drop-ins)

- audio-out-01
  - [Operations](../drop-ins/audio-out-01/docs/operations.md)
  - [Configuration](../drop-ins/audio-out-01/docs/configuration.md)
  - [Integration](../drop-ins/audio-out-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/audio-out-01/docs/troubleshooting.md)
- auto-vj-01
  - [Operations](../drop-ins/auto-vj-01/docs/operations.md)
  - [Configuration](../drop-ins/auto-vj-01/docs/configuration.md)
  - [Integration](../drop-ins/auto-vj-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/auto-vj-01/docs/troubleshooting.md)
  - [Weights & Thresholds Reference](../drop-ins/auto-vj-01/docs/weights-and-thresholds.md)
  - [Training Pack Protocol](planning/auto-vj-training-pack-protocol.md)
- banner-01
  - [Operations](../drop-ins/banner-01/docs/operations.md)
  - [Configuration](../drop-ins/banner-01/docs/configuration.md)
  - [Integration](../drop-ins/banner-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/banner-01/docs/troubleshooting.md)
- beat-flash-01
  - [Operations](../drop-ins/beat-flash-01/docs/operations.md)
  - [Configuration](../drop-ins/beat-flash-01/docs/configuration.md)
  - [Integration](../drop-ins/beat-flash-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/beat-flash-01/docs/troubleshooting.md)
- color-grade-01
  - [Operations](../drop-ins/color-grade-01/docs/operations.md)
  - [Configuration](../drop-ins/color-grade-01/docs/configuration.md)
  - [Integration](../drop-ins/color-grade-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/color-grade-01/docs/troubleshooting.md)
- control-room-01
  - [Planning](planning/drop-in-planning.md)
  - [Operations](../drop-ins/control-room-01/docs/operations.md)
  - [Configuration](../drop-ins/control-room-01/docs/configuration.md)
  - [Integration](../drop-ins/control-room-01/docs/integration.md)
  - [Test Matrix](../drop-ins/control-room-01/docs/test-matrix.md)
  - [Troubleshooting](../drop-ins/control-room-01/docs/troubleshooting.md)
- dj-mixer-01
  - [Coding conventions](../drop-ins/dj-mixer-01/docs/conventions.md)
  - [Operations](../drop-ins/dj-mixer-01/docs/operations.md)
  - [Configuration](../drop-ins/dj-mixer-01/docs/configuration.md)
  - [Integration](../drop-ins/dj-mixer-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/dj-mixer-01/docs/troubleshooting.md)
  - [Feature Overview](../drop-ins/dj-mixer-01/docs/feature-overview.md)
  - [Beat Grid & Song Sections (user guide)](../drop-ins/dj-mixer-01/docs/grid-and-sections.md)
  - [Hardware Bring-up](../drop-ins/dj-mixer-01/docs/hardware-bringup.md)
  - [Real-time Stems — decision](../drop-ins/dj-mixer-01/docs/realtime-stems.md)
  - [S4 MK3 Protocol Research](../drop-ins/dj-mixer-01/docs/s4mk3-protocol.md)
  - [S4 MK3 Bring-up](../drop-ins/dj-mixer-01/docs/hardware-bringup-s4mk3.md)
  - [Upcoming Work](../drop-ins/dj-mixer-01/docs/upcoming-work.md)
  - [Smart DJ Plan](../drop-ins/dj-mixer-01/docs/smart-dj-plan.md)
  - [AI DJ Plan](../drop-ins/dj-mixer-01/docs/ai-dj-plan.md)
  - [Stems FX Plan](../drop-ins/dj-mixer-01/docs/stems-fx-plan.md)
- midi-controllers-01
  - [Operations](../drop-ins/midi-controllers-01/docs/operations.md)
  - [Configuration](../drop-ins/midi-controllers-01/docs/configuration.md)
  - [Integration](../drop-ins/midi-controllers-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/midi-controllers-01/docs/troubleshooting.md)
  - [Profiles](../drop-ins/midi-controllers-01/docs/profiles.md)
  - [APC Remap Plan](../drop-ins/midi-controllers-01/docs/apc-remap-plan.md) (draft proposal)
- lyrics-01
  - [Operations](../drop-ins/lyrics-01/docs/operations.md)
  - [Configuration](../drop-ins/lyrics-01/docs/configuration.md)
  - [Integration](../drop-ins/lyrics-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/lyrics-01/docs/troubleshooting.md)
- media-01
  - [Operations](../drop-ins/media-01/docs/operations.md)
  - [Configuration](../drop-ins/media-01/docs/configuration.md)
  - [Integration](../drop-ins/media-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/media-01/docs/troubleshooting.md)
- multi-head-01
  - [Operations](../drop-ins/multi-head-01/docs/operations.md)
  - [Configuration](../drop-ins/multi-head-01/docs/configuration.md)
  - [Integration](../drop-ins/multi-head-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/multi-head-01/docs/troubleshooting.md)
- osc-bridge-01
  - [Operations](../drop-ins/osc-bridge-01/docs/operations.md)
  - [Configuration](../drop-ins/osc-bridge-01/docs/configuration.md)
  - [Integration](../drop-ins/osc-bridge-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/osc-bridge-01/docs/troubleshooting.md)
- postfx-01
  - [Operations](../drop-ins/postfx-01/docs/operations.md)
  - [Configuration](../drop-ins/postfx-01/docs/configuration.md)
  - [Integration](../drop-ins/postfx-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/postfx-01/docs/troubleshooting.md)
- projectm-01
  - [Planning](../drop-ins/projectm-01/docs/planning.md)
  - [Operations](../drop-ins/projectm-01/docs/operations.md)
  - [Configuration](../drop-ins/projectm-01/docs/configuration.md)
  - [Integration](../drop-ins/projectm-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/projectm-01/docs/troubleshooting.md)
- spotify-01
  - [Operations](../drop-ins/spotify-01/docs/operations.md)
  - [Configuration](../drop-ins/spotify-01/docs/configuration.md)
  - [Integration](../drop-ins/spotify-01/docs/integration.md)
  - [Planning](../drop-ins/spotify-01/docs/planning.md)
  - [Security](../drop-ins/spotify-01/docs/security.md)
  - [Web API Auth Prep](../drop-ins/spotify-01/docs/web-api-auth-prep.md)
  - [Troubleshooting](../drop-ins/spotify-01/docs/troubleshooting.md)
  - Corpus export workflow is documented in [Configuration](../drop-ins/spotify-01/docs/configuration.md)
- streaming-01
  - [Operations](../drop-ins/streaming-01/docs/operations.md)
  - [Configuration](../drop-ins/streaming-01/docs/configuration.md)
  - [Integration](../drop-ins/streaming-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/streaming-01/docs/troubleshooting.md)
- video-postfx-01
  - [Operations](../drop-ins/video-postfx-01/docs/operations.md)
  - [Configuration](../drop-ins/video-postfx-01/docs/configuration.md)
  - [Integration](../drop-ins/video-postfx-01/docs/integration.md)
  - [Troubleshooting](../drop-ins/video-postfx-01/docs/troubleshooting.md)
- webcam-01
  - [Planning](../drop-ins/webcam-01/docs/planning.md)
