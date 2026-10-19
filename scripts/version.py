"""Single source of truth for the Project Oracle version."""

__version__ = "2.0.1"


def start_subprocess_coverage() -> None:
    """Begin coverage measurement in a CLI subprocess when tests run under
    ``pytest --cov`` (audit #9). No-op when ``coverage`` is not installed, so
    the zero-dependency runtime promise is preserved.
    """
    try:  # pragma: no cover — only active under pytest-cov runs
        import coverage

        coverage.process_startup()
    except ImportError:  # pragma: no cover
        pass

