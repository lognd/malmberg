import logging

from malmberg_core.logging import get_logger


def test_get_logger_returns_logger() -> None:
    logger = get_logger("test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test"


def test_get_logger_idempotent() -> None:
    a = get_logger("test.idempotent")
    b = get_logger("test.idempotent")
    assert a is b


def test_formatter_debug_no_level_prefix(capsys: object) -> None:
    from malmberg_core.logging.formatter import MalmbergFormatter

    fmt = MalmbergFormatter(show_level=False)
    record = logging.LogRecord("x", logging.DEBUG, "", 0, "hello", (), None)
    assert fmt.format(record) == "hello"


def test_formatter_warning_prefixes_level() -> None:
    from malmberg_core.logging.formatter import MalmbergFormatter

    fmt = MalmbergFormatter(show_level=False)
    record = logging.LogRecord("x", logging.WARNING, "", 0, "uh oh", (), None)
    assert fmt.format(record) == "WARNING: uh oh"


def test_below_level_filter() -> None:
    from malmberg_core.logging.filter import BelowLevelFilter

    f = BelowLevelFilter("WARNING")
    debug = logging.LogRecord("x", logging.DEBUG, "", 0, "", (), None)
    warning = logging.LogRecord("x", logging.WARNING, "", 0, "", (), None)
    assert f.filter(debug) is True
    assert f.filter(warning) is False
