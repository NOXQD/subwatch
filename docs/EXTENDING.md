# Расширение

Хуки, плагины-источники, свой справочник сервисов и шаблоны банков —
всё без правки кода.

## Хуки

В `[hooks]` перечисляются команды оболочки для событий:

| Событие | Когда |
|---|---|
| `new_subscription` | появилась подписка (из письма, выписки, вручную или после проверки) |
| `upcoming_charge` | ушло первое напоминание о списании |
| `price_changed` | изменилась цена |
| `job_failed` | фоновое сканирование завершилось с ошибкой |
| `budget_exceeded` | превышен общий бюджет или бюджет категории (раз в месяц) |
| `duplicate_found` | найден возможный дубль |
| `zombie_found` | подпиской давно не пользовались |
| `subscription_cancelled` | подписка отменена (письмом, из TUI, из уведомления) |

Каждая команда выполняется через `hooks.shell` (`bash -c`) с таймаутом
`hooks.timeout`. Данные события приходят в переменных окружения:

```
SUBWATCH_EVENT, SUBWATCH_SUBSCRIPTION_ID, SUBWATCH_SERVICE,
SUBWATCH_AMOUNT, SUBWATCH_CURRENCY, SUBWATCH_DATE, SUBWATCH_CATEGORY
```

плюс поля самого события (`SUBWATCH_OLD`, `SUBWATCH_NEW` у
`price_changed`, `SUBWATCH_DAYS_LEFT` у `upcoming_charge`,
`SUBWATCH_REASON` у `duplicate_found`, `SUBWATCH_SCOPE` у
`budget_exceeded`, `SUBWATCH_ERROR` у `job_failed`). Полностью событие
приходит JSON-ом на stdin.

```toml
[hooks]
price_changed = ['notify-send "Подорожал $SUBWATCH_SERVICE" "$SUBWATCH_OLD → $SUBWATCH_NEW"']
new_subscription = ['jq -r .subscription.service >> ~/subscriptions.log']
upcoming_charge = ['~/bin/to-telegram.sh "Скоро спишут $SUBWATCH_AMOUNT за $SUBWATCH_SERVICE"']
```

Упавший или зависший хук пишется в журнал и ничего не ломает.

## Плагины-источники

Источник — это один Python-файл в `~/.config/subwatch/plugins/`. Класс
регистрируется декоратором `@source("имя")` и отдаёт письма или банковские
операции; разбор, дедупликация, хранение и напоминания — общие.

```python
from datetime import date
from decimal import Decimal

from subwatch.plugins import RawMessage, Source, Transaction, source


@source("mybank")
class MyBank(Source):
    kind = "transactions"

    def enabled(self, config):
        return bool(config.plugins.options.get("mybank", {}).get("enabled"))

    def fetch(self, ctx):
        # ctx.options — раздел [plugins.options.mybank] из config.toml
        # ctx.since — с какой даты смотреть, ctx.store — база (курсоры и т. п.)
        yield Transaction(date=date(2026, 10, 3), amount=Decimal("2990"),
                          currency="KZT", merchant="YANDEX*PLUS")
```

```toml
[plugins.options.mybank]
enabled = true
```

Источник писем отдаёт `RawMessage(source=..., key=..., sender=...,
subject=..., text=...)`; `key` должен быть стабильным — по нему письмо не
разбирается дважды. Полный пример — `contrib/plugins/example_bank_api.py`.

```bash
subwatch plugins list        # загруженные источники и ошибки загрузки
subwatch scan --source mybank
```

Плагин, который не загрузился, не мешает остальным: ошибка видна в
`plugins list` и `doctor`. Отключить, не удаляя файл:
`plugins.disabled = ["mybank"]`.

## Свой справочник сервисов

`~/.config/subwatch/merchants.toml` дополняет встроенный справочник
(`src/subwatch/resources/merchants.toml`) или меняет его записи:

```toml
[megadisk]                       # новый сервис
name = "Мегадиск"
category = "cloud"
senders = ["megadisk.example"]   # домены отправителей
patterns = ['megadisk', 'мегадиск']   # регулярки для выписок и текста писем
period = "1m"
cancel_url = "https://megadisk.example/billing"

[netflix]                        # встроенный — в другой категории
category = "other"
```

У записей справочника есть ещё `includes` — какие сервисы входят в пакет
(например, Кинопоиск в Яндекс Плюс). По нему ищутся дубли.

Пример — `contrib/merchants.example.toml`.

## Шаблоны банков

См. [SOURCES.md](SOURCES.md#выписки) и `contrib/banks/example.toml`.

## Ключевые слова и перевод

Слова, по которым узнаются чеки, продления, отмены и периоды на трёх
языках, лежат в `src/subwatch/resources/keywords.toml`. Свои слова для
распознавания писем — `extraction.extra_keywords` в config.toml.

Строки интерфейса — в `src/subwatch/resources/i18n/ru.toml` и `en.toml`.
Свой язык или правка формулировок: положите
`~/.config/subwatch/i18n/<код>.toml` с нужными ключами и выберите язык в
`ui.language`. Недостающие строки возьмутся из русского каталога.
