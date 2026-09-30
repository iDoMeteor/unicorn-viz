# Hardware and GPU run bug audit (2026-09-30)

Owner: DJ Unicorn Tears
Status: complete — all findings open; nothing fixed in this pass
Last updated: 2026-09-30

Sixth and last report of the 2026-09-30 series, after
[2026-09-30-bug-audit.md](2026-09-30-bug-audit.md),
[2026-09-30-auto-vj-director-recommender-audit.md](2026-09-30-auto-vj-director-recommender-audit.md),
[2026-09-30-windows-bug-audit.md](2026-09-30-windows-bug-audit.md),
[2026-09-30-ui-files-bug-audit.md](2026-09-30-ui-files-bug-audit.md) and
[2026-09-30-effects-and-cameras-bug-audit.md](2026-09-30-effects-and-cameras-bug-audit.md).

**Scope.** Bugs only; performance is deferred.
- **Akai APC mini mk2:** core `unicornviz/midi.py`, the MIDI dispatch in
  `hotkeys.py`, and all of `midi-controllers-01` (`midi_manager.py`,
  `apc_leds.py`, `controller_presets.py`, `controller_profiles.py`, the
  bundled profiles).
- **Pioneer DDJ-REV1:** `dj-mixer-01`'s `rev1_map.py`, `rev1_input.py`,
  `rev1_leds.py`, and the REV1 wiring in `dj_mixer_controller.py`.
- **A real GPU run:** the actual app, not the offscreen harness.

Out of scope, by the owner's call: the S4 MK3, the DDJ-REV1000 and the
network drop-ins.

Versions: master `1c2e0ac`, `midi-controllers-01` `a18aadf`,
`dj-mixer-01` `87dbba9` (0.222.0).

**Method.**
1. Read every line of the files above.
2. **Hermetic repros** with a fake rtmidi and a fake `vj_api`, so no device
   was opened or written: `midi_replug.py`, `apc_disabled_inject.py`,
   `apc_stale_leds.py`, `fader_params.py`.
3. **Live hardware:** both controllers were plugged in (APC on `hw:3`, REV1
   on `hw:4`). The app detected and claimed both and lit the APC LEDs. The REV1 LED port opened, then was dropped (H13). I
   can't press buttons or pull cables, so anything that needs a physical
   press or unplug is marked as code-read.
4. **Real GPU runs** from the seat worktree, windowed 1280×720 on the Iris Xe
   (Mesa 26.1.4, GL 4.6, Wayland). The runs used their own `runtime/` and
   `logs/`, never the owner's. Each played all 83 effects in sequence,
   with Auto VJ and keystroke logging off:
   - run 1: 8 s per effect, mixer closed;
   - run 2: 5 s per effect, with the DJ mixer opened at boot, so the REV1
     input, the REV1 LEDs and the second SDL window were live.

The scripts and configs live in `/var/tmp/uv-bug-audit/`.

Marked **VERIFIED** where reproduced.

**GPU run result.** Both runs played the whole list and wrapped around
(88 and 91 scene changes). There were no exceptions, GL errors or
tracebacks while rendering, in either the main window or the mixer's
second SDL window.

Run 2 logged 1,931 perf samples, and only 12 frames took over 25 ms. All
were one-offs at a scene switch:
- Texture Showcase 428 ms (synchronous image decode at construction);
- ANSI Viewer 196 ms;
- everything else 63 ms or less.

Those belong to the deferred performance pass. The bugs the runs did
surface are:
- G1 (the launch flag);
- G2 (perf logging);
- G3 (Ctrl+C shutdown);
- G4 (ProjectM `idle://`);
- H13 (REV1 LEDs);
- H14 (the APC after exit).

Observations, not classified as bugs:
- The main window ran at a median 359 fps in single windowed mode, with
  swap interval 1 requested (`app.py:4785`, return value unchecked). The
  owner's mirror sessions log 36–48 fps, so this is probably compositor
  frame pacing for this window rather than the app.
- The mixer UI logged 31–57 ms mean render against its 33 ms budget while
  sharing the GPU with that uncapped main window.

## Summary

| ID | Sev | Where | Bug |
|---|---|---|---|
| H13 | P1 | `dj_mixer_controller.py:1452` | REV1 LED feedback has been dead in every mixer session since 2026-09-24. Assigning a bound method to the out-of-process engine raises "cannot pickle 'mgl.Context'", and the handler throws the LEDs away. **VERIFIED** live and in the owner's logs |
| H1 | P2 | `midi.py:421-447`, `dj_mixer_controller.py:1416-1420` | Unplugging a controller, even a USB blip, kills it for the session: neither the APC nor the REV1 ever reconnects. A REV1 powered on after the mixer opens is never picked up, although the log says "not found yet". **VERIFIED** |
| H2 | P2 | `apc_leds.py:660-673`, `1075-1098` | On the libusb path, an APC unplug leaves the reader thread spinning on `LIBUSB_ERROR_NO_DEVICE`. The handle is never reopened, so the APC LEDs stay dark until a restart |
| H3 | P2 | `controller_presets.py:446-457`, `vj_api.py:1823-1837` | "MIDI disabled" doesn't disable the APC. The libusb claim and event injection ignore the device setting, so pads still fire actions, through whichever preset is active, even with another controller selected. **VERIFIED** |
| H4 | P2 | `controller_presets.py:52-62` | Most APC faders are dead. `pan` (CC 55) exists on 0 of 83 effects. `volume` (CC 54 and the "master volume" CC 56) exists only on Video Player, `crt` only on ANSI Viewer. **VERIFIED** |
| G1 | P2 | `__main__.py:96`, `config.py:41` | `--effect-duration` always fails config validation (float vs the int default), so the README and user-guide launch examples exit at startup. **VERIFIED** live |
| G3 | P2 | `app.py:8069-8070`, `__main__.py:626-634` | Ctrl+C in a terminal crashes shutdown. SIGINT also kills the audio/mixer helper processes, `_audio_manager.stop()` raises `HostGone`, and the rest of teardown is skipped: runtime-state save, webcam state, audio relay state, MIDI close, GL/SDL. **VERIFIED** live |
| H14 | P3 | `apc_leds.py:646-658` | After every session the APC loses its kernel MIDI driver until replugged: the post-release re-probe fails with "USB device is in the shutdown state". The next launch finds no ALSA ports, and other apps can't see the APC. **VERIFIED** live |
| H5 | P3 | `apc_leds.py:1259-1299` | Pads unbound by a profile switch, a MIDI Learn clear or a rebind keep their old LED color. Switching Stock → Alt-01 leaves 6 dead pads lit. **VERIFIED** |
| H6 | P3 | `midi_manager.py:1620-1629`, `674-706` | MIDI Learn accepts REV1 events as APC bindings, and the teaching press fires the newly learned drop-in action once |
| H7 | P3 | `rev1_leds.py:268-274` | REV1 PLAY beat flash ignores the downbeat offset, so it's out of phase with the music |
| H8 | P3 | `rev1_input.py:645-675` | Only pitch has soft takeover. After AutoPlay, session restore or the UI moves the crossfader or a gain, the first touch of the physical control jumps it back and can cut the audible deck |
| H9 | P3 | `rev1_input.py:550-560`, `568-578` | 14-bit reassembly pairs a new MSB with the old LSB: a one-message zipper glitch at every MSB step |
| H10 | P3 | `midi.py:512-532` | `_open_ports` leaks already-opened MidiIns, with live callbacks, when a later `open_port` fails |
| H11 | P3 | `apc_leds.py:378-406` | The rawmidi fallback drops a message split across two reads (fader sweeps) |
| H12 | P3 | `rev1_input.py:156-160` | `rev1_log_notes` logs note data at INFO, against the MIDI-logging rule |
| G4 | P3 | `projectm_effect.py:975`, `1515`, `1567`, `1585` | With an empty preset library, ProjectM loads `idle://`, which this libprojectM rejects ("No preset factory associated with extension ".""). **VERIFIED** live |
| G2 | P3 | `app.py:6662-6664`, `6707` | `[logging] perf_frames` is ignored on the first boot after the config-menu migration (restore runs before migrate). **VERIFIED** live |

## P1

### H13 — REV1 LEDs dead since the engine moved out of process (VERIFIED)

**Where.** `dj_mixer_controller._open_rev1` builds `Rev1Leds`, which opens
the REV1 MIDI output and logs "LED feedback ready". Then, inside the same
`try`, it runs:

```python
self._engine.on_scratch_mode = self._push_vinyl_on      # line 1452
```

`self._engine` is now a remote proxy into the audio helper process. Setting
an attribute pickles the value. A bound method pickles its `self`, the
controller, which holds the GL context:

```
18:43:46 INFO    dj-mixer-01: rev1 LED feedback ready
18:43:46 WARNING dj-mixer-01: rev1 LED feedback unavailable: cannot pickle 'mgl.Context' object
```

The `except` sets `self._leds = None`, so:
- nothing ever calls `Rev1Leds.update()`: PLAY/CUE/SYNC/CH CUE, the pad
  lights, the pad-mode buttons, the FX paddle and slot lights, the idle VU
  and the AutoPlay pre-transition pad flash are all dark;
- the already-opened output port is never closed (a leaked ALSA client),
  and mixer close skips `all_off()`.

**Evidence.** The owner's own logs in the main checkout:
- every mixer open from 2026-09-17 and 2026-09-18 logs "ready" with no
  failure;
- every one from 2026-09-24 onward (6 sessions: 09-24 ×4, 09-26, 09-27)
  logs the pickle failure.

Run 2 reproduced it on the first open.

Even if the pickle succeeded, the design is broken for the remote engine:
`mixer_engine.toggle_scratch_mode` calls `on_scratch_mode` inside the helper
process (`mixer_engine.py:1174-1178`), where the controller doesn't exist.

**Fix direction.**
- Take the callback out of the LED `try`, so a failure there can't discard
  the LEDs.
- Replace it with a main-process poll: the controller already has the
  engine snapshot each frame, and can call `_push_vinyl_on` when
  `hamster`/scratch mode flips on.

## P2

### H1 — A USB blip kills the controller for the session (VERIFIED)

**Where.** `MidiManager` in core `unicornviz/midi.py`:
- `_maintain_primary` (`421-435`) sees the active port vanish and calls
  `reopen(self._device_hint)`.
- `reopen` (`383-406`) calls `_open_ports`, which fails while the device is
  still unplugged, and then sets `self._device_hint = ''` (`403`).
- From then on `maintenance_update` returns early (`not self._device_hint
  and not self._aux_ins`). The reconnect branch at `433-435` can only run
  while a hint is set, so it never runs after an unplug.
- The aux path (the REV1) is the same shape. `_maintain_aux` (`437-444`)
  destroys the vanished input and calls `add_input_device(hint)` once. That
  fails because the port is still gone, the entry is dropped from
  `_aux_ins`, and nothing ever retries.
- `dj_mixer_controller._open_rev1` (`1407-1425`) logs "input opened (device
  'rev1' not found yet)" when the REV1 is off, then sets `_rev1_open =
  True`. Nothing re-attempts: `_maintain_aux` only walks existing entries.

**Repro.** `midi_replug.py` (fake rtmidi, scripted port list, the real
`maintenance_update`):

```
both present             primary=True  hint='apc mini mk2 notes' aux=['DDJ-REV1:DDJ-REV1 MIDI 1 32:0']
unplugged (blip)         primary=False hint=''                   aux=[]
replugged, tick 1..3     primary=False hint=''                   aux=[]
mixer opened while REV1 still off -> add_input_device False; after REV1 powered on: aux = []
```

**Effect.** A cable jiggle mid-set kills the controller:
- The REV1 is dead until the mixer window is closed and reopened.
- The APC is dead until someone re-picks it in the MIDI selector. On the
  libusb path its LEDs stay dead even then (H2).
- The REV1 LED output (`rev1_leds._open_output`, `204-226`) is opened only
  at construction, so it also needs a mixer close/reopen.

**Fix direction.**
- Keep the hint across failures; `reopen('')` alone should disable MIDI.
- Keep a "wanted" set of aux hints that maintenance retries on its 2 s
  throttle.
- Reopen the REV1 LED output when its input reconnects.

### H2 — libusb APC path: hot spin after unplug, LEDs never come back

**Where.** `_LibUsbIO._read_loop` (`apc_leds.py:660-673`) loops while
`self._running` and ignores every return code except success. Timeouts
(-7) are normal and cost the 10 ms timeout. After a disconnect, though,
libusb returns `LIBUSB_ERROR_NO_DEVICE` immediately. The loop then becomes a
tight Python loop that competes with the render thread for the GIL.

The handle is chosen once, in `APCLedFeedback.__init__` (`1075-1098`), and
nothing reopens it:
- after a replug, writes keep failing;
- after three failures `_transfer` pauses LED output for 30 s, probes,
  fails and pauses again, for the rest of the session.

**Status.** Code-read. The immediate `NO_DEVICE` return is documented
libusb behavior, but I couldn't unplug the controller to measure it.

**Fix direction.**
- Exit the reader on any error other than a timeout.
- Mark the IO unavailable.
- Have `update()` retry `_LibUsbIO.open()` on a slow timer, then re-send
  the host-mode SysEx and repaint.

### H3 — "MIDI disabled" doesn't disable the APC (VERIFIED)

**Where.**
- `controller_presets.register_all(MidiManager, None)` runs on every boot
  (`app.py:6209`). It claims the APC's USB interface through libusb, which
  detaches the kernel driver (`controller_presets.py:446-457`), whatever
  `[midi] device` says.
- The reader thread then feeds every pad press to
  `vj_api.midi_inject_event` (`vj_api.py:1823-1837`), which calls
  `MidiManager._callback(..., None)` as if the event came from the primary
  device.
- `HotkeyHandler.attach_midi` is unconditional (`app.py:6366`).

**Repro.** `apc_disabled_inject.py`:

```
hint=''         available=False events=2 actions=['next', 'fullscreen']
hint='mpk mini' available=False events=2 actions=[None, 'next']
```

**Effect.**
- `[midi] device = ""`, `--midi-device ""` and "none" in the MIDI selector
  (all documented as "MIDI disabled") still let APC pads skip effects and
  toggle fullscreen.
- With another controller selected, APC presses fire through that
  controller's map: APC note 60 becomes MPK's `next`.
- The kernel driver is detached either way, so no other app (a DAW) can use
  the APC while Unicorn Viz runs.

**Fix direction.**
- Gate the early claim on the configured device hint matching the APC.
- Have `midi_inject_event` drop events unless the primary device is the
  APC.

### H4 — Most APC faders do nothing (VERIFIED)

**Where.** The stock APC preset's `cc_map` (`controller_presets.py:52-62`,
same in `profiles/apc-mini-mk2-stock.toml`) binds faders to parameter
names. `HotkeyHandler._dispatch_midi_event` writes only when the current
effect declares that name (`hotkeys.py:458-463`).

`fader_params.py` instantiated all 83 effects and read their real
`parameters`:

| Fader | Name | Effects that have it |
|---|---|---|
| CC 48 | `speed` | 79 |
| CC 49 | `intensity` | 5 |
| CC 50 | `zoom` | 41 |
| CC 51 | `reactivity` | 46 |
| CC 52 | `glow` | 6 |
| CC 53 | `crt` | 1 (ANSI Viewer) |
| CC 54 | `volume` | 1 (Video Player) |
| CC 55 | `pan` | **0** |
| CC 56 | `volume` ("master volume") | 1 (Video Player) |

The Ctrl+Alt+H help modal promises "56 master volume" and "All mapped by
default in APC preset" (`controller_presets.py:379-386`). There is no master
volume. On a typical effect, five of nine faders are silently dead, with no
flash message.

**Fix direction.**
- Bind the dead faders to app-level controls through `vj_api` (reactivity,
  PostFX mix, zoom, master or mixer volume).
- Flash "no <param> on this effect" when a mapped CC has no target.

### G1 — `--effect-duration` can't be used (VERIFIED live)

`__main__.py:96` declares `--effect-duration` as `type=float`. The config
default is the int `60` (`config.py:41`). `_collect_type_errors` rejects a
float where the default is an int (`config.py:364-390`):

```
$ python -m unicornviz --effect-duration 7 ...
Configuration validation failed:
  - demo.effect_duration must be int, got float
exit=2
```

- `README.md:106` (`--effect-duration 30`) and `docs/user-guide.md:108`
  (`--effect-duration 45`) both exit at startup.
- `effect_duration = 7.5` in TOML is rejected the same way.
- The runtime treats the value as a float everywhere (`app.py:730`, `6687`).

**Fix.** Make the default `60.0`.

### G3 — Ctrl+C in a terminal crashes shutdown (VERIFIED live)

A terminal delivers Ctrl+C to the whole foreground process group. Run 1 ended
the same way (`timeout -s INT` signals the group). The audio and mixer
helpers are `multiprocessing` children in that group, and they died of the
same SIGINT (`helper process exited unexpectedly (code -2)`). SDL turned the
signal into a quit, and `_shutdown_runtime` then ran:

```
18:42:53 ERROR    remote: helper process exited unexpectedly (code -2)
18:42:53 WARNING  dj-mixer-01: engine close at shutdown failed: helper process is gone
18:42:53 CRITICAL Uncaught exception
  File "unicornviz/app.py", line 8070, in _shutdown_runtime
    self._audio_manager.stop()
  File "unicornviz/remote_objects.py", line 949, in call
    raise HostGone('helper process is gone')
```

- `_audio_manager.stop()` (`app.py:8069-8070`) is the one unguarded
  helper call in teardown.
- Everything after it is skipped: `persist_relay_state` and
  `audio_host.close()`, `_midi_manager.stop()`, the video-deck layer,
  `_persist_webcam_runtime_state()`, GL teardown, the final
  `self._runtime_state.save()`, and SDL teardown.
- `_shutdown_complete` is already `True`, so `ensure_shutdown` can't
  retry.
- The process exits through the uncaught-exception path.

Run 2 ended with SIGINT to the main process only (`timeout --foreground`).
That run shut down cleanly: "helper process stopped (code 0)", state saved,
no CRITICAL. So the crash comes from the helpers dying first, which is
exactly what a terminal Ctrl+C does.

**Fix direction.**
- Wrap `_audio_manager.stop()` like the other teardown steps.
- Have the helpers ignore SIGINT (`signal.signal(SIGINT, SIG_IGN)` in the
  child, or `os.setpgrp()`), so the parent decides when they stop.

## P3

- **H14 — The APC is left driverless after exit (VERIFIED live).**
  - `_LibUsbIO.close()` (`apc_leds.py:646-658`) releases interface 1 and
    closes the handle. libusb's auto-detach then hands the interface back
    to `snd-usb-audio`.
  - The kernel refuses it: `usb 3-7.2: USB device is in the shutdown
    state, cannot create a card instance` / `probe with driver
    snd-usb-audio failed with error -5`, logged at run 2's exit
    (18:53:59).
  - Run 1's exit re-probed at 18:42:53 too. Run 2 then started with no APC
    ALSA ports (`MIDI: no port matching 'apc mini mk2 notes'`), and per H1
    that disabled MIDI maintenance for the session.
  - The APC still worked in-app, only because of H3's libusb injection.
  - Outside the app, the APC is invisible to every other MIDI program until
    it's physically replugged.
  - This is the "shutdown state" the 2026-09-05 comment in `_LibUsbIO`
    describes.
  - Fix direction: `libusb_reset_device` before close, or detach and
    release interface 0 as well, so the whole card re-probes.
- **H5 — Stale APC LEDs (VERIFIED).**
  - `_refresh_from_app_state` (`apc_leds.py:1259-1299`) only queues colors
    for notes in the current `note_map`.
  - A note that loses its binding never gets `LED_OFF`.
  - `set_profile_colors` clears `_sent` but repaints only bound notes.
  - `apc_stale_leds.py`: Stock → Alt-01 leaves pads 6, 7, 62, 63 and track
    buttons 106, 107 lit (colors 4/4/48/48/37/37) while doing nothing.
  - The same happens after MIDI Learn Ctrl+D and after a rebind that moves
    an action off a note.
  - Fix: queue `LED_OFF` for every previously sent note that's no longer
    in the map.
- **H6 — MIDI Learn capture.**
  - `MidiControllerManager._on_midi` (`midi_manager.py:1620-1629`) ignores
    `event.source`. With the mixer open and Learn armed, touching the REV1
    binds a REV1 note number into the APC map, where only the APC can
    trigger it.
  - The learn bind runs on the reader thread before the main thread
    dispatches the same press (`midi.py:577-590`, `hotkeys.py:392-402`).
    The teaching press therefore fires the newly learned action.
  - The open modal swallows key-mapped actions, but drop-in actions via
    `fire_midi_action` (`projectm_*`, `postfx_clear`, mixer actions) run.
  - Fix: filter `source == ''` and swallow the event that completed a learn.
- **H7 — REV1 beat flash out of phase.**
  - `Rev1Leds._beat_on` (`rev1_leds.py:268-274`) computes
    `(position × bpm/60) % 1` without subtracting `beat_offset`.
  - The snapshot carries `beat_offset` (`deck.py`, `snapshot()`), and
    `deck.beat_phase()` subtracts it.
  - Example: first beat at 0.23 s, 128 BPM. The LED is lit for the half
    beat before each beat and goes dark right on it.
- **H8 — No soft takeover except pitch.**
  - `_apply_deck` and `_apply_mixer` (`rev1_input.py:645-675`) write gain,
    trim, EQ, crossfader and master absolutely.
  - AutoPlay (`autoplay.py:838`, `1702`, `2005`), session restore
    (`state.py:184`) and the UI (`ui.py:9177`) all set
    `engine.crossfader` in software.
  - Example: after an AutoPlay crossfade to B, the physical fader still sits
    at A. The first touch slams it to A and cuts the playing deck.
  - Pitch already has the takeover for this reason (`653-663`).
- **H9 — 14-bit zipper.**
  - On an MSB message the decoder combines the new MSB with the previous
    LSB (`rev1_input.py:550-554`, and the mixer/filter/FX equivalents).
  - The REV1 sends MSB then LSB, so each MSB step applies a value up to
    1/128 of the range off for one message.
  - Fix: apply on the LSB, or zero the stored LSB when a new MSB arrives.
- **H10 — `_open_ports` leak.** If the second `open_port` of a dual-port
  bind raises, the except path calls `stop()`. But the already-opened
  MidiIn is only in the local `opened` list (`midi.py:512-532`), so its
  ALSA client and callback stay alive. This is the leak `destroy_rtmidi`
  exists to prevent.
- **H11 — rawmidi fallback drops split messages.**
  - `_RawMidiIO._parse` (`apc_leds.py:378-406`) `break`s on a partial
    message at the end of a 64-byte read and drops it.
  - The next read starts with data bytes, which are skipped.
  - A fader sweep (21 CCs per 64 bytes) loses one message per split. Only
    affects pre-7.0 kernels, where this path is used.
- **H12 — Note logging at INFO.**
  - `[dj_mixer] rev1_log_notes = true` logs every note at INFO
    (`rev1_input.py:156-160`).
  - CLAUDE.md: "Do not log MIDI note data at INFO level or above".
  - It's an opt-in diagnostic; DEBUG would satisfy both.
- **G4 — ProjectM `idle://`.**
  - With no presets (the seat has no preset library) the effect loads
    `idle://`, and this libprojectM rejects it: `[PresetFactoryManager] No
    preset factory associated with extension "."`, then "ProjectM preset
    failed: idle:".
  - It then auto-advances through an empty list.
  - A fresh install without a preset pack hits this.
  - What the scene shows in that state wasn't captured.
- **G2 — `perf_frames` ignored on first boot (VERIFIED live).**
  - `_restore_performance_settings()` runs before
    `_migrate_config_to_menu()` (`app.py:6662-6664`).
  - On the first boot the restore finds no `perf_perf_frames`, so it
    leaves perf off. The migration then copies `True` into the store.
  - The run loop's fallback applies the config value only when the key is
    missing (`6707`), so perf stays off for that boot.
  - Run 1 had `perf_frames = true` and logged zero `Perf frame` lines.
    Run 2, same store, logged them.

## Checked, not bugs

- **Live detection:** in run 1 the APC opened as a dual-port bind (Notes + Control). In run 2 the REV1 opened as the aux device with its LED output port.
  The libusb claim succeeded, and the first push lit 84 LEDs.
- **LED double tick:** `MidiControllerManager.update()` and
  `render_overlay()` both call `APCLedFeedback.update()` each frame. The
  0.05 s throttle makes the second call a no-op.
- **MIDI dispatch threading:** `HotkeyHandler` queues rtmidi events under a
  lock and dispatches them on the main thread. REV1 LOAD only enqueues to
  the browser's loader thread.
- **REV1 map:** channel and note collisions checked. CC 31 (platter
  +SHIFT / crossfader) and note 99 (MASTER CUE / FX SHIFT SELECT) collide
  only across different channels. Every LSB is unique within its channel.
- **Loop-pad match:** `_active_loop_pad` uses track-time seconds with the
  track-grid BPM, which is consistent.
- **Roll/trans pad release** while a quantized press is pending is already
  reported as U3 in the UI audit.
- **Log noise, not app bugs:**
  - `libGL: Error in /etc/drirc` is the system file.
  - `libdecor-gtk` failing to init is the Wayland session.
  - `ImageShowcase: no images` is expected: the seat has no gitignored
    image assets.

## Suggested order

1. **H13.** A small change brings back all REV1 LED feedback, dark in every
   session for a week.
2. **H1 + H2 + H14.** Controller reconnect and a clean libusb release. A
   cable blip is the most likely live-show hardware failure, and today it
   kills both controllers until a restart or menu dance.
3. **G3.** Guard `_audio_manager.stop()` and make the helpers ignore
   SIGINT, so Ctrl+C stops losing state.
4. **G1.** One-character fix (`60.0`); unblocks the documented launch
   command.
5. **H3.** Gate the claim and the injection on the configured device.
6. **H4.** Give the dead faders app-level targets, and fix the help modal.
7. **H8, H7, H5**, then the rest.
