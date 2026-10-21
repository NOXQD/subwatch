"""`subwatch auth gmail`: a step-by-step wizard for your own Google Cloud
project, OAuth with the gmail.readonly scope only, token into the keyring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from .. import paths
from ..errors import SubwatchError
from ..i18n import t
from .common import ask, confirm, console, ok, say, warn

STEPS = 7


def _load_client(path: Path) -> dict:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise SubwatchError("gmail.err.client_read", path=str(path), detail=exc.strerror or str(exc)) from None
    except ValueError:
        raise SubwatchError("gmail.err.client_json", hint="gmail.hint.client_type", path=str(path)) from None
    if "installed" not in data:
        raise SubwatchError("gmail.err.client_type", hint="gmail.hint.client_type", path=str(path))
    return data


def run_wizard(app, account: str, client_secret: Path | None, no_browser: bool, flow_factory=None) -> None:
    from ..config.editor import ensure_config_file, set_value
    from ..sources.gmail import SCOPES, build_service, save_credentials

    say(t("auth.gmail.title"), "bold")
    say(t("auth.gmail.intro"))
    say("")
    for n in range(1, STEPS + 1):
        say(t("auth.gmail.step_header", n=n, total=STEPS, title=t(f"auth.gmail.step{n}.title")), "bold cyan")
        say(t(f"auth.gmail.step{n}.body"))
        say("")
    if client_secret is None:
        if not sys.stdin.isatty():
            raise SubwatchError("gmail.err.need_client", hint="gmail.hint.client_flag")
        raw = ask(t("auth.gmail.ask_path"))
        if not raw:
            raise typer.Abort()
        client_secret = Path(raw.strip().strip("'\""))
    client = _load_client(client_secret)

    if flow_factory is None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        def flow_factory(cfg):  # noqa: E306
            return InstalledAppFlow.from_client_config(cfg, SCOPES)

    flow = flow_factory(client)
    say(t("auth.gmail.opening_browser") if not no_browser else t("auth.gmail.copy_url"), "bold")
    try:
        creds = flow.run_local_server(
            host="localhost", port=0, open_browser=not no_browser,
            authorization_prompt_message=t("auth.gmail.prompt_url"),
            success_message=t("auth.gmail.browser_success"),
            access_type="offline", prompt="consent",
        )
    except Exception as exc:  # oauthlib raises many kinds
        raise SubwatchError("gmail.err.oauth", hint="gmail.hint.oauth", detail=str(exc)) from None
    if not getattr(creds, "refresh_token", None):
        raise SubwatchError("gmail.err.no_refresh", hint="gmail.hint.no_refresh")
    scopes = set(getattr(creds, "scopes", None) or SCOPES)
    if scopes - set(SCOPES):
        warn(t("auth.gmail.extra_scopes", scopes=", ".join(sorted(scopes - set(SCOPES)))))
    save_credentials(account, creds)
    email = None
    try:
        email = build_service(creds).users().getProfile(userId="me").execute().get("emailAddress")
    except Exception:  # profile is a nicety, the token is already saved
        email = None
    ok(t("auth.gmail.connected", email=email or account))
    path, _ = ensure_config_file(app.loaded.path)
    set_value("sources.gmail.enabled", "true", path)
    set_value("sources.gmail.account", account, path)
    say(t("auth.gmail.saved", path=paths.contract_home(path)))
    if confirm(t("auth.gmail.delete_json", path=str(client_secret)), default=False):
        try:
            client_secret.expanduser().unlink()
            ok(t("auth.gmail.json_deleted"))
        except OSError as exc:
            warn(str(exc))
    say("")
    say(t("auth.gmail.reminder_production"), "yellow")
    say(t("cli.auth.next_scan"), "dim")
    console.print()
