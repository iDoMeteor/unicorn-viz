"""unicornviz.audio.pactl: cached, self-refreshing pactl queries.

The audio-source selector, recording start and capture startup each
spawned ``pactl`` on the main thread.  These tests pin the cache: one spawn
per distinct query, answers served from memory within ``max_age_s``, a
missing binary detected once, and the background refresher's contract.
"""
from __future__ import annotations

import subprocess

import pytest

from unicornviz.audio import pactl as pc


class _Proc:
    def __init__(self, out: str) -> None:
        self.stdout = out


def test_second_query_is_served_from_cache(monkeypatch):
    spawns: list[list[str]] = []
    monkeypatch.setattr(pc.subprocess, 'run',
                        lambda cmd, **k: (spawns.append(cmd), _Proc('sink-a\n'))[1])
    cache = pc.PactlCache(auto_refresh=False)
    assert cache.get('list', 'short', 'sinks') == 'sink-a\n'
    assert cache.get('list', 'short', 'sinks') == 'sink-a\n'
    assert spawns == [['pactl', 'list', 'short', 'sinks']]


def test_distinct_queries_are_cached_separately(monkeypatch):
    monkeypatch.setattr(pc.subprocess, 'run',
                        lambda cmd, **k: _Proc(' '.join(cmd[1:])))
    cache = pc.PactlCache(auto_refresh=False)
    assert cache.get('info') == 'info'
    assert cache.get('list', 'sinks') == 'list sinks'


def test_a_caller_can_insist_on_a_fresh_answer(monkeypatch):
    n = 0

    def run(cmd, **k):
        nonlocal n
        n += 1
        return _Proc(f'v{n}')
    monkeypatch.setattr(pc.subprocess, 'run', run)
    cache = pc.PactlCache(auto_refresh=False)
    assert cache.get('info') == 'v1'
    assert cache.get('info', max_age_s=0.0) == 'v2'


def test_missing_binary_is_detected_once(monkeypatch):
    spawns = 0

    def run(cmd, **k):
        nonlocal spawns
        spawns += 1
        raise FileNotFoundError('pactl')
    monkeypatch.setattr(pc.subprocess, 'run', run)
    cache = pc.PactlCache(auto_refresh=False)
    assert cache.get('info') is None
    assert cache.get('info') is None
    assert cache.get('list', 'sinks') is None
    assert spawns == 1 and cache.available is False


def test_a_failed_query_caches_none_but_stays_available(monkeypatch):
    def run(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 5.0)
    monkeypatch.setattr(pc.subprocess, 'run', run)
    cache = pc.PactlCache(auto_refresh=False)
    assert cache.get('info') is None
    assert cache.available is True


def test_refresher_reruns_known_queries_and_stops_cleanly(monkeypatch):
    n = 0

    def run(cmd, **k):
        nonlocal n
        n += 1
        return _Proc(f'v{n}')
    monkeypatch.setattr(pc.subprocess, 'run', run)
    monkeypatch.setattr(pc, 'REFRESH_S', 0.05)
    cache = pc.PactlCache(auto_refresh=True)
    assert cache.get('info') == 'v1'
    import time
    time.sleep(0.2)
    cache.stop()
    assert n >= 2                                    # refreshed in the background
    assert cache.get('info') != 'v1'                 # newer answer served, no spawn needed
    assert cache._thread is None
