"""
Unicorn Viz — modern demoscene visualizer.

Package layout
--------------
unicornviz/
    app.py          Main application loop (SDL2 window + moderngl context)
    config.py       TOML config loader with built-in defaults
    hotkeys.py      SDL keyboard and MIDI event → action dispatcher
    midi.py         MIDI device manager (python-rtmidi, optional)
    overlays.py     On-screen HUD: name flash, help panel, message toast
    playlist.py     Effect playlist (sequential / random / pinned sequence)

    effects/        One file per visual effect, all auto-discovered
        base.py         BaseEffect ABC + AudioData dataclass
        registry.py     Discovers every BaseEffect subclass at import time
        ansi_viewer.py  ANSi art viewer with CRT phosphor shader
        audio_spectrum.py  FFT bars + oscilloscope waveform
        copper_bars.py  Amiga copper-bar raster effect
        fire.py         Cellular-automaton fire simulation
        fractal_zoom.py Mandelbrot deep-zoom with smooth colouring
        metaballs.py    GLSL SDF metaball field
        particle_storm.py  100k GPU particles, transform-feedback ping-pong
        plasma.py       Classic sin/cos colour-field plasma
        raymarcher.py   SDF scene raymarcher with fog + specular
        sine_scroller.py  Multi-sine bouncing text scroller
        starfield.py    3-D warp-speed star tunnel
        tunnel.py       Texture-mapped rotating tunnel

    audio/          Audio capture + analysis pipeline
        capture.py      sounddevice PipeWire/ALSA loopback capture
        analyzer.py     FFT + spectral-flux beat detector
        manager.py      Thread-safe bridge between capture and effects

    ansi/           ANSi file support
        loader.py       ANSI escape + CP437 parser; SAUCE record reader
        font.py         CP437 8×16 font atlas builder
        renderer.py     Canvas → RGBA OpenGL texture

Usage
-----
Run from the project root after ``pip install -r requirements.txt``::

    python -m unicornviz          # or:  ./run.sh
"""
