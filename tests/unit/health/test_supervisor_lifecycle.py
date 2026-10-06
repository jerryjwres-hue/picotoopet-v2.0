from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from picotoopet_core import cli


class _Report:
    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {"ok": True}


class _FakeSupervisor:
    instances: list[_FakeSupervisor] = []

    def __init__(self, *, database: Any, paths: Any, resident: Any) -> None:
        self.resident = resident
        self.runs = 0
        _FakeSupervisor.instances.append(self)

    def run_once(self) -> _Report:
        self.runs += 1
        return _Report()


class _FakeServices:
    def __init__(self) -> None:
        self.database = object()
        self.resident = object()  # stands in for the shared Ollama-backed resident manager
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    _FakeSupervisor.instances = []
    built: list[_FakeServices] = []
    sleeps: list[float] = []

    def build(_settings: Any) -> _FakeServices:
        services = _FakeServices()
        built.append(services)
        return services

    monkeypatch.setattr(cli, "build_services", build)
    monkeypatch.setattr(cli, "HealthSupervisor", _FakeSupervisor)
    settings = SimpleNamespace(paths=object(), ollama_model="m", resident_check_seconds=60.0)
    return SimpleNamespace(built=built, sleeps=sleeps, settings=settings, monkeypatch=monkeypatch)


def test_loop_builds_services_once_and_reuses_resident(harness: SimpleNamespace) -> None:
    ticks = 0

    def sleep(seconds: float) -> None:
        nonlocal ticks
        harness.sleeps.append(seconds)
        ticks += 1
        if ticks == 3:
            raise KeyboardInterrupt

    harness.monkeypatch.setattr(cli.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        cli._run_supervisor(harness.settings, loop=True)

    assert len(harness.built) == 1
    assert len(_FakeSupervisor.instances) == 1
    supervisor = _FakeSupervisor.instances[0]
    assert supervisor.resident is harness.built[0].resident
    assert supervisor.runs == 3
    assert harness.sleeps == [60.0, 60.0, 60.0]
    assert harness.built[0].close_calls == 1


def test_loop_closes_services_once_when_health_raises(harness: SimpleNamespace) -> None:
    def boom(self: _FakeSupervisor) -> _Report:
        raise RuntimeError("probe failed")

    harness.monkeypatch.setattr(_FakeSupervisor, "run_once", boom)
    harness.monkeypatch.setattr(cli.time, "sleep", lambda _s: pytest.fail("no sleep"))
    with pytest.raises(RuntimeError):
        cli._run_supervisor(harness.settings, loop=True)
    assert len(harness.built) == 1
    assert harness.built[0].close_calls == 1


def test_supervise_without_loop_runs_once_without_sleep(harness: SimpleNamespace) -> None:
    harness.monkeypatch.setattr(cli.time, "sleep", lambda _s: pytest.fail("no sleep"))
    assert cli._run_supervisor(harness.settings, loop=False) == 0
    assert _FakeSupervisor.instances[0].runs == 1
    assert harness.built[0].close_calls == 1


def test_one_shot_health_builds_and_closes_own_services(harness: SimpleNamespace) -> None:
    assert cli._run_health(harness.settings, skip_ollama=False) == 0
    assert cli._run_health(harness.settings, skip_ollama=False) == 0
    assert len(harness.built) == 2
    assert [s.close_calls for s in harness.built] == [1, 1]
    assert [i.runs for i in _FakeSupervisor.instances] == [1, 1]


def test_skip_ollama_does_not_use_services_resident(harness: SimpleNamespace) -> None:
    cli._run_health(harness.settings, skip_ollama=True)
    resident = _FakeSupervisor.instances[0].resident
    assert resident is not harness.built[0].resident
    assert resident.ensure_resident().status is cli.ResidentStatus.RESIDENT
