"""Helpers shared by CLI commands."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from ..app import AppContext
from ..config.loader import ConfigError, cli_overrides, load_config
from ..errors import SubwatchError
from ..i18n import t

F = TypeVar("F", bound=Callable[..., Any])

console = Console(highlight=False, soft_wrap=False)
err_console = Console(stderr=True, highlight=False)


class State:
    """Global options collected by the root callback."""

    config_path: str | None = None
    overrides: list[str] = []
    quiet: bool = False
    verbose: bool = False
    app: AppContext | None = None

    @classmethod
    def cli_layer(cls, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        from ..config.loader import deep_merge

        base = cli_overrides(cls.overrides)
        return deep_merge(base, extra or {})


def get_app(extra_cli: dict[str, Any] | None = None) -> AppContext:
    """The AppContext for this invocation (created on first use)."""
    if State.app is None or extra_cli:
        from pathlib import Path

        path = Path(State.config_path).expanduser() if State.config_path else None
        loaded = load_config(path, cli=State.cli_layer(extra_cli))
        if State.verbose:
            loaded.config.logging.level = "debug"
        State.app = AppContext(loaded, quiet_logs=State.quiet)
    return State.app


def print_error(exc: Exception) -> None:
    if isinstance(exc, ConfigError):
        err_console.print(f"[bold red]{t('cli.error_prefix')}[/] {exc.render()}", markup=True)
        err_console.print(t("cli.hint_config_check"))
        return
    if isinstance(exc, SubwatchError):
        err_console.print(f"[bold red]{t('cli.error_prefix')}[/] ", end="", markup=True)
        err_console.print(exc.message, markup=False)
        if exc.hint_text:
            err_console.print(f"[dim]{t('cli.hint_prefix')}[/] ", end="", markup=True)
            err_console.print(exc.hint_text, markup=False)
        return
    err_console.print(f"[bold red]{t('cli.error_prefix')}[/] ", end="", markup=True)
    err_console.print(t("cli.unexpected", detail=repr(exc)), markup=False)


def handle_errors(fn: F) -> F:
    """Turn our exceptions into readable messages and exit codes."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort, KeyboardInterrupt):
            raise
        except ConfigError as exc:
            print_error(exc)
            raise typer.Exit(78) from None
        except SubwatchError as exc:
            print_error(exc)
            raise typer.Exit(exc.exit_code) from None
        finally:
            if State.app is not None:
                State.app.close()
                State.app = None

    return wrapper  # type: ignore[return-value]


def say(text: str, style: str | None = None) -> None:
    """Print catalog text without interpreting rich markup in it."""
    if State.quiet:
        return
    console.print(text, style=style, markup=False)


def ok(text: str) -> None:
    say("✓ " + text, "green")


def warn(text: str) -> None:
    err_console.print("! " + text, style="yellow", markup=False)


def confirm(question: str, default: bool = False, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return default
    suffix = t("cli.yes_no_default_yes") if default else t("cli.yes_no_default_no")
    answer = console.input(escape(f"{question} {suffix} ")).strip().lower()
    if not answer:
        return default
    return answer in tuple(t("cli.yes_answers").split(","))


def ask(question: str, default: str | None = None, secret: bool = False) -> str:
    if secret:
        import getpass

        return getpass.getpass(question + " ")
    shown = f"{question} [{default}] " if default else f"{question} "
    answer = console.input(escape(shown)).strip()
    return answer or (default or "")
