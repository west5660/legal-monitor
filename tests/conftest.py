"""Test setup.

This test tree runs against the REAL `legal_monitor` source (copied from the
user's machine, not reimplemented), targeting the specific functions that
were fixed/reviewed in this session: the connector date-window filter, the
retry helper, the classify.py scoring formula, and the prompt-artifact /
weak-analysis detectors in analysis_text.py.

Two of the app's real dependencies (sqlalchemy, rich) are not installable in
this sandbox (its package index does not mirror them), while the code paths
under test never actually exercise their behaviour - `models.py` only needs
sqlalchemy importable so its plain-dataclass `RawDocument` becomes
reachable, and `classify.py`/`monitoring.py`/`progress.py` only need `rich`
importable at module load time. So: lightweight stand-ins are installed into
sys.modules before anything under `legal_monitor` is imported, providing
just enough surface (inert classes/functions) for those modules to import
cleanly, without faking any ORM/rendering behaviour that any test relies on.
If sqlalchemy/rich become installable here later, these stubs can simply be
deleted - nothing else references them.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _install_sqlalchemy_stub() -> None:
    try:
        import sqlalchemy  # noqa: F401
        import sqlalchemy.orm  # noqa: F401
    except ImportError:
        pass
    else:
        return  # the real package is installed here - use it, do not shadow it

    sa = types.ModuleType("sqlalchemy")

    class _Inert:
        """Stands in for a SQLAlchemy column-type/construct class.

        Only needs to be callable with arbitrary args (as in `String(50)`,
        `ForeignKey("documents.id")`, `UniqueConstraint(...)`) or referenced
        bare (as in `Text`, `Float`) without raising.
        """

        def __init__(self, *args, **kwargs) -> None:
            pass

    for name in (
        "Boolean",
        "Date",
        "DateTime",
        "Float",
        "ForeignKey",
        "String",
        "Text",
        "UniqueConstraint",
    ):
        setattr(sa, name, type(name, (_Inert,), {}))

    def _unavailable(*_args, **_kwargs):
        raise RuntimeError(
            "sqlalchemy is stubbed out in this test environment - "
            "no real DB/engine access is available here"
        )

    sa.create_engine = _unavailable
    sa.inspect = _unavailable
    sa.text = lambda s: s

    class _Event:
        @staticmethod
        def listens_for(*_args, **_kwargs):
            def _decorator(fn):
                return fn

            return _decorator

    sa.event = _Event()

    sa_orm = types.ModuleType("sqlalchemy.orm")

    class DeclarativeBase:
        pass

    class _Mapped:
        def __class_getitem__(cls, _item):
            return cls

    def mapped_column(*_args, **_kwargs):
        return None

    def relationship(*_args, **_kwargs):
        return None

    sa_orm.DeclarativeBase = DeclarativeBase
    sa_orm.Mapped = _Mapped
    sa_orm.mapped_column = mapped_column
    sa_orm.relationship = relationship
    sa_orm.sessionmaker = _unavailable
    sa_orm.Query = type("Query", (), {})
    sa_orm.Session = type("Session", (), {})

    sa.orm = sa_orm
    sys.modules["sqlalchemy"] = sa
    sys.modules["sqlalchemy.orm"] = sa_orm


def _install_rich_stub() -> None:
    try:
        import rich.progress  # noqa: F401
        import rich.console  # noqa: F401
    except ImportError:
        pass
    else:
        return  # the real package is installed here - use it, do not shadow it

    rich = types.ModuleType("rich")

    rich_progress = types.ModuleType("rich.progress")

    class Progress:
        pass

    for name in (
        "BarColumn",
        "MofNCompleteColumn",
        "TaskProgressColumn",
        "TextColumn",
        "TimeElapsedColumn",
        "TimeRemainingColumn",
    ):
        setattr(rich_progress, name, type(name, (), {}))
    rich_progress.Progress = Progress

    rich_console = types.ModuleType("rich.console")

    class Console:
        pass

    rich_console.Console = Console

    rich.progress = rich_progress
    rich.console = rich_console
    sys.modules["rich"] = rich
    sys.modules["rich.progress"] = rich_progress
    sys.modules["rich.console"] = rich_console


_install_sqlalchemy_stub()
_install_rich_stub()
