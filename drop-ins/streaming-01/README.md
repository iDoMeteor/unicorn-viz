# streaming-01 — RTMP Live Streaming

A subsystem drop-in for [unicorn-viz](https://github.com/iDoMeteor/unicorn-viz) that streams live audio and video to RTMP endpoints (Rumble, YouTube, custom RTMP servers).

## Description

Streaming-01 manages an ffmpeg process that receives raw RGB frames and PCM audio from Unicorn Viz and re-encodes them in real-time for broadcast to an RTMP destination. The drop-in handles process lifecycle, bitrate/codec negotiation, and graceful error recovery.

**Status:** Production-ready for Linux and macOS; Windows support requires manual ffmpeg installation and PATH configuration.

## Features

- **Multi-provider support** — Rumble, YouTube, custom RTMP endpoints
- **Audio/video synchronization** — ffmpeg manages A/V sync automatically
- **Live provider switching** — change RTMP endpoint without restarting the stream
- **Configurable codec/bitrate** — H.264 video + AAC audio (customizable)
- **Frame/audio buffering** — PBO-based frame readback + PulseAudio/ALSA input
- **HUD status display** — streaming state, provider, FPS, bitrate visible on-screen
- **Hotkey control** — toggle streaming and switch providers with keyboard shortcuts
- **Error recovery** — graceful fallback if ffmpeg is unavailable or stream connection fails

## Hotkeys

| Key | Action |
|-----|--------|
| `F8` | Toggle RTMP streaming on/off |
| `Ctrl+F9` | Set streaming provider to **Rumble** |
| `Ctrl+F10` | Set streaming provider to **YouTube** |
| `Ctrl+F11` | Set streaming provider to **Custom RTMP** |

These hotkeys appear in the `H` help overlay under the **Streaming** section.

## Configuration

```toml
[streaming]
# Global streaming enable/disable
enabled = false

# Auto-start streaming on app launch
auto_start = false

# Active provider: "rumble", "youtube", or "custom"
provider = "rumble"

# RTMP endpoint URLs
rumble_endpoint = "rtmp://live-api-s.rumble.com/live"
youtube_endpoint = "rtmp://a.rtmp.youtube.com/live2"
custom_endpoint = "rtmp://your.rtmp.server/live"

# Stream key/credential appended to endpoint
stream_key = "your-stream-key-here"

# Optional: fully-qualified RTMP URL (overrides endpoint + stream_key if set)
stream_url = ""

# ffmpeg executable (default: "ffmpeg" on PATH)
ffmpeg_path = "ffmpeg"

# Video encoding
fps = 60
video_codec = "libx264"      # H.264 (fast, widely compatible)
preset = "veryfast"          # encoding speed/quality tradeoff
pixel_format = "yuv420p"     # standard for RTMP delivery

# Audio encoding
include_audio = true
audio_input_format = "pulse" # Linux: pulse | ALSA: alsa | macOS: avfoundation
audio_input_device = ""      # auto-detect if empty
audio_codec = "aac"
audio_bitrate = "160k"
```

### Provider Setup

#### Rumble

1. Log in to [rumble.com](https://rumble.com)
2. Go to **Creator Hub** → **Live** → **Settings**
3. Copy the **RTMP Server URL** and **Stream Key**
4. Set in `config.toml`:
   ```toml
   [streaming]
   provider = "rumble"
   stream_key = "your-rumble-stream-key"
   ```

#### YouTube

1. Log in to [youtube.com/creator_studio](https://youtube.com/creator_studio)
2. Select **Go Live** and switch to **Stream Key** view
3. Copy the **Stream Key** (not the full URL)
4. Set in `config.toml`:
   ```toml
   [streaming]
   provider = "youtube"
   stream_key = "your-youtube-stream-key"
   ```

#### Custom RTMP Server

For self-hosted or third-party RTMP servers (Twitch, OBS Studio, etc.):

```toml
[streaming]
provider = "custom"
custom_endpoint = "rtmp://your-server-address/live"
stream_key = "your-stream-key"
```

### Runtime Behavior

1. **Start streaming** — Press `F8` to launch the ffmpeg process
2. **Live encode** — RGB frames are captured via PBO readback; audio is piped from PulseAudio/ALSA
3. **Provider switch** — Press `Ctrl+F9/F10/F11` to change RTMP destination without dropping the stream
4. **HUD feedback** — the overlay shows `STREAMING ON` and the active provider name
5. **Stop streaming** — Press `F8` again; ffmpeg process terminates gracefully

If the ffmpeg process crashes or the network connection drops, Unicorn Viz continues playback normally. The next `F8` press will attempt to restart the stream.

## Dependencies

### ffmpeg

**Required:** `ffmpeg` binary must be installed and on `$PATH`, or set explicitly in `ffmpeg_path`.

#### Linux (Fedora/RHEL)
```bash
sudo dnf install ffmpeg
```

#### Linux (Debian/Ubuntu)
```bash
sudo apt install ffmpeg
```

#### Linux (Arch)
```bash
sudo pacman -S ffmpeg
```

#### macOS
```bash
brew install ffmpeg
```

#### Windows

Download and install from [ffmpeg.org](https://ffmpeg.org/download.html), or use a package manager:
```powershell
# Chocolatey
choco install ffmpeg

# Scoop
scoop install ffmpeg
```

Then verify it's on your PATH:
```cmd
ffmpeg -version
```

### Audio Input Device

**Linux (PulseAudio):**
- Default device: auto-detected
- Custom device: `pactl list short sources`

**Linux (ALSA):**
- Default device: `default`
- List devices: `arecord -l`

**macOS:**
- Default device: built-in mic
- Custom device: `ffmpeg -f avfoundation -list_devices true -i ""`

**Windows:**
- Uses DirectShow by default
- Custom device: test with `ffmpeg -list_devices true -f dshow -i dummy`

### Network Requirements

- **Stable internet connection** required for live streaming
- **Upload bandwidth:** minimum 5 Mbps for 1080p @ 60 fps (adjust bitrate if needed)
- **Firewall/NAT:** RTMP uses port 1935 (TCP); ensure outbound traffic is allowed
- **ISP considerations:** some ISPs throttle or block RTMP; try custom RTMP server or check with your ISP

## Interaction with Other Drop-ins

- **Independent** — streaming operates alongside all other drop-ins
- **No conflicts** with multi-head, webcam, or effect drop-ins
- **Requires** frame readback capability from multi-head (if present)
- **Audio passthrough** — streaming audio is independent of what's playing through the system speaker

## Troubleshooting

**"ffmpeg not found":**
- Ensure ffmpeg is installed on your system
- Verify it's on `$PATH`: `which ffmpeg` (macOS/Linux) or `where ffmpeg` (Windows)
- If installed but not on PATH, set absolute path in `config.toml`: `ffmpeg_path = "/usr/bin/ffmpeg"`

**"Connection refused" or "Connection timeout":**
- Check your stream key is correct (copy/paste from provider website)
- Verify your internet connection is stable
- Confirm the RTMP endpoint is reachable: `telnet <endpoint-host> 1935` (if available)
- Try a custom test server to isolate provider issues

**Stream starts but video is blank or black:**
- Confirm Unicorn Viz is rendering normally (check main output)
- Verify multi-head drop-in is loaded and PBO readback is functional
- Check ffmpeg stderr logs in terminal

**Audio/video out of sync:**
- Reduce encoding complexity: `preset = "faster"` (trades quality for lower latency)
- Lower video bitrate if network is congested
- Restart the stream with `F8` toggle

**High CPU usage:**
- Lower `fps` to 30 or reduce resolution scale
- Use faster preset: `preset = "faster"` or `"veryfast"`
- Disable audio if not needed: `include_audio = false`

**Streaming works locally but not remotely (viewers can't tune in):**
- Check streaming provider account/dashboard for stream status
- Verify stream key matches provider's expectations (some providers regenerate keys periodically)
- Confirm stream is set to "Live" or "Public" on provider site

## Architecture

- **Frame capture** — multi-head drop-in manages PBO readback; RGB frames are posted to ffmpeg stdin
- **Audio capture** — ffmpeg natively opens the configured audio device (PulseAudio, ALSA, etc.)
- **Process management** — `RTMPStreamer` spawns/monitors the ffmpeg subprocess; graceful shutdown on app exit
- **Error handling** — stream failures don't crash the app; next `F8` press attempts restart
- **HUD integration** — streaming status and provider name broadcast via standard overlay state system

## Performance Notes

- **Frame readback:** ~1–2 ms per frame (depends on resolution; uses double-buffered PBOs)
- **ffmpeg re-encoding:** typically 10–20 ms per frame on modern CPUs
- **Network lag:** typically 3–8 seconds from capture to live viewers (inherent RTMP latency)

If streaming causes frame drops, try:
- Lowering video resolution (scale with `K` / `Shift+K`)
- Reducing FPS in config (set `fps = 30`)
- Switching to a faster encoding preset

## Developer Notes

For those interested in extending Streaming-01:

- The `RTMPStreamer` class can be subclassed to support additional streaming protocols (HLS, DASH, WebRTC)
- ffmpeg arguments are generated dynamically; custom codec chains can be injected via config
- The audio device selection logic can be extended to support explicit device names per platform
