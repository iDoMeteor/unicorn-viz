"""Recording support for Unicorn Viz.

This module manages a simple ffmpeg subprocess that accepts raw RGB frames
from the app and writes H.264 MP4 output. V1 records video only.

Frame writes are decoupled from the render loop.  ``write_frame()`` only
publishes the newest frame into a slot and returns; a dedicated writer
thread (``uv-rec-writer``) paces that slot out to ffmpeg's stdin at a
**constant** rate, duplicating the last frame when the render loop falls
behind.  This is what keeps a recording playing back at real-time speed
and in sync with its live audio track even when the app is rendering well
below the target rate.

A second thread (``uv-rec-stderr``) drains ffmpeg's stderr, both so a full
pipe buffer cannot stall the encoder and so failures can be reported with
ffmpeg's own explanation attached.
"""
from __future__ import annotations

import logging
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from unicornviz.audio.pactl import run_pactl
from unicornviz.config import Config
from unicornviz.paths import resolve_path

log = logging.getLogger(__name__)


def _send_graceful_stop(process: subprocess.Popen) -> None:
    """Ask ffmpeg to finalize its output, portably.

    ``send_signal(SIGINT)`` raises ValueError on Windows Popen objects —
    which previously aborted the stop path, orphaning ffmpeg with an
    unfinalized (unplayable) MP4. Windows uses CTRL_BREAK_EVENT, which
    requires the process to have been started with CREATE_NEW_PROCESS_GROUP.
    """
    if sys.platform == 'win32':
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGINT)


#: Hardware H.264 encoders, best-first.  Each entry is
#: ``(codec, pre_input_args, filter_suffix, quality_flag)``:
#:
#: * ``pre_input_args`` must appear before any ``-i`` (VA-API opens its
#:   device there);
#: * ``filter_suffix`` is appended to the video filter chain, since VA-API
#:   encodes from GPU surfaces and needs the frame uploaded first;
#: * ``quality_flag`` replaces ``-crf``, which is an x264 concept the
#:   hardware encoders reject.
_HW_ENCODERS: tuple[tuple[str, list[str], str, str], ...] = (
    ('h264_nvenc', [], '', '-cq'),
    ('h264_vaapi', ['-vaapi_device', '{device}'], 'format=nv12,hwupload', '-qp'),
    ('h264_qsv', [], '', '-global_quality'),
)

#: Probe result, cached for the process.  ``False`` means "probed, none work".
_hw_encoder_cache: tuple[str, list[str], str, str] | None | bool = None
# Serializes the probe so a recording started while the startup prewarm is
# still running waits for that result instead of launching a second ffmpeg.
_hw_probe_lock = threading.Lock()


def prewarm_hw_encoder_probe(ffmpeg_path: str) -> threading.Thread:
    """Run the hardware-encoder probe on a daemon thread at startup.

    The probe encodes one test frame per candidate with a 20 s ceiling
    each; done lazily it landed on the main thread the moment the operator
    hit record.  Started at boot it is finished long before that.
    """
    t = threading.Thread(
        target=_probe_hw_encoder, args=(ffmpeg_path,),
        name='uv-hw-encoder-probe', daemon=True,
    )
    t.start()
    return t


def _render_device() -> str:
    """First DRM render node, used as the VA-API device."""
    nodes = sorted(Path('/dev/dri').glob('renderD*')) if Path('/dev/dri').is_dir() else []
    return str(nodes[0]) if nodes else '/dev/dri/renderD128'


def _probe_hw_encoder(ffmpeg_path: str) -> tuple[str, list[str], str, str] | None:
    """Return the first hardware encoder that actually encodes, or None.

    Being *built* into ffmpeg says nothing about whether it runs here: a
    driver may be missing, or -- on Fedora -- present but built without the
    patent-encumbered encoders, which reports 'No usable encoding profile
    found' only when you try.  So each candidate is asked to encode a real
    frame, and the answer is cached for the process.
    """
    global _hw_encoder_cache
    if _hw_encoder_cache is not None:
        return _hw_encoder_cache or None
    with _hw_probe_lock:
        if _hw_encoder_cache is not None:      # the prewarm finished while we waited
            return _hw_encoder_cache or None
        return _probe_hw_encoder_locked(ffmpeg_path)


def _probe_hw_encoder_locked(ffmpeg_path: str) -> tuple[str, list[str], str, str] | None:
    global _hw_encoder_cache
    device = _render_device()
    for codec, pre_input, filt, quality in _HW_ENCODERS:
        pre = [a.format(device=device) for a in pre_input]
        cmd = [
            ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-y',
            *pre,
            '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=30:duration=1',
        ]
        if filt:
            cmd += ['-vf', filt]
        cmd += ['-c:v', codec, '-f', 'null', '-']
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=20.0)
        except Exception as exc:
            log.debug('Recording: %s probe failed to run: %s', codec, exc)
            continue
        if proc.returncode == 0:
            log.info('Recording: hardware encoder available: %s', codec)
            _hw_encoder_cache = (codec, pre, filt, quality)
            return _hw_encoder_cache
        detail = (proc.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        log.debug('Recording: %s unavailable (%s)', codec,
                  detail[0] if detail else f'exit {proc.returncode}')

    log.info('Recording: no working hardware encoder; using software x264')
    _hw_encoder_cache = False
    return None


class Recorder:
    """Manage an ffmpeg subprocess for recording raw RGB frames to disk."""

    def __init__(self, cfg: Config, width: int, height: int) -> None:
        self._enabled = bool(cfg.get('recording', 'enabled', default=True))
        self._auto_record = bool(cfg.get('recording', 'auto_record', default=False))
        self._directory = resolve_path(cfg.get('recording', 'directory', default='recordings'))
        self._ffmpeg_path = str(cfg.get('recording', 'ffmpeg_path', default='ffmpeg'))
        self._container = str(cfg.get('recording', 'container', default='mp4'))
        self._fps = int(cfg.get('recording', 'fps', default=60))
        self._codec = str(cfg.get('recording', 'codec', default='auto'))
        self._preset = str(cfg.get('recording', 'preset', default='veryfast'))
        self._crf = int(cfg.get('recording', 'crf', default=18))
        self._pixel_format = str(cfg.get('recording', 'pixel_format', default='yuv420p'))
        self._capture_audio = bool(cfg.get('recording', 'capture_audio', default=True))
        self._audio_input_format = str(cfg.get('recording', 'audio_input_format', default='pulse'))
        self._audio_input_device = str(cfg.get('recording', 'audio_input_device', default='')).strip()
        self._audio_codec = str(cfg.get('recording', 'audio_codec', default='aac'))
        self._audio_bitrate = str(cfg.get('recording', 'audio_bitrate', default='192k'))
        self._filename_prefix = str(cfg.get('recording', 'filename_prefix', default='unicornviz'))
        self._show_indicator = bool(cfg.get('recording', 'show_indicator', default=True))
        self._width = width
        self._height = height
        self._process: subprocess.Popen[bytes] | None = None
        self._current_path: Path | None = None
        self._started_at: float = 0.0
        self._resolved_audio_input: tuple[str, str] | None = None
        # Set by the app from the analyzer's active source, see
        # set_audio_source_hint().
        self._source_hint: str = ''
        # Encoder actually selected at spawn (see _resolve_encoder).
        self._active_codec: str = ''
        self._retrying_software: bool = False
        self._last_error: str = ''
        # Async writer state.  The render thread publishes into a single
        # latest-frame slot; a daemon thread paces that slot out to ffmpeg's
        # stdin at a constant rate (see _frame_writer_worker).
        self._frame_lock = threading.Lock()
        self._latest_frame: bytes | None = None
        self._writer_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._recording_stopping: bool = False
        # Wallclock pacing state, all owned by the writer thread.
        self._pacing_start: float = 0.0
        self._frames_written: int = 0
        self._frames_duplicated: int = 0
        self._frames_dropped: int = 0
        # Set by the writer thread when ffmpeg dies mid-recording; consumed
        # once by the app loop so the operator sees the failure instead of a
        # lit REC indicator silently dropping every frame.
        self._write_failed: bool = False
        self._failure_reported: bool = False
        # Ceiling on how many duplicate frames one catch-up burst may emit,
        # so a long render stall cannot make the writer flood ffmpeg with a
        # multi-second wall of frames it then has to encode all at once.
        self._max_catch_up_frames: int = max(1, self._fps)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def auto_record(self) -> bool:
        return self._auto_record

    @property
    def show_indicator(self) -> bool:
        return self._show_indicator

    @property
    def active_codec(self) -> str:
        """Encoder chosen for the current/most recent recording."""
        return self._active_codec or self._codec

    @property
    def target_fps(self) -> int:
        """Constant frame rate the output is muxed at.

        The app caps its frame-tap readback at this rate: frames rendered
        beyond it would be paced straight back out again, so reading them
        off the GPU is pure cost.
        """
        return self._fps

    @property
    def is_recording(self) -> bool:
        """True only while ffmpeg is genuinely alive and accepting frames.

        ``poll()`` matters: ffmpeg exiting on its own (bad audio device,
        disk full, unsupported encoder) used to leave this True forever, so
        the REC indicator stayed lit over a dead encoder while every frame
        was dropped on the floor.
        """
        proc = self._process
        return (
            proc is not None
            and proc.stdin is not None
            and proc.poll() is None
            and not self._write_failed
        )

    @property
    def has_failed(self) -> bool:
        """True when the writer thread hit a fatal ffmpeg write failure."""
        return self._write_failed

    def consume_failure(self) -> str | None:
        """Return the failure message once after a writer-thread death.

        Subsequent calls return None until the next failure; lets the app
        loop flash exactly one operator-facing notice per incident.
        """
        if self._write_failed and not self._failure_reported:
            self._failure_reported = True
            return self._last_error or 'recording writer failed'
        return None

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def elapsed_seconds(self) -> float:
        if not self.is_recording or self._started_at == 0.0:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    @property
    def resolved_audio_input(self) -> tuple[str, str] | None:
        return self._resolved_audio_input

    def _build_output_path(self) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return self._directory / f'{self._filename_prefix}_{ts}.{self._container}'

    def _pactl(self, *args: str) -> str | None:
        """Cached pactl query (unicornviz.audio.pactl); None when unavailable.

        Recording starts on the main thread; the three queries behind source
        resolution are answered from the shared cache, refreshed in the
        background every few seconds, instead of three fresh spawns.
        """
        return run_pactl(*args)

    def _pulse_sink_states(self) -> list[tuple[str, str]]:
        """Return ``(sink_name, state)`` for every sink, newest pactl format.

        ``pactl list short sinks`` emits tab-separated columns ending in the
        run state (RUNNING / IDLE / SUSPENDED).  Only the name and the state
        are load-bearing here, so the middle columns are ignored rather than
        parsed positionally — they differ between PulseAudio and PipeWire.
        """
        out = self._pactl('list', 'short', 'sinks')
        if not out:
            return []
        rows: list[tuple[str, str]] = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split('\t') if p.strip()]
            if len(parts) >= 3:
                rows.append((parts[1], parts[-1].upper()))
        return rows

    def _pulse_default_sink(self) -> str:
        """Return the server's default sink name, or '' when unknown."""
        out = self._pactl('info')
        if not out:
            return ''
        for line in out.splitlines():
            if line.startswith('Default Sink:'):
                return line.split(':', 1)[1].strip()
        return ''

    # Config-editor-tweakable settings: attribute name and inclusive range.
    # Everything here is read at spawn time, so a change lands on the next
    # recording rather than mutating one already in flight.
    TWEAKABLES: dict[str, tuple[str, float, float]] = {
        'fps': ('_fps', 15.0, 120.0),
        'crf': ('_crf', 0.0, 51.0),
        'capture_audio': ('_capture_audio', 0.0, 1.0),
        'auto_record': ('_auto_record', 0.0, 1.0),
        'show_indicator': ('_show_indicator', 0.0, 1.0),
    }

    def apply_setting(self, key: str, value: float) -> None:
        """Apply a config-editor tweakable to this recorder.

        Applies to the *next* recording: ffmpeg is configured entirely at
        spawn time, so changing frame rate or quality mid-encode is not
        something the format can express.
        """
        spec = self.TWEAKABLES.get(key)
        if spec is None:
            return
        attr, low, high = spec
        clamped = max(low, min(high, float(value)))
        current = getattr(self, attr)
        setattr(self, attr, type(current)(clamped) if isinstance(current, bool)
                else (int(clamped) if isinstance(current, int) else clamped))
        if key == 'fps':
            self._max_catch_up_frames = max(1, self._fps)

    def set_pulse_source_name(self, name: str) -> None:
        """Pin the ffmpeg audio device, or clear it to resume auto-detection."""
        self._audio_input_device = (name or '').strip()

    def available_audio_sources(self) -> list[tuple[str, str]]:
        """Return selectable ``(pulse_source_name, human_label)`` monitors.

        Used by the config editor's source picker so the operator can pin the
        output their set actually plays through instead of relying on
        detection.
        """
        out = self._pactl('list', 'sinks')
        if not out:
            return []
        sources: list[tuple[str, str]] = []
        name = ''
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith('Name:'):
                name = stripped.split(':', 1)[1].strip()
            elif stripped.startswith('Description:') and name:
                desc = stripped.split(':', 1)[1].strip()
                sources.append((f'{name}.monitor', desc))
                name = ''
        return sources

    def set_audio_source_hint(self, label: str | None) -> None:
        """Tell the recorder which audio source is driving the visuals.

        The app passes the analyzer's current source label here before
        starting.  Whatever the visualizer is listening to *is* the show
        audio by definition, which makes it a far better answer than any
        guess based on which output happens to look busy.
        """
        self._source_hint = (label or '').strip()

    def _sink_name_for_description(self, description: str) -> str:
        """Map a human-readable device description to a pulse sink name.

        sounddevice reports PipeWire endpoints by their *description*
        ('DDJ-REV1 Analog Surround 4.0') while ffmpeg needs the sink *name*
        ('alsa_output.usb-AlphaTheta_...analog-surround-40').  pactl is the
        only thing that knows both, so it does the translation.
        """
        out = self._pactl('list', 'sinks')
        if not out:
            return ''
        current_name = ''
        wanted = description.strip().lower()
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith('Name:'):
                current_name = stripped.split(':', 1)[1].strip()
            elif stripped.startswith('Description:'):
                if stripped.split(':', 1)[1].strip().lower() == wanted:
                    return current_name
        return ''

    def _resolve_pulse_source(self) -> str:
        """Resolve the Pulse/PipeWire source that actually carries the show.

        The previous implementation always took the **default sink's**
        monitor.  That is wrong for the setup this project exists to serve:
        when the set plays out of a DJ controller (or any non-default
        output), the default sink is idle and its monitor records digital
        silence — a recording with a valid, entirely empty audio stream.

        Resolution order:

        1. an explicit ``[recording] audio_input_device``;
        2. the source the **visualizer is analyzing** — the recording then
           always contains the audio that produced the visuals;
        3. the monitor of a sink that is **actually playing** (RUNNING),
           preferring the default sink when several are;
        4. the default sink's monitor, with a warning that it is idle;
        5. ``'default'`` when pactl is unavailable at all.
        """
        if self._audio_input_device:
            log.info(
                'Recording audio: using configured device %s',
                self._audio_input_device,
            )
            return self._audio_input_device

        hint = self._source_hint
        if hint and hint not in ('disabled', 'inactive', 'default input'):
            # The analyzer may already be on a monitor source; if the label
            # names a sink we know, capture that sink's monitor directly.
            sink = self._sink_name_for_description(hint)
            if sink:
                log.info(
                    'Recording audio: following the visualizer source "%s" -> %s',
                    hint,
                    sink,
                )
                return f'{sink}.monitor'
            log.debug(
                'Recording audio: visualizer source "%s" does not name a known '
                'output; falling back to output-state detection.',
                hint,
            )

        sinks = self._pulse_sink_states()
        default_sink = self._pulse_default_sink()
        running = [name for name, state in sinks if state == 'RUNNING']
        log.debug(
            'Recording audio source scan: default=%s sinks=%s',
            default_sink or '<unknown>',
            sinks or '<none>',
        )

        if running:
            chosen = default_sink if default_sink in running else running[0]
            if len(running) > 1:
                log.info(
                    'Recording audio: %d outputs are playing (%s); capturing %s. '
                    'Set [recording] audio_input_device to pin a specific one.',
                    len(running),
                    ', '.join(running),
                    chosen,
                )
            else:
                log.info('Recording audio: capturing the active output %s', chosen)
            return f'{chosen}.monitor'

        if default_sink:
            log.warning(
                'Recording audio: nothing is playing right now, so falling back '
                'to the default output monitor (%s). If the set plays through a '
                'different device the recording will be SILENT — set '
                '[recording] audio_input_device to that device.',
                default_sink,
            )
            return f'{default_sink}.monitor'

        log.warning(
            'Recording audio: could not query pactl; using the Pulse "default" '
            'source, which is normally a microphone rather than the show audio.'
        )
        return 'default'

    def _resolve_windows_dshow_device(self) -> str | None:
        """Enumerate DirectShow audio devices; pick a loopback-style source.

        Only loopback-class devices (Stereo Mix / virtual cables) are
        accepted — falling back to a microphone would silently record room
        noise instead of the show audio.
        """
        try:
            proc = subprocess.run(
                [self._ffmpeg_path, '-hide_banner', '-list_devices', 'true',
                 '-f', 'dshow', '-i', 'dummy'],
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            listing = (proc.stderr or '') + (proc.stdout or '')
        except Exception as exc:
            log.warning('Recording: dshow device enumeration failed: %s', exc)
            return None
        devices = re.findall(r'"([^"]+)"\s*\(audio\)', listing)
        for pattern in ('stereo mix', 'loopback', 'virtual-audio-capturer',
                        'cable output', 'what u hear'):
            for name in devices:
                if pattern in name.lower():
                    return name
        return None

    def _resolve_audio_input(self) -> tuple[str, str] | None:
        """Return the ffmpeg audio input (format, device), or None to skip audio.

        On Windows the Linux default 'pulse' is remapped to DirectShow with
        loopback-device discovery; when no loopback device exists the
        recording proceeds video-only (with an operator-facing warning)
        instead of failing to spawn ffmpeg at all.
        """
        input_format = self._audio_input_format.lower()
        if sys.platform == 'win32' and input_format in ('pulse', 'dshow', 'auto', ''):
            device = self._audio_input_device
            if device and not device.startswith(('audio=', 'video=')):
                device = f'audio={device}'
            if not device:
                found = self._resolve_windows_dshow_device()
                if found is None:
                    log.warning(
                        'Recording: no loopback audio device found — enable '
                        '"Stereo Mix" or install a virtual audio cable, or set '
                        '[recording] audio_input_device. Recording video-only.'
                    )
                    return None
                device = f'audio={found}'
            return 'dshow', device
        if input_format == 'pulse':
            return 'pulse', self._resolve_pulse_source()
        return input_format, self._audio_input_device or 'default'

    def _resolve_encoder(self) -> tuple[str, list[str], str, str]:
        """Return ``(codec, pre_input, filter_suffix, quality_flag)`` to use.

        ``codec = "auto"`` probes for a working hardware encoder and falls
        back to software x264 when none is usable -- which is the normal
        outcome on a stock Fedora box, where the shipped VA-API driver has
        no H.264 encoder at all.
        """
        if self._codec.strip().lower() == 'auto':
            hw = _probe_hw_encoder(self._ffmpeg_path)
            if hw is not None:
                return hw
            return 'libx264', [], '', '-crf'
        return self._codec, [], '', '-crf'

    def _build_command(self, output_path: Path) -> list[str]:
        codec, pre_input, filter_suffix, quality_flag = self._resolve_encoder()
        self._active_codec = codec
        command = [
            self._ffmpeg_path,
            '-y',
            *pre_input,
            '-loglevel',
            'error',
            '-nostdin',
            '-f',
            'rawvideo',
            '-pix_fmt',
            'rgb24',
            '-video_size',
            f'{self._width}x{self._height}',
            '-framerate',
            str(self._fps),
            # The writer thread paces frames to exactly this rate, so the
            # declared framerate and the real arrival rate agree.
            '-thread_queue_size',
            '64',
            '-i',
            '-',
        ]
        self._resolved_audio_input = (
            self._resolve_audio_input() if self._capture_audio else None
        )
        if self._resolved_audio_input is not None:
            audio_format, audio_device = self._resolved_audio_input
            command += [
                # A live capture cannot be back-pressured: if the muxer is
                # busy when samples arrive they are simply lost, which shows
                # up as audio dropouts.  A deep input queue absorbs that.
                '-thread_queue_size',
                '1024',
                '-f',
                audio_format,
                '-i',
                audio_device,
            ]
        # Map explicitly rather than relying on ffmpeg's automatic stream
        # selection, so a device that exposes several streams cannot quietly
        # change which one gets recorded.
        command += ['-map', '0:v:0']
        if self._resolved_audio_input is not None:
            command += ['-map', '1:a:0']
        # GL reads back bottom-up; flip once here rather than on the CPU.
        # Hardware encoders append their own upload step to this chain.
        vfilter = 'vflip' + (f',{filter_suffix}' if filter_suffix else '')
        command += ['-vf', vfilter, '-c:v', codec]
        if codec == 'libx264':
            # -preset is an x264 concept; hardware encoders name their own
            # speed controls differently and reject it.
            command += ['-preset', self._preset]
        command += [quality_flag, str(self._crf)]
        if not filter_suffix:
            # A GPU-surface pipeline sets its own output format; forcing one
            # here would insert a download and undo the point of the thing.
            command += ['-pix_fmt', self._pixel_format]
        command += ['-movflags', '+faststart']
        if self._resolved_audio_input is not None:
            command += [
                '-c:a',
                self._audio_codec,
                '-b:a',
                self._audio_bitrate,
                '-shortest',
            ]
        else:
            command.append('-an')
        command.append(str(output_path))
        return command

    def start(self) -> bool:
        """Start a new recording session."""
        if not self._enabled:
            self._last_error = 'Recording disabled'
            return False
        if self.is_recording:
            return True

        output_path = self._build_output_path()
        command = self._build_command(output_path)
        log.debug(
            'Recording start requested: size=%dx%d fps=%d codec=%s preset=%s crf=%d audio=%s output=%s',
            self._width,
            self._height,
            self._fps,
            self._codec,
            self._preset,
            self._crf,
            self._capture_audio,
            output_path,
        )
        log.debug('Recording command: %s', ' '.join(command))
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                # Captured, not discarded: this is the only channel that ever
                # says *why* a recording failed.  _stderr_reader_worker must
                # drain it or a full pipe buffer will stall ffmpeg.
                stderr=subprocess.PIPE,
                # New process group so the Windows graceful-stop path
                # (CTRL_BREAK_EVENT in _send_graceful_stop) can target ffmpeg.
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == 'win32' else 0
                ),
            )
            self._current_path = output_path
            self._started_at = time.monotonic()
            self._last_error = ''
            # Start the async writer thread.
            self._recording_stopping = False
            self._write_failed = False
            self._failure_reported = False
            self._latest_frame = None
            self._stderr_tail.clear()
            self._frames_written = 0
            self._frames_duplicated = 0
            self._frames_dropped = 0
            # Pace from process spawn rather than from the first frame: the
            # audio input starts recording the moment ffmpeg comes up, so
            # anchoring video to the same instant keeps the two aligned.
            self._pacing_start = time.monotonic()
            self._stderr_thread = threading.Thread(
                target=self._stderr_reader_worker,
                name='uv-rec-stderr',
                daemon=True,
            )
            self._stderr_thread.start()
            self._writer_thread = threading.Thread(
                target=self._frame_writer_worker,
                name='uv-rec-writer',
                daemon=True,
            )
            self._writer_thread.start()
            if self._resolved_audio_input is not None:
                log.info(
                    'Recording audio source: %s (%s)',
                    self._resolved_audio_input[1],
                    self._resolved_audio_input[0],
                )
            log.info('Recording started: %s', output_path)
            return True
        except FileNotFoundError:
            self._last_error = f'ffmpeg not found: {self._ffmpeg_path}'
            self._process = None
            self._current_path = None
            log.error(self._last_error)
            return False
        except Exception as exc:
            self._last_error = f'Recording start failed: {exc}'
            self._process = None
            self._current_path = None
            log.error(self._last_error)
            return self._retry_in_software()

    def _stderr_reader_worker(self) -> None:
        """Daemon thread: drain ffmpeg's stderr so it can never block.

        A piped stderr that nobody reads fills its kernel buffer and wedges
        ffmpeg mid-encode, so this thread is mandatory, not diagnostic
        garnish.  ffmpeg runs at ``-loglevel error``, so anything arriving
        here is a real problem and is logged as such — previously all of it
        went to DEVNULL, which is why a failed recording never explained
        itself.
        """
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in proc.stderr:
                line = raw.decode('utf-8', 'replace').strip()
                if not line:
                    continue
                self._stderr_tail.append(line)
                log.warning('ffmpeg: %s', line)
        except Exception as exc:
            log.debug('Recording stderr reader exited: %s', exc)

    def _retry_in_software(self) -> bool:
        """Fall back to x264 once when a hardware encoder failed to spawn.

        The probe encodes a real frame, so a hardware encoder that gets this
        far usually works -- but a driver can still refuse the actual
        resolution or run out of surfaces.  A recording that silently does
        not happen is the worst outcome, so give up the acceleration rather
        than the recording.  Guarded so the retry cannot recurse.
        """
        global _hw_encoder_cache
        if self._active_codec in ('', 'libx264') or self._retrying_software:
            return False
        log.warning(
            'Recording: %s failed to start; retrying with software x264',
            self._active_codec,
        )
        _hw_encoder_cache = False  # do not re-pick it this session
        self._retrying_software = True
        try:
            return self.start()
        finally:
            self._retrying_software = False

    #: How long ffmpeg may go without touching the output file before it is
    #: considered wedged rather than working.  Finalizing is I/O, not
    #: computation, so a healthy encoder always keeps the file moving.
    _FINALIZE_STALL_TIMEOUT_S = 20.0
    #: Absolute ceiling, however much progress it appears to be making.
    _FINALIZE_MAX_WAIT_S = 600.0

    def _await_finalize(
        self,
        process: subprocess.Popen[bytes],
        output_path: Path | None,
    ) -> int:
        """Wait for ffmpeg to finish writing, escalating only when stuck.

        ``-movflags +faststart`` moves the index to the front of the file,
        which means **rewriting the whole thing** once recording stops.  A
        long set is many gigabytes, so that pass legitimately takes tens of
        seconds -- far longer than the fixed 10s+10s budget this used to
        allow before sending SIGKILL, which would destroy the very file it
        was trying to close.

        So progress is what is measured, not elapsed time: as long as the
        output file keeps changing, ffmpeg is working and is left alone.
        Escalation happens only when it goes quiet.
        """
        deadline = time.monotonic() + self._FINALIZE_MAX_WAIT_S
        last_size = -1
        last_progress = time.monotonic()
        escalated = False
        announced = False

        while True:
            try:
                return_code = process.wait(timeout=0.5)
                if announced:
                    log.info('Recording: finalize complete')
                return return_code
            except subprocess.TimeoutExpired:
                pass

            size = -1
            if output_path is not None:
                try:
                    size = output_path.stat().st_size
                except OSError:
                    size = -1
            now = time.monotonic()
            if size != last_size:
                last_size = size
                last_progress = now
                if not announced and now - (deadline - self._FINALIZE_MAX_WAIT_S) > 2.0:
                    log.info(
                        'Recording: finalizing %s (%.1f GB) — rewriting the index, '
                        'this can take a moment',
                        output_path.name if output_path else '?',
                        max(0, size) / 1073741824.0,
                    )
                    announced = True
                continue

            stalled = now - last_progress
            if stalled >= self._FINALIZE_STALL_TIMEOUT_S and not escalated:
                escalated = True
                last_progress = now
                log.warning(
                    'Recording: no output progress for %.0fs; asking ffmpeg to '
                    'finalize gracefully', stalled,
                )
                _send_graceful_stop(process)
            elif stalled >= self._FINALIZE_STALL_TIMEOUT_S and escalated:
                log.warning(
                    'Recording: ffmpeg wedged with no output progress — killing '
                    '(output may be unplayable)'
                )
                process.kill()
                return process.wait(timeout=5.0)

            if now >= deadline:
                log.warning(
                    'Recording: finalize exceeded %.0fs — killing',
                    self._FINALIZE_MAX_WAIT_S,
                )
                process.kill()
                return process.wait(timeout=5.0)

    def _frame_writer_worker(self) -> None:
        """Daemon thread: pace the latest frame out to ffmpeg at constant rate.

        The output is muxed as **constant** frame rate, so the number of
        frames handed to ffmpeg has to match elapsed wallclock — not the
        number of frames the app happened to render.  The render loop is
        variable-rate by nature (heavy scene, preset compile, 4K mirror), and
        writing one frame per rendered frame while telling ffmpeg the stream
        was 60 fps produced video that played back fast and drifted out of
        sync with the real-time audio track.

        So: each tick, work out how many frames *should* exist by now,
        duplicate the newest frame to fill any gap, and skip ahead rather
        than flood if the deficit is absurd.  Duplicates cost almost nothing
        in the encoded file (empty P-frames) and keep audio aligned.
        """
        interval = 1.0 / float(self._fps)
        last_written: bytes | None = None
        while not self._recording_stopping:
            proc = self._process
            if proc is None or proc.stdin is None:
                break
            if proc.poll() is not None:
                tail = '; '.join(self._stderr_tail) or f'exit code {proc.returncode}'
                self._last_error = f'ffmpeg exited during recording: {tail}'
                self._write_failed = True
                log.error(self._last_error)
                break

            with self._frame_lock:
                frame = self._latest_frame
            if frame is None:
                # No frame has been rendered yet; hold the pacing clock so
                # the first frame back-fills the startup gap and the video
                # timeline still lines up with the audio.
                time.sleep(min(interval, 0.005))
                continue

            now = time.monotonic()
            due = int((now - self._pacing_start) / interval) + 1
            deficit = due - self._frames_written
            if deficit <= 0:
                time.sleep(min(interval, 0.002))
                continue
            if deficit > self._max_catch_up_frames:
                skipped = deficit - self._max_catch_up_frames
                self._frames_written += skipped
                self._frames_dropped += skipped
                deficit = self._max_catch_up_frames
                log.debug('Recording pacing fell %d frames behind; resynced', skipped)

            try:
                for _ in range(deficit):
                    proc.stdin.write(frame)
                    self._frames_written += 1
                    if frame is last_written:
                        self._frames_duplicated += 1
                    last_written = frame
            except (BrokenPipeError, OSError) as exc:
                if not self._recording_stopping:
                    tail = '; '.join(self._stderr_tail)
                    self._last_error = (
                        f'Recording write failed: {exc}'
                        + (f' ({tail})' if tail else '')
                    )
                    self._write_failed = True
                    log.error(self._last_error)
                break
        log.debug(
            'Recording writer thread exited: wrote=%d duplicated=%d skipped=%d',
            self._frames_written,
            self._frames_duplicated,
            self._frames_dropped,
        )

    def write_frame(self, rgb_bytes: bytes) -> bool:
        """Publish a raw RGB frame as the newest available (non-blocking).

        Only the most recent frame matters: the writer thread paces output
        on its own clock, so an extra frame rendered inside one tick would
        be discarded anyway.  Returns False when recording is not active.
        """
        if not self.is_recording or self._recording_stopping:
            return False
        with self._frame_lock:
            self._latest_frame = rgb_bytes
        return True

    def stop(self) -> Path | None:
        """Stop the current recording and return the output path, if any."""
        process = self._process
        output_path = self._current_path
        if process is None:
            return output_path
        log.debug('Stopping recording: %s', output_path)
        try:
            self._recording_stopping = True
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=5.0)
                if self._writer_thread.is_alive():
                    log.warning('Recording writer thread did not exit within 5.0s')
                self._writer_thread = None
            log.info(
                'Recording frames: %d written (%d duplicated to hold %d fps, '
                '%d skipped)',
                self._frames_written,
                self._frames_duplicated,
                self._fps,
                self._frames_dropped,
            )
            self._latest_frame = None
            if process.stdin is not None:
                process.stdin.close()
            return_code = self._await_finalize(process, output_path)
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=2.0)
                self._stderr_thread = None
            if return_code != 0:
                tail = '; '.join(self._stderr_tail)
                self._last_error = (
                    f'Recording exited with code {return_code}'
                    + (f': {tail}' if tail else '')
                )
                log.warning(self._last_error)
            elif output_path is not None:
                log.info('Recording saved: %s', output_path)
        except Exception as exc:
            self._last_error = f'Recording stop failed: {exc}'
            log.warning(self._last_error)
        finally:
            self._process = None
            self._current_path = None
            self._started_at = 0.0
        return output_path