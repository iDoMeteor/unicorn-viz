"""Recording — constant-rate pacing, audio-source resolution, liveness.

These cover the three faults that made recordings unusable in practice:

* video muxed as CFR while frames arrived at the (variable) render rate, so
  playback ran fast and drifted away from the real-time audio track;
* the audio source resolved to the *default* sink's monitor, which is silent
  whenever the set plays through anything else (a DJ controller, say);
* ffmpeg dying without the app noticing, leaving REC lit over a dead encoder.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from unicornviz.config import Config
from unicornviz.recording import Recorder


def _cfg() -> Config:
    return Config(Path('tests') / '_missing_config_for_tests.toml')


def _recorder(**over) -> Recorder:
    rec = Recorder(_cfg(), 64, 48)
    for key, value in over.items():
        setattr(rec, f'_{key}', value)
    return rec


class _Stdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        pass


class _Proc:
    def __init__(self, alive: bool = True) -> None:
        self.stdin = _Stdin()
        self.returncode = None if alive else 1

    def poll(self):
        return self.returncode


# --------------------------------------------------------------------------
# Pacing
# --------------------------------------------------------------------------

def test_writer_duplicates_frames_to_hold_constant_rate() -> None:
    """A render loop slower than the target rate must not shorten the file.

    Frames handed to ffmpeg have to track wallclock, not render count, or a
    CFR mux replays the show faster than it happened.  Here exactly one
    frame is ever published, and the writer is expected to keep emitting it
    so the timeline stays real-time.
    """
    rec = _recorder(fps=50)
    proc = _Proc()
    rec._process = proc
    rec._latest_frame = b'frame'
    rec._max_catch_up_frames = 50

    started = time.monotonic()
    rec._pacing_start = started
    thread = threading.Thread(target=rec._frame_writer_worker, daemon=True)
    thread.start()
    time.sleep(0.4)
    rec._recording_stopping = True
    thread.join(timeout=2.0)
    elapsed = time.monotonic() - started

    expected = elapsed * 50
    written = len(proc.stdin.writes)
    # Generous band: this asserts the writer paces on wallclock at all, not
    # that a test machine can hit a scheduler deadline exactly.
    assert 0.5 * expected <= written <= 1.5 * expected + 2, (
        f'wrote {written} frames in {elapsed:.2f}s, expected ~{expected:.0f}'
    )
    # Only one distinct frame was ever published, so the rest are duplicates.
    assert rec._frames_duplicated > 0
    assert all(w == b'frame' for w in proc.stdin.writes)


def test_writer_stops_and_reports_when_ffmpeg_dies() -> None:
    """A dead encoder must latch a failure the app can surface, not spin."""
    rec = _recorder(fps=50)
    rec._process = _Proc(alive=False)
    rec._latest_frame = b'frame'
    rec._stderr_tail.append('Invalid argument')

    thread = threading.Thread(target=rec._frame_writer_worker, daemon=True)
    thread.start()
    thread.join(timeout=2.0)

    assert thread.is_alive() is False
    assert rec.has_failed is True
    assert 'Invalid argument' in rec.last_error
    assert rec.consume_failure() is not None
    assert rec.consume_failure() is None


def test_write_frame_keeps_only_the_newest_frame() -> None:
    """The render thread must never block or queue behind the encoder."""
    rec = _recorder()
    rec._process = _Proc()
    assert rec.write_frame(b'old') is True
    assert rec.write_frame(b'new') is True
    assert rec._latest_frame == b'new'


def test_write_frame_rejected_when_not_recording() -> None:
    rec = _recorder()
    assert rec.write_frame(b'x') is False


def test_target_fps_drives_the_frame_tap_cap() -> None:
    """The app caps readback at this rate; frames above it are discarded."""
    rec = _recorder(fps=24)
    assert rec.target_fps == 24


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------

def test_dead_ffmpeg_is_not_reported_as_recording() -> None:
    """A REC indicator over an exited encoder is a lie that costs a whole set."""
    rec = _recorder()
    rec._process = _Proc(alive=False)
    assert rec.is_recording is False


def test_live_ffmpeg_is_reported_as_recording() -> None:
    rec = _recorder()
    rec._process = _Proc(alive=True)
    assert rec.is_recording is True


# --------------------------------------------------------------------------
# Audio source resolution
# --------------------------------------------------------------------------

def test_explicit_device_wins_over_detection(monkeypatch) -> None:
    rec = _recorder(audio_input_device='my.explicit.source')
    monkeypatch.setattr(rec, '_pactl', lambda *a: (_ for _ in ()).throw(
        AssertionError('pactl must not be consulted when pinned')))
    assert rec._resolve_pulse_source() == 'my.explicit.source'


def test_visualizer_source_hint_selects_that_sinks_monitor(monkeypatch) -> None:
    """The audio driving the visuals is the audio the recording should carry.

    Regression for silent recordings: the DJ controller is not the default
    sink, so default-sink detection captured an idle output.
    """
    rec = _recorder()
    rec.set_audio_source_hint('DDJ-REV1 Analog Surround 4.0')

    def fake_pactl(*args):
        if args[:2] == ('list', 'sinks'):
            return (
                'Sink #1\n'
                '\tName: alsa_output.pci-0000_00_1f.3.analog-stereo\n'
                '\tDescription: Built-in Audio Analog Stereo\n'
                'Sink #2\n'
                '\tName: alsa_output.usb-DDJ-REV1.analog-surround-40\n'
                '\tDescription: DDJ-REV1 Analog Surround 4.0\n'
            )
        return ''

    monkeypatch.setattr(rec, '_pactl', fake_pactl)
    assert rec._resolve_pulse_source() == (
        'alsa_output.usb-DDJ-REV1.analog-surround-40.monitor'
    )


def test_falls_back_to_a_running_sink_when_hint_is_unknown(monkeypatch) -> None:
    rec = _recorder()
    rec.set_audio_source_hint('Some Unrelated Device')

    def fake_pactl(*args):
        if args == ('list', 'short', 'sinks'):
            return (
                '1\talsa_output.builtin\tPipeWire\ts32le\tSUSPENDED\n'
                '2\talsa_output.controller\tPipeWire\ts24le\tRUNNING\n'
            )
        if args == ('info',):
            return 'Default Sink: alsa_output.builtin\n'
        return ''

    monkeypatch.setattr(rec, '_pactl', fake_pactl)
    assert rec._resolve_pulse_source() == 'alsa_output.controller.monitor'


def test_idle_system_falls_back_to_default_sink_monitor(monkeypatch) -> None:
    rec = _recorder()

    def fake_pactl(*args):
        if args == ('list', 'short', 'sinks'):
            return '1\talsa_output.builtin\tPipeWire\ts32le\tSUSPENDED\n'
        if args == ('info',):
            return 'Default Sink: alsa_output.builtin\n'
        return ''

    monkeypatch.setattr(rec, '_pactl', fake_pactl)
    assert rec._resolve_pulse_source() == 'alsa_output.builtin.monitor'


def test_no_pactl_degrades_to_default_source(monkeypatch) -> None:
    rec = _recorder()
    monkeypatch.setattr(rec, '_pactl', lambda *a: None)
    assert rec._resolve_pulse_source() == 'default'


def test_available_audio_sources_lists_monitors(monkeypatch) -> None:
    rec = _recorder()
    monkeypatch.setattr(rec, '_pactl', lambda *a: (
        '\tName: sink.one\n\tDescription: One\n'
        '\tName: sink.two\n\tDescription: Two\n'
    ))
    assert rec.available_audio_sources() == [
        ('sink.one.monitor', 'One'),
        ('sink.two.monitor', 'Two'),
    ]


# --------------------------------------------------------------------------
# ffmpeg command construction
# --------------------------------------------------------------------------

def test_command_maps_streams_explicitly_and_queues_audio(monkeypatch) -> None:
    rec = _recorder(capture_audio=True)
    monkeypatch.setattr(rec, '_resolve_audio_input', lambda: ('pulse', 'src.monitor'))
    cmd = rec._build_command(Path('/tmp/out.mp4'))
    assert '-map' in cmd
    assert cmd[cmd.index('-map') + 1] == '0:v:0'
    assert '1:a:0' in cmd
    # A live capture that cannot be back-pressured needs a deep input queue.
    assert '-thread_queue_size' in cmd
    # Declared input rate must match what the pacing writer actually emits.
    assert cmd[cmd.index('-framerate') + 1] == str(rec.target_fps)


def test_command_without_audio_disables_the_track(monkeypatch) -> None:
    rec = _recorder(capture_audio=False)
    cmd = rec._build_command(Path('/tmp/out.mp4'))
    assert '-an' in cmd
    assert '1:a:0' not in cmd


# --------------------------------------------------------------------------
# Config-editor tweakables
# --------------------------------------------------------------------------

def test_apply_setting_clamps_to_declared_range() -> None:
    rec = _recorder()
    rec.apply_setting('fps', 9999.0)
    assert rec.target_fps == 120
    rec.apply_setting('fps', 0.0)
    assert rec.target_fps == 15
    # The catch-up ceiling tracks the frame rate it is expressed in.
    assert rec._max_catch_up_frames == 15


def test_apply_setting_ignores_unknown_keys() -> None:
    rec = _recorder()
    rec.apply_setting('not_a_setting', 1.0)  # must not raise


def test_pinning_and_clearing_the_audio_source() -> None:
    rec = _recorder()
    rec.set_pulse_source_name('pinned.monitor')
    assert rec._audio_input_device == 'pinned.monitor'
    rec.set_pulse_source_name('')
    assert rec._audio_input_device == ''


# --------------------------------------------------------------------------
# Encoder selection
# --------------------------------------------------------------------------

def test_explicit_codec_is_never_overridden(monkeypatch) -> None:
    """A pinned codec must not be silently swapped for hardware."""
    import unicornviz.recording as rec_mod
    monkeypatch.setattr(rec_mod, '_probe_hw_encoder',
                        lambda _p: ('h264_vaapi', [], 'x', '-qp'))
    rec = _recorder(codec='libx264')
    assert rec._resolve_encoder()[0] == 'libx264'


def test_auto_uses_hardware_when_the_probe_succeeds(monkeypatch) -> None:
    import unicornviz.recording as rec_mod
    monkeypatch.setattr(
        rec_mod, '_probe_hw_encoder',
        lambda _p: ('h264_vaapi', ['-vaapi_device', '/dev/dri/renderD128'],
                    'format=nv12,hwupload', '-qp'))
    rec = _recorder(codec='auto', capture_audio=False)
    cmd = rec._build_command(Path('/tmp/o.mp4'))
    assert '-c:v' in cmd and cmd[cmd.index('-c:v') + 1] == 'h264_vaapi'
    # VA-API opens its device before any input.
    assert cmd.index('-vaapi_device') < cmd.index('-i')
    # Frames must be uploaded to the GPU after the flip.
    assert 'vflip,format=nv12,hwupload' in cmd
    # -crf and -preset are x264 concepts the hardware encoders reject.
    assert '-crf' not in cmd
    assert '-preset' not in cmd
    assert '-qp' in cmd


def test_auto_falls_back_to_software_when_no_hardware(monkeypatch) -> None:
    """The normal outcome on a stock Fedora box, and it must still record."""
    import unicornviz.recording as rec_mod
    monkeypatch.setattr(rec_mod, '_probe_hw_encoder', lambda _p: None)
    rec = _recorder(codec='auto', capture_audio=False)
    cmd = rec._build_command(Path('/tmp/o.mp4'))
    assert cmd[cmd.index('-c:v') + 1] == 'libx264'
    assert '-crf' in cmd
    assert '-preset' in cmd
    assert '-pix_fmt' in cmd


def test_software_retry_does_not_recurse() -> None:
    rec = _recorder(codec='auto')
    rec._active_codec = 'libx264'
    assert rec._retry_in_software() is False


# --------------------------------------------------------------------------
# Finalize: never kill an encoder that is still writing
# --------------------------------------------------------------------------

class _FinalizingProc:
    """ffmpeg rewriting its output, as +faststart does on a large file."""

    def __init__(self, ticks_to_finish: int, growing: bool = True) -> None:
        self._left = ticks_to_finish
        self._growing = growing
        self.size = 0
        self.signals: list[object] = []
        self.killed = False

    def wait(self, timeout=None):
        if self._left <= 0:
            return 0
        self._left -= 1
        if self._growing:
            self.size += 1_000_000
        # Advance real time, since the caller measures progress against the
        # clock rather than against poll count.
        time.sleep(0.01)
        raise __import__('subprocess').TimeoutExpired('ffmpeg', timeout)

    def send_signal(self, sig) -> None:
        self.signals.append(sig)

    def kill(self) -> None:
        self.killed = True
        self._left = 0


class _OutFile:
    """Stands in for the output path; reports the encoder's current size."""

    name = 'out.mp4'

    def __init__(self, proc) -> None:
        self._proc = proc

    def stat(self):
        class _S:
            st_size = self._proc.size
        _S.st_size = self._proc.size
        return _S


def _finalize(rec, proc, tmp_path):
    """Run _await_finalize against a stand-in output file."""
    del tmp_path
    return rec._await_finalize(proc, _OutFile(proc))


def test_finalize_waits_while_the_file_is_still_growing(tmp_path) -> None:
    """A multi-GB +faststart rewrite must not be guillotined mid-write.

    The old fixed 10s+10s budget sent SIGKILL to a perfectly healthy
    encoder, destroying the file it was closing.
    """
    rec = _recorder()
    proc = _FinalizingProc(ticks_to_finish=60, growing=True)
    assert _finalize(rec, proc, tmp_path) == 0
    assert proc.killed is False
    assert proc.signals == [], 'a working encoder must not be signalled'


def test_finalize_escalates_when_output_stops_moving(tmp_path) -> None:
    """Stalled is different from slow, and only stalled deserves a signal."""
    rec = _recorder()
    rec._FINALIZE_STALL_TIMEOUT_S = 0.05
    proc = _FinalizingProc(ticks_to_finish=10_000_000, growing=False)
    rec._FINALIZE_MAX_WAIT_S = 2.0
    _finalize(rec, proc, tmp_path)
    assert proc.signals, 'a wedged encoder should be asked to stop first'
    assert proc.killed is True
