from __future__ import annotations

import sys
from typing import Protocol

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


class StepProgress(Protocol):
    def advance(self, amount: int = 1, description: str | None = None) -> None: ...

    def finish(self) -> None: ...


class _NullStepProgress:
    def advance(self, amount: int = 1, description: str | None = None) -> None:
        pass

    def finish(self) -> None:
        pass


class _RichStepProgress:
    def __init__(self, progress: Progress, task_id: int) -> None:
        self._progress = progress
        self._task_id = task_id
        self._finished = False

    def advance(self, amount: int = 1, description: str | None = None) -> None:
        if self._finished:
            return
        kwargs: dict = {"advance": amount}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(self._task_id, **kwargs)

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._progress.remove_task(self._task_id)
        except KeyError:
            pass


def create_progress(console: Console | None = None) -> Progress:
    if console is None:
        console = Console(force_terminal=True, legacy_windows=sys.platform == "win32")
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("осталось"),
        TimeRemainingColumn(),
        console=console,
        transient=False,
        refresh_per_second=4,
    )


def pause_for_input(progress: Progress | None) -> None:
    """Остановить Live-отрисовку Rich, чтобы input() работал в консоли."""
    if progress is not None:
        progress.stop()


def resume_after_input(progress: Progress | None) -> None:
    if progress is not None:
        progress.start()


def start_step(progress: Progress | None, description: str, total: int) -> StepProgress:
    if progress is None or total <= 0:
        return _NullStepProgress()
    task_id = progress.add_task(description, total=total)
    return _RichStepProgress(progress, task_id)
