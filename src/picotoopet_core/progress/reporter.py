"""Narrow progress reporting boundary for Worker coordinators."""

from __future__ import annotations

from typing import Protocol

from .models import ProgressUpdate
from .repository import ProgressRepository


class ProgressReporter(Protocol):
    """Append one already-bounded progress fact to the canonical Core ledger."""

    def emit(self, update: ProgressUpdate) -> object:
        """Persist or record one progress fact."""


class RepositoryProgressReporter:
    """Production reporter backed only by the canonical ProgressRepository."""

    def __init__(self, repository: ProgressRepository) -> None:
        self.repository = repository

    def emit(self, update: ProgressUpdate) -> object:
        """Persist one progress fact without exposing a database handle to coordinators."""

        return self.repository.append(update)
