"""Прогон Subwatch на синтетическом почтовом ящике и запись docs/DEMO.md.

Запуск: uv run python scripts/demo.py

Всё происходит во временном каталоге: свой config.toml, своя база,
keyring в памяти, IMAP-сервер на localhost (tests/mock_imap.py) с письмами
из tests/fixtures/emails.py. Дата заморожена на 22 октября 2026, курсы
валют ручные — результат воспроизводится один в один.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="subwatch-demo-"))
for name in ("config", "data", "state", "cache", "runtime"):
    (TMP / name).mkdir(mode=0o700)
os.environ.update({
    "XDG_CONFIG_HOME": str(TMP / "config"), "XDG_DATA_HOME": str(TMP / "data"),
    "XDG_STATE_HOME": str(TMP / "state"), "XDG_CACHE_HOME": str(TMP / "cache"),
    "XDG_RUNTIME_DIR": str(TMP / "runtime"), "SUBWATCH_NOW": "2026-10-22T12:00:00",
    "SUBWATCH_NOTIFY_RECORD": str(TMP / "notifications.jsonl"), "SUBWATCH_LOGGING__JOURNAL": "false",
    "COLUMNS": "110", "TZ": "Asia/Almaty",
})
os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

import keyring  # noqa: E402
from conftest import MemoryKeyring  # noqa: E402
from fixtures.emails import EMAILS  # noqa: E402
from mock_imap import MockImapServer, ServerState  # noqa: E402

keyring.set_keyring(MemoryKeyring())

from subwatch import clock  # noqa: E402
from subwatch.__main__ import main  # noqa: E402

clock.set_timezone("Asia/Almaty")

STATEMENT = "\n".join(["Дата;Сумма;Описание"] + [
    line for m in range(5, 11) for line in (
        f"14.{m:02d}.2026;-1 590,00;SPOTIFY P{m}A7",
        f"{(m * 5) % 26 + 1:02d}.{m:02d}.2026;-{[5400, 1200, 8800, 640, 3100, 2750][m - 5]},00;MAGNUM CASH&CARRY",
        f"09.{m:02d}.2026;-990,00;KCELL MUSIC",
    )
])


def cli(*args: str, stdin: str | None = None) -> str:
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                main(list(args))
            except SystemExit:
                pass
    finally:
        sys.stdin = old_stdin
    text = (out.getvalue() + err.getvalue()).replace(str(TMP), "~")
    return "\n".join(line.rstrip() for line in text.replace(" ", " ").splitlines()).strip()


def block(title: str, command: str, output: str, note: str = "") -> str:
    parts = [f"### {title}", "", "```console", f"$ {command}", output, "```", ""]
    if note:
        parts += [note, ""]
    return "\n".join(parts)


def main_demo() -> None:
    state = ServerState()
    for e in EMAILS:
        state.folders["INBOX"].append(e.to_bytes())
    sections: list[str] = []
    with MockImapServer(state) as srv:
        cfg = TMP / "config" / "subwatch" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cli("config", "init")
        cli("config", "set", "currency.rates_source", "manual")
        cli("rates", "set", "USD", "520")
        cli("rates", "set", "RUB", "6.4")
        cli("rates", "set", "EUR", "565")
        cli("config", "set", "budget.monthly_limit", "40000")

        sections.append(block(
            "1. Подключение почты по IMAP", f"subwatch auth imap --name demo --host 127.0.0.1 --port {srv.port} "
            "--user user@example.org --no-ssl", cli("auth", "imap", "--name", "demo", "--host", "127.0.0.1",
                                                     "--port", str(srv.port), "--user", "user@example.org",
                                                     "--no-ssl", "--password-stdin", stdin="app-password\n"),
            "Пароль приложения ушёл в keyring, в config.toml записаны только сервер, логин и папки."))

        sections.append(block("2. Первое сканирование", "subwatch scan", cli("scan"),
                              f"В ящике {len(EMAILS)} писем на русском, английском и казахском: чеки, продления, "
                              "пробные периоды, смена цены, отмены, а заодно заказ Ozon, коды подтверждения "
                              "и рассылки, которые подписками не являются. Сервер видел только EXAMINE и "
                              "BODY.PEEK — ни одной команды записи: "
                              f"{'нет' if not state.writes() else state.writes()}."))

        sections.append(block("3. Что нашлось", "subwatch list", cli("list")))
        sections.append(block("4. Очередь проверки", "subwatch review list", cli("review", "list"),
                              "Сюда попали находки, в которых Subwatch не уверен: неизвестный сервис или "
                              "платёж, который пришёл не от самого сервиса, а от банка."))
        confirm = cli("review", "confirm", "Мегадиск")
        reject = cli("review", "reject", "Tasklane")
        sections.append(block("5. Решения по очереди", "subwatch review confirm Мегадиск && subwatch review "
                              "reject Tasklane", confirm + "\n" + reject + "\n\n$ subwatch rules list\n" +
                              cli("rules", "list"),
                              "Решения запоминаются правилами: Мегадиск теперь принимается сразу, Tasklane больше "
                              "не предлагается."))

        statement = TMP / "kaspi.csv"
        statement.write_text(STATEMENT, encoding="utf-8")
        sections.append(block("6. Импорт выписки", "subwatch import kaspi.csv", cli("import", str(statement)),
                              "Spotify и Kcell списываются каждый месяц на одну и ту же сумму. Обе подписки уже "
                              "были известны по письмам, поэтому выписка их не дублирует, а добавляет историю "
                              "списаний. Покупки в Magnum тоже повторяются, но суммы и даты скачут — это не "
                              "подписка."))

        sections.append(block("7. Ближайшие списания", "subwatch upcoming --days 14", cli("upcoming", "--days", "14")))
        sections.append(block("8. Сколько уходит в месяц", "subwatch spend", cli("spend")))
        sections.append(block("9. По месяцам", "subwatch spend --by month --months 4",
                              cli("spend", "--by", "month", "--months", "4")))

        bar = json.loads(cli("bar"))
        sections.append(block("10. Модуль панели", "subwatch bar", json.dumps(bar, ensure_ascii=False, indent=2),
                              "Тот же JSON понимают и панель Omarchy (модуль `type: command`), и Waybar."))

        cli("remind")
        notes = [json.loads(line) for line in (TMP / "notifications.jsonl").read_text(encoding="utf-8").splitlines()]
        reminders = [n for n in notes if n["kind"] == "reminder"]
        shown = "\n\n".join(f"[{n['urgency']}] {n['summary']}\n{n['body']}" for n in reminders) or "—"
        other = "\n".join(f"[{n['kind']}] {n['summary']}: {n['body']}" for n in notes if n["kind"] != "reminder")
        sections.append(block("11. Напоминания", "subwatch remind  # обычно запускает таймер",
                              shown.replace(" ", " "),
                              "Уведомление Omarchy кнопок не рисует, поэтому клик по нему открывает меню "
                              "«Оставить / Отменить / Отложить». Кроме напоминаний за прогон пришли такие "
                              "уведомления:\n\n```text\n" + other.replace(" ", " ") + "\n```"))

        sections.append(block("12. Повторное сканирование", "subwatch scan", cli("scan"),
                              "Позиция в ящике запомнена (UIDVALIDITY и последний UID), письма повторно "
                              "не читаются."))

        cli("config", "set", "ai.enabled", "true")
        ai = cli("scan", "--ai-dry-run", "--full", "--reprocess")
        cli("config", "set", "ai.enabled", "false")
        requests = []
        for chunk in ai.split("Запрос ")[1:]:
            header = "Запрос " + chunk.splitlines()[0]
            user = chunk.split("[user]", 1)[1].split("\n\n", 1)[0].strip() if "[user]" in chunk else ""
            requests.append(header + "\n[user]\n" + user)
        shown_ai = "\n\n".join(requests[:3]) + ("\n\n…" if len(requests) > 3 else "")
        sections.append(block("13. Что ушло бы в AI-модель", "subwatch scan --ai-dry-run --full --reprocess",
                              shown_ai,
                              f"AI-слой выключен по умолчанию. В режиме --ai-dry-run видно, какие письма достались "
                              f"бы модели и какой именно текст ушёл бы. Здесь таких писем {len(requests)} из "
                              f"{len(EMAILS)} — только те, где правила не уверены. Системная инструкция одна для "
                              "всех запросов (src/subwatch/resources/ai_prompt.txt) и здесь не повторяется. "
                              "Адреса, номера карт и телефонов, приветствия и почтовые адреса вырезаны, "
                              "оставлены только строки с цифрами и словами про оплату."))

        ics = cli("export", "ics", "--output", "-").splitlines()
        start = next(i for i, line in enumerate(ics) if line.startswith("BEGIN:VEVENT"))
        sections.append(block("14. Календарь", "subwatch export ics --output -",
                              "\n".join(ics[:7] + ["…"] + ics[start:start + 16] + ["…"])))
        sections.append(block("15. Что хранится", "subwatch privacy", cli("privacy")))

    header = f"""# Демо на синтетическом ящике

Этот файл собран скриптом `scripts/demo.py`: он поднимает IMAP-сервер на
localhost с {len(EMAILS)} письмами из `tests/fixtures/emails.py`, создаёт
отдельный конфиг и базу во временном каталоге и вызывает настоящие команды
`subwatch`. Дата заморожена на 22 октября 2026, курсы валют заданы вручную
(1 $ = 520 ₸, 1 ₽ = 6,4 ₸, 1 € = 565 ₸), общий бюджет — 40 000 ₸ в месяц.

Пересобрать: `uv run python scripts/demo.py`.

"""
    (ROOT / "docs" / "DEMO.md").write_text(header + "\n".join(sections), encoding="utf-8")
    print(f"docs/DEMO.md записан, временные файлы: {TMP}")


if __name__ == "__main__":
    main_demo()
