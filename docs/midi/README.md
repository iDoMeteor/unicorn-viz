# DDJ-REV1 MIDI reference

Owner: dj-mixer-01 · Status: reference · Last updated: 2026-07-13

The authoritative Pioneer **"DDJ-REV1 List of MIDI Messages"** PDF is committed
here as [`ddj-rev1_midi_message_list.pdf`](ddj-rev1_midi_message_list.pdf)
(retrieved via the Wayback Machine — the live pioneerdj.com CDN blocks direct
download).

- Live URL (browser only, CDN-gated): `https://www.pioneerdj.com/-/media/pioneerdj/software-info/controller/ddj-rev1/ddj-rev1_midi_message_list_j1.pdf`
- Archived copy: `http://web.archive.org/web/20250918025219id_/https://www.pioneerdj.com/-/media/pioneerdj/software-info/controller/ddj-rev1/ddj-rev1_midi_message_list_j1.pdf`

This supersedes the transcribed subset in `docs/planning/dj-mixer-drop-in-plan.md`
(Appendix A) — where they differ, the PDF wins.

## Channels (status nibble, 0-indexed = value − 1)

| Section | MIDI ch (1-idx) | 0-idx |
|---|---|---|
| Deck 1 / 2 / 3 / 4 (non-pad) | 1 / 2 / 3 / 4 | 0 / 1 / 2 / 3 |
| Deck 1–4 performance pads | 8 / 10 / 12 / 14 | 7 / 9 / 11 / 13 |
| Deck 1–4 pads **+SHIFT** | 9 / 11 / 13 / 15 | 8 / 10 / 12 / 14 |
| Mixer / master / browser | 7 | 6 |
| FX1 / FX2 | 5 / 6 | 4 / 5 |

## Performance-pad mode note bases

Pad *i* (1–8) = **base + (i−1)**, sent on the deck's pad channel. `+SHIFT` sends
the same note on the shift channel. Velocity `0x7F` press / `0x00` release.

| Pad mode | Base note (dec) | Hex | Notes (pads 1–8) |
|---|---|---|---|
| Hot Cue | 0 | 0x00 | 0–7 |
| Auto Loop | 16 | 0x10 | 16–23 |
| Tracking Scratch (track-nav) | 32 | 0x20 | 32–39 |
| Sampler | 48 | 0x30 | 48–55 |
| Beat Jump | 64 | 0x40 | 64–71 |
| Roll | 80 | 0x50 | 80–87 |
| Trans (transform) | 96 | 0x60 | 96–103 |
| Scratch Bank | 112 | 0x70 | 112–119 |

## Deck select (upper-corner buttons)

`DECK SELECT` sends **Note 60 (0x3C)** on the *target* deck's channel:
`0x7F` = that deck ON for its side, `0x00` = OFF. Left side toggles decks 1↔3,
right side toggles 2↔4. (Long-press = Note 96 on the deck channel.)

These bases are encoded in `drop-ins/dj-mixer-01/rev1_map.py`
(`PAD_MODE_BASES`) and dispatched in `rev1_input.py`.
