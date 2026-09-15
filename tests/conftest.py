"""Test setup.

This test tree runs against the REAL `legal_monitor` source (copied from the
user's machine, not reimplemented), targeting the specific functions that
were fixed/reviewed in this session: the connector date-window filter, the
retry helper, the classify.py scoring formula, the cli.py serve non-loopback
warning, and the prompt-artifact / weak-analysis detectors in
analysis_text.py.

Some of the app's real dependencies (sqlalchemy, rich, typer, feedparser)
are not installable in this sandbox (its package index does not mirror
them), while the code paths under test never actually exercise their
behaviour - `models.py` only needs sqlalchemy importable so its
plain-dataclass `RawDocument` becomes reachable, `classify.py`/
`monitoring.py`/`progress.py` only need `rich` importable at module load
time, and `cli.py` only needs `typer`'s decorators to pass functions through
unchanged (tests call cli.py's functions directly, never through typer's
CLI-parsing/dispatch layer). So: lightweight stand-ins are installed into
sys.modules before anything under `legal_monitor` is imported, providing
just enough surface (inert classes/functions) for those modules to import
cleanly, without faking any ORM/rendering/CLI-parsing behaviour that any
test relies on. If a real package becomes installable here later, its stub
can simply be deleted - nothing else references them.
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
        # Real SQLAlchemy generates a kwargs-accepting __init__ for a
        # declarative model automatically. This sandbox-only stub mimics
        # just that (Document(source=..., title=..., ...) needs to work
        # for tests that construct model instances directly, without a
        # real engine/session) - inert on the real machine, where the
        # genuine DeclarativeBase is used instead.
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class _Mapped:
        def __class_getitem__(cls, _item):
            return cls

    class _PermissiveColumn:
        """Stands in for a mapped column's class-level descriptor.

        Real SQLAlchemy columns support `.isnot()`, `==`, `>=`, etc. for
        building filter expressions. This sandbox's FakeQuery-based tests
        never actually evaluate those expressions (their fake .filter()
        ignores its arguments) - they just need the *construction* of the
        expression (e.g. `Document.register_date.isnot(None)`) not to raise.
        """

        def __getattr__(self, _name):
            return lambda *_a, **_k: self

        def __eq__(self, _other):
            return self

        def __ne__(self, _other):
            return self

        def __lt__(self, _other):
            return self

        def __le__(self, _other):
            return self

        def __gt__(self, _other):
            return self

        def __ge__(self, _other):
            return self

        def __hash__(self):
            return id(self)

    def mapped_column(*_args, **_kwargs):
        return _PermissiveColumn()

    def relationship(*_args, **_kwargs):
        return None

    sa_orm.DeclarativeBase = DeclarativeBase
    sa_orm.Mapped = _Mapped
    sa_orm.mapped_column = mapped_column
    sa_orm.relationship = relationship
    sa_orm.sessionmaker = _unavailable
    sa_orm.Query = type("Query", (), {})
    sa_orm.Session = type("Session", (), {})
    # Only needs to exist as an importable name - export.py passes it to
    # Query.options(), which the tests that touch that code path stub out
    # entirely (they replace session.query() before .options() is ever
    # reached), so it never needs to do anything.
    sa_orm.joinedload = lambda *_args, **_kwargs: None

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
        # Real rich.console.Console.print() renders markup and writes to a
        # stream. Tests that check cli.py's user-facing messages (e.g. the
        # non-loopback --host warning) need to observe what was printed, so
        # this stand-in records each call's positional args instead of
        # silently discarding them - inert on the real machine, where the
        # genuine Console is used instead.
        def __init__(self, *args, **kwargs) -> None:
            self.printed: list[tuple] = []

        def print(self, *args, **kwargs) -> None:
            self.printed.append(args)

    rich_console.Console = Console

    rich_table = types.ModuleType("rich.table")

    class Table:
        # Only needs to accept construction kwargs (title=...) and the
        # add_column()/add_row() calls cli.py makes when building its
        # summary tables - no test currently inspects rendered table
        # contents, only the plain console.print() messages around them.
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_column(self, *args, **kwargs) -> None:
            pass

        def add_row(self, *args, **kwargs) -> None:
            pass

    rich_table.Table = Table

    rich.progress = rich_progress
    rich.console = rich_console
    rich.table = rich_table
    sys.modules["rich"] = rich
    sys.modules["rich.progress"] = rich_progress
    sys.modules["rich.console"] = rich_console
    sys.modules["rich.table"] = rich_table


def _install_typer_stub() -> None:
    try:
        import typer  # noqa: F401
    except ImportError:
        pass
    else:
        return  # the real package is installed here - use it, do not shadow it

    typer = types.ModuleType("typer")

    class Typer:
        # Real typer.Typer() collects commands via @app.command(...) and
        # builds a Click-based CLI app from them. Tests here call the
        # decorated functions directly (e.g. cli.serve(...)), never through
        # typer's command-line dispatch, so the stand-in only needs
        # @app.command() / @app.command("name") to return the function
        # unchanged - not to actually register or dispatch anything.
        def __init__(self, *args, **kwargs) -> None:
            pass

        def command(self, *args, **kwargs):
            def _decorator(fn):
                return fn

            return _decorator

        def callback(self, *args, **kwargs):
            def _decorator(fn):
                return fn

            return _decorator

    def Option(default=None, *args, **kwargs):
        # Real typer.Option() returns metadata that typer's CLI-parsing
        # layer resolves into the actual argument value at call time. Since
        # tests call the underlying functions directly with explicit
        # keyword arguments, this only needs to supply the same default a
        # direct call without that keyword would otherwise be missing.
        return default

    def Argument(default=None, *args, **kwargs):
        return default

    class Exit(Exception):
        def __init__(self, code: int = 0) -> None:
            self.code = code
            super().__init__(code)

    typer.Typer = Typer
    typer.Option = Option
    typer.Argument = Argument
    typer.Exit = Exit
    sys.modules["typer"] = typer


def _install_feedparser_stub() -> None:
    try:
        import feedparser  # noqa: F401
    except ImportError:
        pass
    else:
        return  # the real package is installed here - use it, do not shadow it

    feedparser = types.ModuleType("feedparser")
    # Only needs to exist and be importable - duma.py's DumaRssConnector
    # only calls feedparser.parse() inside fetch(), which none of the
    # current tests exercise directly (they either stub httpx.Client and
    # go through pravo/regulation/sozd, or bypass fetch()/connectors
    # entirely). A no-op stand-in keeps `import feedparser` at module load
    # time from blowing up module collection for every test that transitively
    # imports legal_monitor.pipeline.ingest (which imports duma.py).
    feedparser.parse = lambda *_args, **_kwargs: types.SimpleNamespace(entries=[])
    sys.modules["feedparser"] = feedparser


_install_sqlalchemy_stub()
_install_rich_stub()
_install_typer_stub()
_install_feedparser_stub()
