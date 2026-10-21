"""Пример плагина-источника для Subwatch.

Положите файл в ~/.config/subwatch/plugins/ — он подхватится при следующем
сканировании. Настройки плагина берутся из config.toml:

    [plugins.options.example_bank]
    enabled = true
    export_dir = "~/Загрузки/bank-export"

Источник может отдавать операции (Transaction) — тогда Subwatch сам найдёт
среди них повторяющиеся списания — или письма (RawMessage), которые пройдут
через те же правила, что и почта. Проверить, что плагин загрузился:
subwatch plugins list
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from subwatch.plugins import Source, SourceContext, Transaction, source


@source("example_bank")
class ExampleBank(Source):
    kind = "transactions"

    def enabled(self, config):
        return bool(config.plugins.options.get("example_bank", {}).get("enabled"))

    def fetch(self, ctx: SourceContext):
        folder = Path(ctx.options.get("export_dir", "~/Загрузки/bank-export")).expanduser()
        for path in sorted(folder.glob("*.json")):
            for op in json.loads(path.read_text(encoding="utf-8")):
                if op.get("direction") != "debit":
                    continue
                day = date.fromisoformat(op["date"])
                if day < ctx.since:
                    continue
                yield Transaction(
                    date=day,
                    amount=Decimal(str(op["amount"])),
                    currency=op.get("currency", ctx.config.currency.base),
                    merchant=op["merchant"],
                )
