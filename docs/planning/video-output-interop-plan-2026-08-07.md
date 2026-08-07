# Video Output Interop Plan — PipeWire/DMA-BUF, v4l2loopback, NDI

Owner: owner + agents
Status: **Phase 0 (frame tap) DONE** — core 1.0.0-beta.46. Phasing confirmed
  by owner 2026-08-07: v4l2loopback first, libfunnel pinned behind our own
  abstraction (PR upstream if it needs changes).
Last updated: 2026-08-07

Closes the single worst row on the [scorecard](../scorecard.md): **video
output interop**, where we grade **D** and every rival except projectM holds
an A. Today the only way to get unicorn-viz into OBS, Resolume, or a second
machine is to screen-capture a window.

Ordering is **Linux first** — it is our primary platform, it is the platform
with the least prior art, and it is where our users actually are.

---

## 0. The problem in one paragraph

Every serious visual tool can hand its output to another application as a
live video source. Three ecosystem-specific mechanisms dominate:

| Mechanism | Platform | Transport | Cost |
|---|---|---|---|
| **Syphon** | macOS | GPU texture via IOSurface | zero-copy, ~0 latency |
| **Spout** | Windows | GPU texture via DirectX shared handle | zero-copy, ~0 latency |
| **NDI** | any | compressed video over IP | encode + network + decode |
| **PipeWire + DMA-BUF** | **Linux** | GPU buffer via dmabuf FD | zero-copy, ~0 latency |
| **v4l2loopback** | Linux | virtual V4L2 camera device | one CPU copy + convert |

Spout and Syphon are same-machine only. NDI is the only one that crosses
machines. On Linux the zero-copy equivalent is PipeWire carrying DMA-BUF
buffers — the same machinery Wayland screen sharing runs on.

---

## 1. What consumes what (verified 2026-08-07)

This table decides the phase order, because it is about what works in
**the owner's actual OBS rig** with no extra moving parts.

| Producer path | OBS on Linux | GStreamer | Resolume / other | Notes |
|---|---|---|---|---|
| **v4l2loopback** | ✅ **native** (Video Capture Device) | ✅ `v4l2src` | ✅ anything V4L2 | Needs the `v4l2loopback` kernel module (DKMS) installed once |
| **PipeWire video node** | ⚠️ needs [`obs-pwvideo`](https://github.com/raslen131/obs-pwvideo) plugin | ✅ `pipewiresrc` | varies | OBS's built-in PipeWire support is *portal screencast*, not arbitrary nodes |
| **NDI** | ⚠️ needs [DistroAV](https://obsproject.com/forum/resources/distroav-network-audio-video-in-obs-studio-using-ndi%C2%AE-technology.528/) plugin | ✅ via plugin | ✅ Resolume, vMix, etc. | DistroAV 6.2.x wants OBS ≥ 31.1.1 and NDI Runtime ≥ 6.3 |

**Consequence:** v4l2loopback is the only path that works with a stock OBS
install. PipeWire is the technically correct path but asks the user for a
plugin. Both are worth having, for different reasons.

---

## 2. Architectural prerequisite — one readback, fanned out

**Do this before adding any new consumer.** Today recording and streaming
each perform their **own** GPU→CPU readback of the same frame. Adding
v4l2loopback and NDI naively would make that four readbacks per frame of the
identical picture — at 1080p60 that is ~500 MB/s of pointless PCIe traffic,
and the 2026-08-03 audit already flagged the synchronous recording readback
as a frame-budget problem.

Introduce a single **frame tap** in core:

- One asynchronous PBO readback per frame, *only when at least one consumer
  is subscribed*, at the slowest rate any subscriber needs.
- Consumers register `(name, pixel_format, max_fps)` and receive a
  read-only view; the tap owns the buffer lifetime.
- Zero-copy consumers (PipeWire/DMA-BUF) **bypass the tap entirely** and take
  the GL texture handle directly — they must never trigger a readback.
- Existing recording and streaming migrate onto the tap, which by itself
  removes one redundant readback and lets recording finally reuse the PBO
  path the audit recommended.

This is the piece that makes the rest cheap, and it pays for itself even if
only recording and streaming ever use it.

---

## 2.5 Where this code lives — decided

**One new drop-in, `video-out-01`, houses every publisher** (v4l2loopback,
PipeWire/DMA-BUF, NDI, and later Spout/Syphon). Core gains only the frame
tap. Owner delegated this call on 2026-08-07; the reasoning, so it can be
revisited on evidence rather than taste:

- **Not inside `streaming-01`.** That drop-in broadcasts *to a service* —
  an RTMP session you deliberately start and stop, with a stream key and a
  destination. Interop is ambient plumbing: it makes the show available to
  whatever is on the machine or the LAN. Same frames, different concern and
  different lifecycle; merging them would tangle "am I live?" with "is my
  output visible to OBS?", which are questions an operator must be able to
  answer separately.
- **Not four separate drop-ins.** Every publisher needs the same
  scaffolding: tap subscription, rate capping, a bounded-queue writer
  thread, format negotiation, graceful-absence handling, and a status line.
  Split four ways that machinery gets copy-pasted four times and drifts —
  exactly how the `webcam-01`/`videos-01` frame handling diverged.
- **One config family, one status surface.** `[video_out.v4l2]`,
  `[video_out.pipewire]`, `[video_out.ndi]` read as one feature with
  backends, which is what it is. The HUD shows one "interop" line listing
  active outputs and their modes.
- **The platform split stays internal.** A user on Linux never sees the
  Spout code path; each backend self-disables on platforms where it cannot
  work, the same way `midi-controllers-01` handles the libusb LED path.

The one thing that stays in core is the frame tap (§2), because recording
and streaming — both core-adjacent and already shipping — need it too, and a
drop-in must never be a hard dependency of core.

## 3. Phase 1 — v4l2loopback (Linux, ships first)

**Why first:** works with stock OBS, no plugin, no new GPU code, and reuses
the frame tap we just built. It is the "works today" path.

- New drop-in **`video-out-01`** (per the drop-in policy: its own private
  repo, wired as a submodule, guarded `load_dropin_symbol` in core).
- Subscribe to the frame tap; write frames to a configured
  `/dev/videoN` node.
- Format: negotiate `YUYV` or `RGB24` — OBS accepts both; RGB24 avoids a
  colour conversion at our end at the cost of bandwidth. Start with RGB24,
  measure, add YUV conversion only if the copy shows up in the frame budget.
- Config:
  ```toml
  [video_out.v4l2]
  enabled = false          # opt-in: creating a fake camera unasked is rude
  device = "/dev/video10"
  fps_cap = 30             # decouple from render rate
  ```
- **Setup burden is real and must be documented**: `v4l2loopback` is an
  out-of-tree kernel module needing DKMS, plus a `modprobe` with
  `exclusive_caps=1` (required for Chromium-family consumers). Ship a
  `tools/install/v4l2loopback_setup.sh` and a troubleshooting page — a
  silent "no device" failure here would be worse than not shipping it.
- Degrade honestly: if the device is absent, log one clear warning naming
  the setup script and stay disabled. Never crash, never retry-spam.

**Acceptance:** OBS on Fedora shows "Unicorn Viz" as a Video Capture Device
and displays the live show, with the render loop's frame time unchanged
within noise when the cap is 30 fps.

---

## 4. Phase 2 — PipeWire + DMA-BUF (Linux, the real one)

**Why second:** it is the correct, zero-copy, Wayland-native answer, and the
one that makes us a first-class citizen on modern Linux — but it needs real
EGL work and asks OBS users for a plugin.

**Mechanism:**
1. Get the texture name from moderngl (`texture.glo`).
2. Export it via EGL: `eglCreateImageKHR(EGL_GL_TEXTURE_2D_KHR, tex)` then
   `eglExportDMABUFImageMESA` → dmabuf FD + stride + offset + modifier.
   (SDL gives us the EGLDisplay/EGLContext on Wayland; on X11/GLX this path
   does not exist and Phase 1 remains the fallback.)
3. Publish as a PipeWire video node with `SPA_DATA_DmaBuf`.

**Implementation choice — decide before starting:**

| Option | Pros | Cons |
|---|---|---|
| **A. ctypes binding to [libfunnel](https://github.com/hoshinolina/libfunnel)** | MIT, purpose-built ("Spout2/Syphon but for Linux"), handles sync modes + multi-GPU | **API explicitly unstable**; adds a C dependency users must build |
| **B. Direct PipeWire via ctypes** | no third-party dep, full control | substantial work: node negotiation, format params, buffer pools, explicit sync |
| **C. GStreamer `appsrc → pipewiresink`** | mature, well-documented | pulls in PyGObject + GStreamer — a heavy dependency for one feature |

**Recommendation: A, behind our own thin interface**, so that if libfunnel's
API churns or stalls we can swap to B without touching the drop-in's public
surface. Pin the commit; vendor the build into `install.sh`.

**Fallback within the phase:** if dmabuf export fails (proprietary driver
quirks, X11 session, cross-GPU), fall back to PipeWire **SHM** buffers —
still a valid PipeWire node, just with a copy. Log which mode is active;
never fail silently into the slow path without saying so.

**Acceptance:** with `obs-pwvideo` installed, OBS lists "Unicorn Viz" as a
PipeWire Video source; `pw-top` shows the stream in dmabuf mode; frame time
is unchanged from baseline because no readback occurs.

---

## 5. Phase 3 — NDI (cross-machine, all platforms)

**Why third:** it is the only mechanism that crosses machines, which is the
real "visuals box + stream box" venue setup — but it is also the only one
with licensing strings.

- NDI SDK is royalty-free **but redistribution is governed by NewTek/Vizrt's
  licence**. Follow DistroAV's pattern: **do not bundle the runtime**; detect
  it, and if absent print a link and stay disabled. This keeps our MIT story
  clean.
- ctypes binding to `libndi`; feed it CPU frames from the frame tap (NDI
  encodes, so zero-copy is not on the table anyway).
- Config mirrors the others, `enabled = false` by default, with a source
  name (`Unicorn Viz`), fps cap, and optional alpha.
- Bandwidth honesty in the docs: NDI full-quality 1080p60 is roughly
  100–150 Mbit/s. On a gigabit LAN that is fine; on shared wifi it is not.

**Acceptance:** a second machine on the LAN running OBS + DistroAV
discovers and displays the feed.

---

## 6. Phase 4 — Spout (Windows) and Syphon (macOS)

Deferred until those platforms are themselves solid; both are well-trodden
and neither should be a surprise.

- **Spout**: DirectX shared texture. Under SDL+OpenGL on Windows this needs
  the `WGL_NV_DX_interop2` bridge to hand a GL texture to a D3D11 shared
  surface — the standard approach and the same one every GL-based Spout
  sender uses.
- **Syphon**: Objective-C framework over IOSurface; needs a small native
  shim. Comes essentially free with a macOS port, and Mac VJs will expect it
  before they expect anything else.

---

## 7. Shared design rules (apply to every phase)

1. **Opt-in.** Every path defaults `enabled = false`. Publishing our video
   to the system unasked — especially a fake webcam — is a privacy call the
   user makes, not us. (Same lesson as webcam-01 capturing while hidden.)
2. **Never stall the render thread.** All CPU paths write from the tap's
   worker thread with a bounded queue and frame dropping, exactly like the
   streaming writer fixed in streaming-01 0.5.1.
3. **Independent rate caps.** A 30 fps interop feed on a 60 fps show is
   normal and should not force the show to 30.
4. **One status surface.** The HUD/control room should show which interop
   outputs are live, in what mode (dmabuf vs SHM vs copy), so a degraded
   path is visible rather than mysterious.
5. **Drop-in independence.** Core gains only the frame tap; every publisher
   lives in `video-out-01` behind guarded loading.

---

## 8. Scorecard impact

| Row | Now | After P1 | After P2 | After P3 |
|---|:-:|:-:|:-:|:-:|
| Video output interop | **D** | C+ | B+ | **A−** |

A− rather than A until Spout/Syphon land, because a Windows or Mac user
still gets nothing. With Phase 3 done we would hold NDI parity with the
entire field and be the *only* product here with a first-class Linux
zero-copy path — projectM included, since it is a library that leaves
interop to its host.

---

## 9. Decisions taken

**Decided (owner delegated 2026-08-07):**

- **Packaging:** one `video-out-01` drop-in for all backends; frame tap in
  core — see §2.5 for the reasoning.
- **NDI runtime:** detect, don't bundle. Keeps our MIT licensing clean and
  matches how DistroAV handles the same constraint.
- **Everything opt-in**, defaulting off (§7.1).

**Also decided 2026-08-07 (owner):**

- **Phase order: v4l2loopback first.** A working path beats a correct path
  you cannot yet look at; Phase 2 replaces it transparently.
- **libfunnel: pin it**, behind our own abstraction, and submit PRs upstream
  if we need changes rather than forking.
- **Frame tap: done first** (§2), shipped in core 1.0.0-beta.46 ahead of any
  publisher — see the Status header.

**Nothing outstanding.** Phase 1 can start whenever.
