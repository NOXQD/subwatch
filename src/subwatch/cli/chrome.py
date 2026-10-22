"""Localising the parts of the CLI that come from typer and its bundled click.

Typer renders help panels with module-level constants and builds error
messages from English f-strings. We swap the constants for catalog text and
translate the error messages by pattern. Everything shown still comes from
the catalog (cli.chrome.*); the English patterns below only *recognise*
library messages.
"""

from __future__ import annotations

import re
from functools import wraps
from typing import Any

from ..i18n import t

_GETTEXT = {
    "(dynamic)": "cli.chrome.dynamic",
    "Aborted!": "cli.chrome.aborted",
    "default: {default}": "cli.chrome.default_inline",
    "required": "cli.chrome.required_inline",
    "env var: {var}": "cli.chrome.envvar_inline",
    "Arguments": "cli.chrome.arguments",
    "Options": "cli.chrome.options",
    "Commands": "cli.chrome.commands",
    "Missing command.": "cli.chrome.missing_command",
    "No such command {name!r}.": "cli.chrome.no_such_command",
}

# (pattern of a library message, catalog key); named groups become params.
_MESSAGES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^Missing argument '?(?P<name>[^'.]*)'?\.(?P<rest>.*)$", re.S), "cli.chrome.missing_argument"),
    (re.compile(r"^Missing option '?(?P<name>[^'.]*)'?\.(?P<rest>.*)$", re.S), "cli.chrome.missing_option"),
    (re.compile(r"^Missing parameter:? '?(?P<name>[^'.]*)'?\.?(?P<rest>.*)$", re.S), "cli.chrome.missing_parameter"),
    (re.compile(r"^No such option: (?P<name>\S+) \(Possible options: (?P<options>.+)\)$"),
     "cli.chrome.no_such_option_hint"),
    (re.compile(r"^No such option: (?P<name>\S+)$"), "cli.chrome.no_such_option"),
    (re.compile(r"^Got unexpected extra arguments? \((?P<args>.+)\)$"), "cli.chrome.extra_args"),
    (re.compile(r"^Option '(?P<name>.+)' requires an argument\.$"), "cli.chrome.requires_arg"),
    (re.compile(r"^Option '(?P<name>.+)' requires (?P<n>\d+) arguments\.$"), "cli.chrome.requires_args"),
    (re.compile(r"^Option '(?P<name>.+)' does not take a value\.$"), "cli.chrome.no_value"),
    (re.compile(r"^Invalid value for (?P<name>.+?): (?P<detail>.+)$", re.S), "cli.chrome.invalid_value_for"),
    (re.compile(r"^Invalid value: (?P<detail>.+)$", re.S), "cli.chrome.invalid_value"),
]

_DETAILS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^'(?P<value>.*)' is not a valid (?:integer|int)( range)?\.$"), "cli.chrome.not_int"),
    (re.compile(r"^'(?P<value>.*)' is not a valid float( range)?\.$"), "cli.chrome.not_float"),
    (re.compile(r"^'(?P<value>.*)' is not a valid boolean\..*$"), "cli.chrome.not_bool"),
    (re.compile(r"^'(?P<value>.*)' is not one of (?P<choices>.+)\.$"), "cli.chrome.not_choice"),
    (re.compile(r"^(?P<value>.+) is not in the range (?P<range>.+)\.$"), "cli.chrome.not_in_range"),
    (re.compile(r"^'(?P<value>.*)' does not match the formats? (?P<formats>.+)\.$"), "cli.chrome.bad_format"),
    (re.compile(r"^(?:File|Path|Directory) '(?P<path>.+)' does not exist\.$"), "cli.chrome.path_missing"),
    (re.compile(r"^(?:File|Path) '(?P<path>.+)' is a directory\.$"), "cli.chrome.path_is_dir"),
]


def translate_message(message: str) -> str:
    for rx, key in _MESSAGES:
        m = rx.match(message)
        if m:
            params = {k: (v or "").strip() for k, v in m.groupdict().items()}
            if "detail" in params:
                params["detail"] = translate_detail(params["detail"])
            return t(key, **params)
    return translate_detail(message)


def translate_detail(detail: str) -> str:
    for rx, key in _DETAILS:
        m = rx.match(detail)
        if m:
            return t(key, **{k: (v or "") for k, v in m.groupdict().items()})
    return detail


def _gettext(msgid: str) -> str:
    key = _GETTEXT.get(msgid)
    return t(key) if key else msgid


_installed = False


def install() -> None:
    """Patch typer once, after the language has been chosen."""
    global _installed
    import typer.core as tcore
    import typer.rich_utils as ru
    from typer._click import core as ccore
    from typer._click import exceptions as cexc
    from typer._click import formatting as cfmt

    tcore._ = _gettext  # type: ignore[attr-defined]
    ru._ = _gettext  # type: ignore[attr-defined]
    ru.DEPRECATED_STRING = t("cli.chrome.deprecated")
    ru.DEFAULT_STRING = t("cli.chrome.default")
    ru.ENVVAR_STRING = t("cli.chrome.envvar")
    ru.REQUIRED_LONG_STRING = t("cli.chrome.required")
    ru.ARGUMENTS_PANEL_TITLE = t("cli.chrome.arguments")
    ru.OPTIONS_PANEL_TITLE = t("cli.chrome.options")
    ru.COMMANDS_PANEL_TITLE = t("cli.chrome.commands")
    ru.ERRORS_PANEL_TITLE = t("cli.chrome.error")
    ru.ABORTED_TEXT = t("cli.chrome.aborted")
    ru.RICH_HELP = t("cli.chrome.try_help")
    if hasattr(ru, "RANGE_STRING"):
        ru.RANGE_STRING = t("cli.chrome.range")
    usage = t("cli.chrome.usage")
    ru.OptionHighlighter.highlights = [
        h for h in ru.OptionHighlighter.highlights if "usage" not in h
    ] + [rf"(?P<usage>{re.escape(usage)} )"]
    if _installed:
        return
    _installed = True

    original_usage = cfmt.HelpFormatter.write_usage

    @wraps(original_usage)
    def write_usage(self, prog: str, args: str = "", prefix: str | None = None) -> None:
        if prefix is None:
            prefix = t("cli.chrome.usage") + " "
        original_usage(self, prog, args, prefix)

    cfmt.HelpFormatter.write_usage = write_usage  # type: ignore[method-assign]

    original_help = ccore.Command.get_help_option

    @wraps(original_help)
    def get_help_option(self, ctx):
        opt = original_help(self, ctx)
        if opt is not None:
            opt.help = t("cli.chrome.help_option")
        return opt

    ccore.Command.get_help_option = get_help_option  # type: ignore[method-assign]

    for name in dir(cexc):
        cls = getattr(cexc, name)
        if isinstance(cls, type) and issubclass(cls, cexc.ClickException) and "format_message" in cls.__dict__:
            _wrap_format(cls)


def _wrap_format(cls: Any) -> None:
    original = cls.__dict__["format_message"]

    @wraps(original)
    def format_message(self) -> str:
        return translate_message(original(self))

    cls.format_message = format_message
