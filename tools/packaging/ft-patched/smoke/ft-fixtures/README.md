# Smoke-test fixtures for the free-threaded OpenCV wheels

(Copied from UnicornViz `tools/packaging/ft-fixtures/`, same owner, MIT; only the script path below was updated.)

Owner: UV Threads
Status: active
Last updated: 2026-10-01

Two tiny clips used by `smoke/ft_opencv_smoke.py` on **every** platform, so
the Windows wheel (whose CI runner has no system `ffmpeg`) is checked decoding the same
codecs `video-clips-01` plays: H.264 in `.mp4` and VP9 in `.webm`.

Each is 20 frames, 160x120, 10 fps, a few KB. The content is a bright 16-pixel bar on a
dark gray background whose left edge sits at x = 7 * N for frame number N, so the bar's
centre (7 * N + 8) identifies the frame. The smoke test decodes in order and also seeks
by frame index, and asserts the bar is where it should be: a decoder that drops,
reorders or mis-seeks frames fails it, and so does a blank frame. (Decoding was checked to
within 0.04 px on every frame and exactly after seeks, with the Linux wheel.)

## How they were generated (system ffmpeg, once)

    SRC="color=c=black:s=160x120:r=10:d=2,format=gray,geq=lum='if(between(X,7*N,7*N+16),255,40)',format=yuv420p"

    ffmpeg -y -f lavfi -i "$SRC" -frames:v 20 -an -map_metadata -1 \
      -fflags +bitexact -flags:v +bitexact \
      -c:v libx264 -preset veryslow -crf 26 -pix_fmt yuv420p -bf 0 -g 5 \
      -movflags +faststart h264.mp4

    ffmpeg -y -f lavfi -i "$SRC" -frames:v 20 -an -map_metadata -1 \
      -fflags +bitexact -flags:v +bitexact \
      -c:v libvpx-vp9 -b:v 0 -crf 38 -pix_fmt yuv420p -g 5 -row-mt 0 -deadline best \
      vp9.webm

`SHA256SUMS` records the files as committed. The clips are test data, not shipped: the
encoders used here are the machine's own, and the wheels under test only ever *decode*
them.
