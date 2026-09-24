"""unicornviz.workers: batch jobs from path-loaded modules in worker processes."""
from __future__ import annotations

import os
from pathlib import Path

from unicornviz import workers

_JOB = str(Path(__file__).resolve().parent / 'fixtures' / 'worker_job.py')


def test_jobs_run_in_another_process_at_lower_priority() -> None:
    pool = workers.WorkerPool(1, name='test')
    try:
        pid, nice, loads = pool.submit(_JOB, 'whoami').result(timeout=60)
        assert pid != os.getpid()
        assert nice >= os.nice(0) + workers.WORKER_NICENESS or nice == 19
        assert pool.submit(_JOB, 'add', 2, 3).result(timeout=60) == 5
        _, _, loads_again = pool.submit(_JOB, 'whoami').result(timeout=60)
        assert loads_again == loads == 1              # module loaded once
    finally:
        pool.shutdown()


def test_default_workers_is_capped_and_overridable(monkeypatch) -> None:
    monkeypatch.delenv('UNICORNVIZ_WORKERS', raising=False)
    assert 1 <= workers.default_workers() <= 4
    monkeypatch.setenv('UNICORNVIZ_WORKERS', '0')
    assert workers.default_workers() == 0
    monkeypatch.setenv('UNICORNVIZ_WORKERS', '7')
    assert workers.default_workers() == 7
