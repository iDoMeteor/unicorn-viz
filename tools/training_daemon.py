"""Unicorn Viz background training daemon.

Sets up an isolated audio + display environment (PipeWire null sink + Xvfb),
launches the Spotify desktop app and unicorn-viz headlessly, then
auto-packages the session corpus when unicorn-viz exits.  Run from the *main*
repo root; point --app-dir at the separate training deploy of unicorn-viz.

Usage::

    python tools/training_daemon.py \\
        --playlist-name "45 minute chillstep mix" \\
        --app-dir /path/to/unicorn-viz-training

Prerequisites:
  * Xvfb    — sudo dnf install xorg-x11-server-Xvfb
  * Spotify  — snap (already installed) or flatpak; must be logged in
  * pactl    — ships with PipeWire on Fedora/Arch

What the daemon does:
  1. Creates a PipeWire null sink (``unicorn-training`` by default).
  2. Starts Xvfb on DISPLAY :99.
  3. Launches the Spotify desktop app headlessly, routing audio to the null sink.
     Spotify still appears as a Connect device — control it from your phone or
     any other Spotify client.  Crossfade and auto-mix work as configured in
     your Spotify account settings.
  4. Launches unicorn-viz from ``--app-dir`` with Mesa software rendering,
     capturing audio from the null sink monitor via ``--audio-device``.
  5. After unicorn-viz exits, runs ``package_training_set.py`` to archive the
     session corpus into the next available bucket.
  6. Cleans up Xvfb, Spotify, and the null sink on exit.

Note: Spotify must be logged in before running the daemon headlessly.  If this
is the first run on the machine, launch Spotify normally once, log in, then
close it before starting the daemon.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

_LOG = logging.getLogger('training_daemon')

# Path to package_training_set.py relative to this script.
_PACKAGER = Path(__file__).resolve().parent / 'package_training_set.py'

# How long to wait for Xvfb display to become available.
_XVFB_READY_TIMEOUT_S = 10.0

# How long to let Spotify initialise and establish a Connect session before
# launching unicorn-viz.  Spotify is an Electron app and takes a few seconds.
_SPOTIFY_WARMUP_S = 8.0


# ---------------------------------------------------------------------------
# Cleanup registry
# ---------------------------------------------------------------------------

_cleanup_fns: list = []


def _run_cleanup() -> None:
    for fn in reversed(_cleanup_fns):
        try:
            fn()
        except Exception as exc:
            _LOG.warning('cleanup error: %s', exc)


atexit.register(_run_cleanup)


def _on_signal(signum, _frame) -> None:
    _LOG.info('received signal %s, shutting down', signum)
    sys.exit(0)


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(cmd: str) -> str:
    """Return full path to *cmd* or abort with a clear error."""
    path = shutil.which(cmd)
    if path is None:
        sys.exit(f'ERROR: {cmd!r} not found in PATH.')
    return path


def _slugify(text: str) -> str:
    """Convert playlist name to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')
    return slug or 'untitled'


def _set_name(playlist_name: str) -> str:
    today = date.today().strftime('%Y%m%d')
    return f'{today}-{_slugify(playlist_name)}'


def _start(args: list[str], *, env: dict | None = None, cwd: str | Path | None = None) -> subprocess.Popen:
    """Start a subprocess without inheriting our terminal signal group."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    _LOG.info('starting: %s', shlex.join(args))
    return subprocess.Popen(
        args,
        env=merged_env,
        cwd=str(cwd) if cwd else None,
        start_new_session=True,
    )


def _kill_proc(proc: subprocess.Popen | None, name: str, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    _LOG.info('terminating %s (pid %s)', name, proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _LOG.warning('%s did not terminate; killing', name)
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# Null sink
# ---------------------------------------------------------------------------

def _create_null_sink(sink_name: str) -> int:
    """Load a PipeWire/PulseAudio null sink; return module index for cleanup."""
    result = subprocess.run(
        ['pactl', 'load-module', 'module-null-sink',
         f'sink_name={sink_name}',
         f'sink_properties=device.description="Unicorn Training ({sink_name})"'],
        capture_output=True, text=True, check=True,
    )
    module_id = int(result.stdout.strip())
    _LOG.info('null sink %r loaded as module %d', sink_name, module_id)
    return module_id


def _unload_null_sink(module_id: int) -> None:
    try:
        subprocess.run(['pactl', 'unload-module', str(module_id)], check=True)
        _LOG.info('null sink module %d unloaded', module_id)
    except subprocess.CalledProcessError as exc:
        _LOG.warning('failed to unload sink module %d: %s', module_id, exc)


# ---------------------------------------------------------------------------
# Xvfb
# ---------------------------------------------------------------------------

def _start_xvfb(display: str) -> subprocess.Popen:
    xvfb_bin = _require('Xvfb')
    proc = _start([xvfb_bin, display, '-screen', '0', '1920x1080x24', '-nolisten', 'tcp'])
    return proc


def _wait_xvfb(display: str, timeout: float = _XVFB_READY_TIMEOUT_S) -> None:
    """Poll until the Xvfb display socket appears."""
    xdpyinfo = shutil.which('xdpyinfo')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if xdpyinfo:
            result = subprocess.run(
                [xdpyinfo, '-display', display],
                capture_output=True,
            )
            if result.returncode == 0:
                _LOG.info('Xvfb on %s is ready', display)
                return
        else:
            num = display.lstrip(':')
            if Path(f'/tmp/.X{num}-lock').exists():
                time.sleep(0.5)
                _LOG.info('Xvfb on %s lock file present', display)
                return
        time.sleep(0.25)
    _LOG.warning('Xvfb on %s may not be ready after %.1fs — continuing anyway', display, timeout)


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

def _start_spotify(display: str, sink_name: str) -> subprocess.Popen:
    """Launch the Spotify desktop app headlessly under *display*.

    Passes ``--no-zygote --disable-gpu`` to suppress GPU/sandbox noise that
    is harmless under a virtual framebuffer.  Audio is routed to *sink_name*
    via ``PULSE_SINK``, which libpulse (inside the Electron app) respects
    through PipeWire's PulseAudio compat layer.
    """
    spotify_bin = _require('spotify')
    return _start(
        [spotify_bin, '--no-zygote', '--disable-gpu'],
        env={
            'DISPLAY': display,
            'PULSE_SINK': sink_name,
        },
    )


# ---------------------------------------------------------------------------
# unicorn-viz
# ---------------------------------------------------------------------------

def _start_unicornviz(
    app_dir: Path,
    display: str,
    sink_name: str,
    windowed: bool,
) -> subprocess.Popen:
    python_bin = _require('python3')
    cmd = [python_bin, '-m', 'unicornviz', '--audio-device', sink_name]
    cmd.append('--windowed' if windowed else '--fullscreen')
    return _start(
        cmd,
        cwd=app_dir,
        env={
            'DISPLAY': display,
            # Mesa software renderer — no GPU required inside Xvfb.
            'LIBGL_ALWAYS_SOFTWARE': '1',
            'GALLIUM_DRIVER': 'llvmpipe',
        },
    )


# ---------------------------------------------------------------------------
# Packager
# ---------------------------------------------------------------------------

def _run_packager(app_dir: Path, set_name: str, session_notes: str) -> int:
    python_bin = _require('python3')
    # Run the packager from the training deploy so it picks up corpus files
    # under app_dir/assets/training/.
    packager_in_deploy = app_dir / 'tools' / 'package_training_set.py'
    if not packager_in_deploy.exists():
        _LOG.warning('packager not found at %s; falling back to %s', packager_in_deploy, _PACKAGER)
        packager_in_deploy = _PACKAGER

    cmd = [python_bin, str(packager_in_deploy), '--no-prompt', '--set-name', set_name]
    if session_notes:
        cmd += ['--session-notes', session_notes]

    _LOG.info('running packager: %s', shlex.join(cmd))
    return subprocess.run(cmd, cwd=str(app_dir)).returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Headless background training daemon for Unicorn Viz Auto VJ.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--playlist-name', required=True, metavar='TEXT',
        help='Spotify playlist name — used to build the set directory name.',
    )
    parser.add_argument(
        '--app-dir', required=True, type=Path, metavar='PATH',
        help='Path to the unicorn-viz training deploy (separate from this dev repo).',
    )
    parser.add_argument(
        '--display', default=':99',
        help='Xvfb virtual display number.',
    )
    parser.add_argument(
        '--sink-name', default='unicorn-training',
        help='PipeWire null sink name for audio isolation.',
    )
    parser.add_argument(
        '--session-notes', default='', metavar='TEXT',
        help='Notes to record in the session log (passed to the packager).',
    )
    parser.add_argument(
        '--windowed', action='store_true',
        help='Run unicorn-viz in a window instead of fullscreen.',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Set up infrastructure (sink, Xvfb, Spotify) but skip unicorn-viz and packager.',
    )
    parser.add_argument(
        '--spotify-warmup', type=float, default=_SPOTIFY_WARMUP_S, metavar='SECONDS',
        help='Seconds to wait for Spotify to start before launching unicorn-viz.',
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    args = _parse_args()

    app_dir = args.app_dir.resolve()
    if not app_dir.is_dir():
        sys.exit(f'ERROR: --app-dir does not exist: {app_dir}')

    set_name = _set_name(args.playlist_name)
    _LOG.info('set name: %s', set_name)
    _LOG.info('app dir:  %s', app_dir)

    # ---- null sink ----------------------------------------------------------
    try:
        module_id = _create_null_sink(args.sink_name)
    except subprocess.CalledProcessError as exc:
        sys.exit(f'ERROR: could not create null sink: {exc.stderr}')
    _cleanup_fns.append(lambda mid=module_id: _unload_null_sink(mid))

    # ---- Xvfb ---------------------------------------------------------------
    xvfb_proc = _start_xvfb(args.display)
    _cleanup_fns.append(lambda p=xvfb_proc: _kill_proc(p, 'Xvfb'))
    _wait_xvfb(args.display)

    # ---- Spotify ------------------------------------------------------------
    spotify_proc = _start_spotify(args.display, args.sink_name)
    _cleanup_fns.append(lambda p=spotify_proc: _kill_proc(p, 'Spotify'))

    print(f'\nSpotify started.  Select this machine as your Spotify Connect device, ')
    print(f'start your playlist with crossfade enabled, then come back here.')
    print(f'Waiting {args.spotify_warmup:.0f}s for Spotify to initialise…')
    time.sleep(args.spotify_warmup)

    if args.dry_run:
        print('\n--dry-run: infrastructure is running.  Press Ctrl+C to tear down.')
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        return 0

    # ---- unicorn-viz --------------------------------------------------------
    print(f'\nLaunching unicorn-viz (set: {set_name}) …')
    uviz_proc = _start_unicornviz(app_dir, args.display, args.sink_name, args.windowed)
    _cleanup_fns.append(lambda p=uviz_proc: _kill_proc(p, 'unicorn-viz'))

    try:
        uviz_proc.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _LOG.info('unicorn-viz exited (code %s)', uviz_proc.poll())

    # ---- package session ----------------------------------------------------
    print('\nPackaging session corpus…')
    pack_rc = _run_packager(app_dir, set_name, args.session_notes)
    if pack_rc != 0:
        _LOG.warning('packager exited with code %d', pack_rc)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
