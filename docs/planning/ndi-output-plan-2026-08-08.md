# NDI output — `ndi-out-01` drop-in plan

Owner: owner + agents
Status: **Deferred** — designed, not started. Blocked on an owner action
(SDK acceptance), not on engineering.
Last updated: 2026-08-08

Phase 3 of the video output interop work. Phases 1 and 2 shipped:
v4l2loopback and PipeWire/DMA-BUF both live in
[`video-out-01`](video-output-interop-plan-2026-08-07.md). NDI is the
remaining row on the scorecard's video-interop line, and the only one that
carries a licensing consequence.

---

## 1. Why this is a separate drop-in

NDI is **not** another backend inside `video-out-01`, by owner decision on
2026-08-08, and the reasoning is worth recording because it is not
primarily about code layout:

| Component | License of the thing it binds |
|---|---|
| v4l2loopback sink | GPL kernel module, spoken to through ioctls |
| PipeWire / libfunnel | MIT |
| **NDI** | **Vizrt proprietary SDK + EULA, with redistribution terms** |

Folding NDI into `video-out-01` would put a proprietary dependency inside a
component that is otherwise cleanly licensed and freely shareable. Anyone
taking `video-out-01` — including us, if drop-ins are ever opened up (see
the RC1 public-channel decision) — would inherit an NDI obligation they did
not ask for. Isolating it keeps that boundary honest, and makes "ship
without NDI" a packaging decision rather than a code change.

This also matches how the runtime already treats optional capability: the
drop-in is absent, and everything degrades to working-without-it.

---

## 2. The blocker, stated plainly

`libndi.so` comes only from Vizrt's NDI SDK. Verified on the owner's
machine 2026-08-08:

```
ldconfig -p | grep -i ndi     -> nothing
find / -name 'libndi*.so*'    -> nothing
ffmpeg -devices | grep -i ndi -> nothing
```

ffmpeg **removed** its NDI support in 2021 over the same licensing
question, so there is no route through it either, and there is no
free-software reimplementation worth binding against.

The SDK is free of charge but sits behind a registration form and an EULA
acceptance. That is a human action and an owner decision — an agent should
not accept a license on the owner's behalf. **This is the only thing
standing between the plan and the work.**

### Why we are not writing the binding first

The libfunnel work is the precedent. Building and running it surfaced five
binding bugs that reading the headers had not:

- EGL symbols lived in a separate `libfunnel-egl.so`;
- a wrong enum value;
- dequeue returning `1` rather than the documented value;
- blocking-mode behaviour that differed from the docs;
- an `assert()` that **aborts the process** on a misordered call.

Every one of those is the kind of defect a ctypes binding hides until it
runs. Shipping an NDI binding that has never executed a single call would
be the same mistake with a proprietary SDK on the other side of it, and
the failure mode — a native abort mid-set — is one this project has already
paid for twice this week.

---

## 3. Shape

Mirrors `video-out-01`, which has proved the pattern end to end.

```
drop-ins/ndi-out-01/
  ndi_sender.py            ctypes binding; resolves libndi.so at runtime
  ndi_out_controller.py    same controller contract as VideoOutController
  install.sh               detects the SDK, points at the download, never fetches it
  README.md                status/version header + changelog
  docs/                    operations / configuration / integration / troubleshooting
```

**Core integration is already built.** `ndi-out-01` implements the same
contract the frame tap and `app.py` use today, so wiring is one more
guarded `load_dropin_symbol()` site next to `multi-head-01`, `webcam-01`,
`streaming-01` and `video-out-01` — no new core mechanism.

**Frame path:** NDI wants packed BGRA (or UYVY) at the full output rate, so
it subscribes to the **frame tap** exactly as the v4l2 sink does, and
inherits the readback the tap already performs for recording/streaming. It
deliberately does *not* use the zero-copy GPU path that PipeWire takes —
NDI's API accepts a CPU buffer, so a GPU handle buys nothing.

**Rate cap:** subscribes with `max_fps` from config, so an NDI receiver
cannot force a readback faster than the network can carry.

---

## 4. Config surface (proposed)

```toml
[ndi_out]
enabled = false            # off until the SDK is present
source_name = "Unicorn Viz"  # what receivers see on the network
fps_cap = 30               # frame-tap ceiling
pixel_format = "BGRA"      # BGRA | UYVY (UYVY halves bandwidth, costs a convert)
groups = ""                # optional NDI group restriction
```

Plus `--ndi` / `--no-ndi` and `--ndi-name NAME`, matching the CLI-drivable
pattern the headless work established.

---

## 5. Acceptance

The work is done when all of these are observed, not inferred:

1. **Absent SDK degrades silently.** With no `libndi.so`, the app starts,
   logs one INFO line, and behaves exactly as it does today. This half is
   testable *now* and should be built and tested first.
2. A running Unicorn Viz appears as an **NDI source on the network**,
   discoverable from another machine.
3. A receiver (OBS + DistroAV, or NDI Studio Monitor) shows **live frames**
   at the configured rate.
4. Enabling NDI while recording and streaming does **not** add a second
   readback — the tap's `readbacks_saved` counter proves the frame is
   shared.
5. Stopping the receiver, then the sender, leaves no wedged thread and no
   native abort at exit.
6. `[ndi_out] enabled = false` is indistinguishable from the drop-in being
   absent.

---

## 6. Sequencing

1. **Owner:** accept the EULA and install the NDI SDK
   (`ndi.video/download-ndi-sdk`), place `libndi.so` where `ldconfig`
   finds it. *(blocking)*
2. Create the private repo, wire the submodule, scaffold the drop-in.
3. Build the **absent-SDK path first** and test it — that is the path most
   users will take, and it is the one that must never break the app.
4. Bind and verify the sender against the installed SDK, one call at a
   time, the way libfunnel had to be done.
5. Verify against OBS + DistroAV on a second machine.
6. Scorecard: video interop **B → A-**; Spout/Syphon parity still open for
   Windows/macOS.

---

## 7. What this plan does not claim

It does not claim NDI is nearly done. Nothing has been written. The design
is settled and the integration points already exist, which is why the
estimate is small once the SDK is present — but the estimate is *worthless*
until something has actually executed, and this document exists partly to
stop a future reader assuming otherwise.
