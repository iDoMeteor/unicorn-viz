# ANSi Art — Sources and Credits

Owner: core manager
Status: Maintained
Last updated: 2026-08-08

This directory holds the CP437 ANSi art the viewer renders. It contains two
kinds of files with different origins and different rights, and the difference
matters.

## `acid/` — ACiD Productions artpacks (third-party, credited below)

The eighteen `.ANS` files in `acid/` are real artscene releases by ACiD
Productions, downloaded from the [16colo.rs](https://16colo.rs) archive by
`tools/fetch_acid_ans.py` and committed here so the viewer has authentic art
out of the box.

**Copyright in these works remains with the individual artists credited
below.** They are not covered by this project's MIT license, and unicorn-viz
claims no rights in them. They are included under the artscene's long-standing
convention of free circulation — packs were released publicly for exactly this
kind of display, and 16colo.rs exists to archive and distribute them — but a
convention is not a license grant, and this file exists so the credit travels
with the art.

Every file carries a SAUCE record naming its author; the table below is
generated from those records, and the viewer parses the same data at load time.

| File | Title | Artist | Group | Released |
| --- | --- | --- | --- | --- |
| `acid-50a_ANS-50A.ANS` | ACiD ANSI logocluster #16 | Multiple Artists | ACiD Productions | 1996-09-01 |
| `acid-50a_GS-SHAD1.ANS` | Shades of a Shade | Ghengis | ACiD Productions | 1996-09-01 |
| `acid-50a_KM-FIFTY.ANS` | Fifty to Infinity | King Midas | ACiD Productions | 1996-09-01 |
| `acid-50a_NI-SKULL.ANS` | Skull Duggery | Nitnatsnoc | ACiD Productions | 1996-09-01 |
| `acid-50a_PH-MOOSE.ANS` | Moose City | Pharcyde | ACiD Productions | 1996-09-01 |
| `acid-50a_RA-FIFTY.ANS` | ACiD 50 Advo | Reanimator | ACiD Productions | 1996-09-01 |
| `acid-50a_SE-JELLO.ANS` | Jellomite | Sensei | ACiD Productions | 1996-09-01 |
| `acid-50a_SE-LIME.ANS` | Lime | Sensei | ACiD Productions | 1996-09-01 |
| `acid-56_GS-ACID.ANS` | Ghengis' Final ANSI | Ghengis | ACiD Productions | 1997-04-01 |
| `acid-56_KT-ABRAX.ANS` | Abraxas | Kitiara | ACiD Productions | 1997-04-01 |
| `acid-56_MD-SKULL.ANS` | Mixing Atoms With Angles | Mr. Self Destruct | ACiD Productions | 1997-04-01 |
| `acid-56_NEWS-56.ANS` | ACiD Newsletter Issue #15 | acid!press | ACiD Productions | 1997-04-05 |
| `acid-100_ANSC-100.ANS` | ACiD-100 Newschool ANSCII Cluster | Multiple Artists | ACiD Productions | 2003-12-31 |
| `acid-100_ANSI-100.ANS` | ACiD-100 ANSI Cluster | Multiple Artists | ACiD Productions | 2003-12-31 |
| `acid-100_DA-ANIME.ANS` | Anime Remix | Devil Angel | ACiD Productions | 2003-12-31 |
| `acid-100_GO-EAST.ANS` | East 1999 | Guile and Offset | ACiD Productions | 2003-12-31 |
| `acid-100_MAY-ACID.ANS` | ACiD 100 | Maytag | ACiD Productions | 2003-12-31 |
| `acid-100_OS-HAZ01.ANS` | Hazard 2.0 | Offset | ACiD Productions | 2003-12-31 |

Source packs: [acid-50a](https://16colo.rs/pack/acid-50a) (1996),
[acid-56](https://16colo.rs/pack/acid-56) (1997),
[acid-100](https://16colo.rs/pack/acid-100) (2003).

The three logocluster / newsletter files credited to "Multiple Artists" are
collaborative pieces whose individual contributors are named inside the art
itself rather than in the SAUCE record.

**If you are one of these artists and would prefer your work not ship with this
project, open an issue and it will be removed from the next release.**

Re-fetch or extend the set with `python tools/fetch_acid_ans.py`. If you add
files, regenerate the table above from their SAUCE records rather than typing
credits by hand — the record is the authority on who made the piece.

## Root of this directory — original project art

`acid_logo.ans`, `colour_test.ans`, `fire_scene.ans`, `future_crew.ans`,
`plasma_test.ans`, `razor_bbs.ans` and `unicorn_viz_title.ans` are original
work generated for this project by `tools/generate_ansi_art.py`. They are
covered by the project's MIT license like any other source file.

Their titles nod to demoscene and BBS history (Future Crew, Razor 1911, ACiD);
the names are homage, not claims of affiliation, and no third-party art was
copied to make them.

## Related

- Full licensing review, including the CP437 font assets in `assets/fonts/`:
  [`docs/audits/2026-08-08-licensing-audit.md`](../../docs/audits/2026-08-08-licensing-audit.md)
