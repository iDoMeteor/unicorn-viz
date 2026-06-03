from __future__ import annotations

import struct

import pytest

from unicornviz.ansi.loader import ANSIParser


@pytest.fixture
def cp437_sample_bytes() -> bytes:
    # CP437 bytes: 0xB3 (vertical box), 0xDB (full block), plus newline.
    return b'\xb3\xdb\nA'


@pytest.fixture
def sauce_sample_bytes() -> bytes:
    body = b'HELLO\r\n'
    sauce = bytearray(128)
    sauce[0:5] = b'SAUCE'
    sauce[5:7] = b'00'
    sauce[7:42] = b'TESTTITLE'.ljust(35, b' ')
    sauce[42:62] = b'TESTAUTHOR'.ljust(20, b' ')
    sauce[62:82] = b'TESTGROUP'.ljust(20, b' ')
    struct.pack_into('<H', sauce, 96, 80)
    struct.pack_into('<H', sauce, 98, 25)
    return body + b'\x1a' + bytes(sauce)


def test_cp437_bytes_are_preserved(cp437_sample_bytes: bytes) -> None:
    canvas = ANSIParser().parse(cp437_sample_bytes)

    assert canvas.get(0, 0).codepoint == 0xB3
    assert canvas.get(0, 1).codepoint == 0xDB
    # LF moves to next row while preserving column, so 'A' lands at x=2.
    assert canvas.get(1, 2).codepoint == ord('A')


def test_sauce_metadata_is_parsed_and_payload_is_clean(sauce_sample_bytes: bytes) -> None:
    canvas = ANSIParser().parse(sauce_sample_bytes)
    sauce = getattr(canvas, '_sauce', {})

    assert sauce.get('title') == 'TESTTITLE'
    assert sauce.get('author') == 'TESTAUTHOR'
    assert sauce.get('group') == 'TESTGROUP'
    assert sauce.get('width') == 80
    assert sauce.get('height') == 25
    # SAUCE footer should not appear as rendered text content.
    assert canvas.get(0, 0).codepoint == ord('H')
    assert canvas.get(0, 1).codepoint == ord('E')


def test_sub_eof_marker_stops_parsing() -> None:
    data = b'AB\x1aCD'

    canvas = ANSIParser().parse(data)

    assert canvas.get(0, 0).codepoint == ord('A')
    assert canvas.get(0, 1).codepoint == ord('B')
    assert canvas.get(0, 2).codepoint == 32
