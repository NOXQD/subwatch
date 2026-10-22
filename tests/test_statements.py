from datetime import date
from decimal import Decimal

import pytest

from subwatch import paths
from subwatch.app import AppContext
from subwatch.config.schema import Config
from subwatch.errors import SubwatchError
from subwatch.sources.statements import (
    BankTemplate,
    detect_template,
    load_templates,
    parse_pdf_text,
    pdf_text,
    read_statement,
    template_from_mapping,
)

TBANK_HEADER = ('"Дата операции";"Дата платежа";"Номер карты";"Статус";"Сумма операции";"Валюта операции";'
                '"Сумма платежа";"Валюта платежа";"Кэшбэк";"Категория";"MCC";"Описание";"Бонусы (включая кэшбэк)";'
                '"Округление на инвесткопилку";"Сумма операции с округлением"')


def tbank_row(day, amount, desc, status="OK", currency="RUB"):
    return (f'"{day} 10:15:00";"{day}";"*1234";"{status}";"{amount}";"{currency}";"{amount}";"{currency}";;'
            f'"Цифровые товары";"5815";"{desc}";"0,00";"0,00";"{amount}"')


def write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return p


def test_tbank_cp1251_detected(tmp_path):
    rows = [TBANK_HEADER]
    for m in range(5, 11):
        rows.append(tbank_row(f"03.{m:02d}.2026", "-299,00", "Яндекс Плюс"))
    rows.append(tbank_row("05.10.2026", "+5000,00", "Пополнение"))
    rows.append(tbank_row("06.10.2026", "-150,00", "Кофейня", status="FAILED"))
    p = write(tmp_path, "tbank.csv", "\n".join(rows), "cp1251")
    res = read_statement(p, Config())
    assert res.template.name == "tbank"
    assert len(res.transactions) == 6
    assert res.transactions[0].merchant == "Яндекс Плюс" and res.transactions[0].amount == Decimal(299)
    assert res.transactions[0].currency == "RUB"


def test_generic_ru_detected(tmp_path):
    p = write(tmp_path, "s.csv", "Дата;Сумма;Описание\n01.10.2026;-3 990,00;NETFLIX.COM*123\n"
                                 "02.10.2026;12 000,00;Зарплата\n")
    res = read_statement(p, Config())
    assert [t.merchant for t in res.transactions] == ["Netflix"]
    assert res.transactions[0].currency == "KZT"  # base currency when the file has none


def test_universal_mapping_and_save_template(tmp_path):
    p = write(tmp_path, "bank.csv", "Когда,Куда,Расход\n2026-09-01,SPOTIFY P1A,1590\n2026-10-01,SPOTIFY P2B,1590\n")
    tpl = template_from_mapping("date=Когда,description=Куда,debit=Расход", None, currency="KZT")
    res = read_statement(p, Config(), tpl)
    assert [t.merchant for t in res.transactions] == ["Spotify", "Spotify"]
    saved = paths.banks_dir() / "mybank.toml"
    saved.parent.mkdir(parents=True)
    tpl.name = "mybank"
    tpl.detect_headers = ["Когда", "Куда", "Расход"]
    saved.write_text(tpl.to_toml(), encoding="utf-8")
    loaded = load_templates()["mybank"]
    assert loaded.user and loaded.debit == "Расход"
    assert detect_template(p, p.read_text(), load_templates()).name == "mybank"


def test_missing_columns_message(tmp_path):
    p = write(tmp_path, "bad.csv", "A;B\n1;2\n")
    tpl = template_from_mapping("date=Дата,amount=Сумма,description=Описание")
    with pytest.raises(SubwatchError) as err:
        read_statement(p, Config(), tpl)
    assert "Дата" in err.value.message and "A, B" in err.value.message


def test_unknown_format(tmp_path):
    p = write(tmp_path, "x.csv", "foo;bar\n1;2\n")
    with pytest.raises(SubwatchError) as err:
        read_statement(p, Config())
    assert err.value.key == "statements.err.unknown_format"


def test_kaspi_pdf_lines():
    tpl = load_templates()["kaspi_gold"]
    text = "\n".join([
        "Выписка по Kaspi Gold за период с 01.05.26 по 21.10.26",
        "Дата Сумма Операция Детали",
        "03.05.26 - 2 490,00 ₸ Покупка YANDEX.PLUS",
        "03.06.26 - 2 490,00 ₸ Покупка YANDEX.PLUS",
        "03.07.26 - 2 490,00 ₸ Покупка YANDEX.PLUS",
        "05.07.26 + 50 000,00 ₸ Пополнение С Kaspi Депозита",
        "10.07.26 - 7 000,00 ₸ Перевод Асель К.",
    ])
    res = parse_pdf_text(text, tpl, "KZT", "sha")
    assert [(t.date, t.amount, t.merchant) for t in res.transactions] == [
        (date(2026, 5, 3), Decimal("2490.00"), "Яндекс Плюс"),
        (date(2026, 6, 3), Decimal("2490.00"), "Яндекс Плюс"),
        (date(2026, 7, 3), Decimal("2490.00"), "Яндекс Плюс"),
    ]


def make_pdf(path, lines):
    """A minimal one-page PDF with Helvetica text, enough for pdfplumber."""
    content = "BT /F1 11 Tf 50 780 Td 14 TL\n" + "\n".join(
        "(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for line in lines
    ) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> "
        "/Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def test_real_pdf_through_pdfplumber(tmp_path):
    p = tmp_path / "statement.pdf"
    make_pdf(p, ["ACME BANK monthly statement", "2026-08-05  NETFLIX.COM  -15.49 USD",
                 "2026-09-05  NETFLIX.COM  -15.49 USD", "2026-10-05  NETFLIX.COM  -17.99 USD"])
    assert "ACME BANK" in pdf_text(p)
    tpl = BankTemplate(name="acme", format="pdf", date_format="%Y-%m-%d", detect_text=["ACME BANK"],
                       line_regex=r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<description>\S+)\s+(?P<amount>-?[\d.]+)\s+(?P<currency>[A-Z]{3})$")
    res = read_statement(p, Config(), tpl)
    assert [t.amount for t in res.transactions] == [Decimal("15.49"), Decimal("15.49"), Decimal("17.99")]
    assert {t.currency for t in res.transactions} == {"USD"}


def test_import_finds_subscriptions_and_is_idempotent(tmp_path, capsys):
    from subwatch.__main__ import main

    rows = ["Дата;Сумма;Описание"]
    for m in range(5, 11):
        rows.append(f"03.{m:02d}.2026;-2 490,00;YANDEX*PLUS")
        rows.append(f"{(m * 7) % 27 + 1:02d}.{m:02d}.2026;-{[4500, 1200, 8900, 650, 3100, 15400][m - 5]},00;MAGNUM")
    p = write(tmp_path, "kaspi.csv", "\n".join(rows))
    for _ in range(2):
        try:
            main(["import", str(p)])
        except SystemExit:
            pass
    out = capsys.readouterr().out
    assert "Найдена подписка: Яндекс Плюс" in out and "уже импортирован" in out
    ctx = AppContext.load()
    sub = ctx.store.find_by_service("Яндекс Плюс")[0]
    assert sub.status == "active" and sub.source == "statement"
    assert sub.next_charge == date(2026, 11, 3) and sub.period.code == "1m"
    assert len(ctx.store.charges(sub.id)) == 6
    assert ctx.store.find_by_service("Magnum") == []
    stored = ctx.store.transactions()
    assert all(not hasattr(t, "card") for t in stored) and len(stored) == 12
    ctx.close()


def test_statements_inbox_dir_is_scanned(tmp_path):
    from conftest import write_config

    from subwatch.scan import run_job

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    rows = ["Дата;Сумма;Описание"] + [f"14.{m:02d}.2026;-1 590,00;SPOTIFY P{m}" for m in range(6, 11)]
    write(inbox, "oct.csv", "\n".join(rows))
    write_config(f'[sources.statements]\ninbox_dir = "{inbox}"\n[sources.imap]\nenabled = false\n')
    ctx = AppContext.load(quiet_logs=True)
    report = run_job(ctx)
    assert report.stats["statements"]["transactions"] == 5
    assert ctx.store.find_by_service("Spotify")[0].status == "active"
    report2 = run_job(ctx)
    assert report2.stats["statements"]["transactions"] == 0
    ctx.close()
