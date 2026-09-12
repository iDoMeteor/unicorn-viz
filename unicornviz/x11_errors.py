"""Keep a benign Xlib protocol error from killing the process.

Why this exists (2026-09-12): switching display mode on the X11 driver under
XWayland exited the app with::

    X Error of failed request:  BadMatch (invalid parameter attributes)
      Major opcode of failed request:  42 (X_SetInputFocus)

SDL's ``X11_SetWindowBordered`` waits until the window is viewable and then
calls ``XSetInputFocus`` on it because it has keyboard focus.  A border change
makes the window manager reparent the window, which unmaps it for a moment,
and when that lands between SDL's check and its focus call the server answers
``BadMatch``.  Xlib's default error handler prints the message above and
calls ``exit(1)``.  The focus request is cosmetic -- the window gets focus
back from the window manager anyway -- so the right response is to ignore
that one error and let everything else behave exactly as before.

:func:`install_focus_error_guard` chains an Xlib error handler in front of
whatever is installed (SDL's own safety-net handler, normally) that swallows
``BadMatch`` on ``X_SetInputFocus`` and forwards every other error untouched.
It is a no-op anywhere libX11 is not present.  Call it once, after SDL has
initialized the x11 video driver, from the main thread.

Usage::

    from unicornviz.x11_errors import install_focus_error_guard
    if sdl2.SDL_GetCurrentVideoDriver() == b'x11':
        install_focus_error_guard()
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from typing import Any

log = logging.getLogger(__name__)

# X11 protocol constants (Xproto.h / X.h).
X_SET_INPUT_FOCUS = 42     # request opcode
BAD_MATCH = 8              # error code


class XErrorEvent(ctypes.Structure):
    """Leading fields of Xlib's ``XErrorEvent`` (the ones a handler reads)."""

    _fields_ = [
        ('type', ctypes.c_int),
        ('display', ctypes.c_void_p),
        ('resourceid', ctypes.c_ulong),
        ('serial', ctypes.c_ulong),
        ('error_code', ctypes.c_ubyte),
        ('request_code', ctypes.c_ubyte),
        ('minor_code', ctypes.c_ubyte),
    ]


# int handler(Display *display, XErrorEvent *event)
XErrorHandlerType = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))

# Module-level references keep the ctypes callback and the previous handler
# alive for the process lifetime; Xlib holds only raw function pointers.
_guard: Any = None
_previous: Any = None


def should_swallow(error_code: int, request_code: int) -> bool:
    """True for the one error the guard absorbs: BadMatch on X_SetInputFocus."""
    return int(error_code) == BAD_MATCH and int(request_code) == X_SET_INPUT_FOCUS


def _handle(display: int, event_ptr: Any) -> int:
    event = event_ptr.contents
    if should_swallow(event.error_code, event.request_code):
        log.debug(
            'Ignored X error BadMatch on X_SetInputFocus (serial=%d resource=0x%x): '
            'the window was reparented between SDL\'s viewable check and its focus call',
            event.serial, event.resourceid,
        )
        return 0
    if _previous:
        return int(_previous(display, event_ptr))
    return 0


def install_focus_error_guard() -> bool:
    """Chain the guard in front of the current Xlib error handler.

    Returns True when installed (or already installed), False when libX11
    could not be loaded.  Safe to call more than once.
    """
    global _guard, _previous
    if _guard is not None:
        return True
    name = ctypes.util.find_library('X11')
    if not name:
        log.debug('x11 focus-error guard: libX11 not found; nothing to do')
        return False
    try:
        lib = ctypes.CDLL(name)
        set_handler = lib.XSetErrorHandler
    except (OSError, AttributeError) as exc:
        log.debug('x11 focus-error guard: XSetErrorHandler unavailable: %s', exc)
        return False
    set_handler.argtypes = [XErrorHandlerType]
    set_handler.restype = XErrorHandlerType
    guard = XErrorHandlerType(_handle)
    previous = set_handler(guard)
    _guard, _previous = guard, previous
    log.info('x11: BadMatch-on-SetInputFocus guard installed (previous handler %s)',
             'chained' if previous else 'none')
    return True
