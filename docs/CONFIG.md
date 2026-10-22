# Настройки

Один файл: `~/.config/subwatch/config.toml`. При установке он создаётся с
комментарием к каждому параметру — это и есть полный справочник, здесь
только обзор и примеры. Другой путь можно указать через `--config` или
переменную `SUBWATCH_CONFIG`.

## Откуда берётся значение

От высшего приоритета к низшему:

1. **Командная строка.** Общий флаг `--set ключ=значение` (можно несколько
   раз) и флаги отдельных команд, например `subwatch scan --months 3`.
2. **Переменные окружения** `SUBWATCH_<РАЗДЕЛ>__<КЛЮЧ>`. Двойное
   подчёркивание разделяет уровни: `SUBWATCH_CURRENCY__BASE=USD`,
   `SUBWATCH_REMINDERS__QUIET_HOURS__START=23:00`. Значение читается как
   TOML (`7`, `true`, `[7, 3, 1]`), списки можно писать через запятую:
   `SUBWATCH_REMINDERS__DAYS_BEFORE=7,3,1`.
3. **config.toml.**
4. **Значения по умолчанию** из схемы.

```bash
$ subwatch config get currency.base --source
"KZT"    # из config.toml
$ SUBWATCH_CURRENCY__BASE=USD subwatch config get currency.base --source
"USD"    # из переменной окружения
$ subwatch config diff
reminders.days_before: [3, 1] → [7, 3, 1] (из config.toml)
```

Язык интерфейса подчиняется тому же порядку, но выбирается до разбора
остальных настроек: `--lang en` > `SUBWATCH_UI__LANGUAGE` > `ui.language`.

## Команды

| Команда | Что делает |
|---|---|
| `config get КЛЮЧ [--source]` | значение и его источник |
| `config set КЛЮЧ ЗНАЧЕНИЕ` | меняет файл, сохраняя комментарии; неверное значение не записывается |
| `config unset КЛЮЧ` | убирает ключ из файла, действует значение по умолчанию |
| `config edit` | открывает `$EDITOR` и проверяет файл после сохранения; если он сломан — предложит поправить или вернуть как было |
| `config reset [КЛЮЧ]` | возвращает стандартный файл (старый сохраняется рядом с суффиксом `.bak.<дата>`) или один ключ |
| `config diff` | чем действующие настройки отличаются от стандартных |
| `config check` | проверка без запуска чего-либо ещё |
| `config show [--sources]` | все действующие значения |

## Когда изменения вступают в силу

- TUI раз в `ui.reload_interval` секунд проверяет файл и тему Omarchy и
  перечитывает их: клавиши, цвета, сортировка, данные меняются без
  перезапуска. Если файл в этот момент сломан, TUI работает со старыми
  настройками и показывает ошибку.
- Сканирование и напоминания читают файл при каждом запуске таймера.
- Расписание таймеров, горячие клавиши, интервал модуля панели и язык
  требуют перезаписи файлов systemd, Hyprland и меню. `config set` и
  `config edit` делают это сами; после ручной правки файла выполните
  `subwatch integrate apply`.

## Разделы

### `[reminders]` — напоминания

```toml
[reminders]
days_before = [3, 1]        # за сколько дней (0 — в день списания)
time = "10:00"
repeat_unacknowledged = true
repeat_every = "4h"
max_repeats = 2
snooze = "1d"
snooze_options = ["3h", "1d", "3d"]
trial_days_before = [2, 0]  # о конце пробного периода
amount_basis = "charge"     # пороги сумм: по списанию или в пересчёте на месяц

[reminders.quiet_hours]
start = "22:00"
end = "08:00"
```

Правила уточняют общие настройки для части подписок. Из подходящих
правил действует самое конкретное: **по сервису > по сумме > по
категории**; при равенстве — первое в файле. Не указанные в правиле поля
берутся из `[reminders]`.

```toml
[[reminders.rules]]
name = "дорогие — за неделю"
min_amount = 10000          # в базовой валюте
days_before = [7, 3, 1]

[[reminders.rules]]
categories = ["video"]
time = "19:00"

[[reminders.rules]]
services = ["iCloud+"]
enabled = false             # не напоминать вовсе
```

Напоминание, попавшее в тихие часы, приходит в их конце. Если на него не
отреагировали, оно повторяется каждые `repeat_every`, но не чаще
`max_repeats` раз и тоже не в тихие часы. «Оставить» гасит все оставшиеся
напоминания об этом списании, «Отложить» переносит его, «Отменить»
открывает страницу отмены (если она известна) и помечает подписку
отменённой.

### `[currency]` — валюты

```toml
[currency]
base = "KZT"
rates_source = "auto"   # auto | nbk | cbr | open_er_api | frankfurter | manual
cache_ttl_hours = 12

[currency.manual_rates]
USD = 520.0             # сколько базовой валюты стоит единица
```

`auto` выбирает Нацбанк РК для тенге, ЦБ РФ для рубля и open.er-api для
остального. Курсы скачиваются при сканировании и хранятся в базе. Без сети
используются сохранённые курсы, а для валют, которых там нет, — ручные.
`rates_source = "manual"` вообще отключает загрузку.

### `[categories]`, `category_rules`, `tag_rules`, `[budget]`

```toml
[budget]
monthly_limit = 40000   # общий лимит в месяц
warn_at_pct = 90        # предупреждать с 90 %

[categories.video]
name = "Видео"
icon = "󰎁"
budget = 8000

[categories.health]     # своя категория
name = "Здоровье"

[[category_rules]]      # срабатывают раньше встроенного справочника
category = "education"
senders = ["*@skillbox.ru"]

[[tag_rules]]
tag = "работа"
services = ["JetBrains", "GitHub Copilot"]
```

Список категорий в файле полный: если убрать категорию из файла, её не
будет. Подписки, которым справочник прочит удалённую категорию, попадут в
`other`. Превышение лимита меняет цвет модуля панели и один раз в месяц
присылает уведомление (и запускает хук `budget_exceeded`).

### `[scan]`, `[sources.*]`, `[filters]`

```toml
[scan]
schedule = "daily"      # OnCalendar: "hourly", "*-*-* 09:00", "Mon..Fri 08:30" или интервал "6h"
months_back = 12        # глубина первого сканирования
max_messages = 5000
nice = 10
io_class = "idle"

[sources.gmail]
labels = []             # пусто — вся почта, кроме exclude_labels
exclude_labels = ["SPAM", "TRASH"]
query = "-category:promotions"

[filters]
exclude_senders = ["*@news.example.com", "promo@*"]
exclude_services = ["Ozon"]
exclude_keywords = ["рассылка"]
```

Маски отправителей проверяются и по полному адресу, и по домену:
`*netflix.com` отсечёт и `info@netflix.com`, и `info@mailer.netflix.com`.
Решения «это не подписка» из очереди проверки хранятся отдельно, в базе:
`subwatch rules list`.

### `[extraction]`, `[recurrence]`

Пороги уверенности: от `auto_accept` (0.8) находка сразу становится
подпиской, от `review_threshold` (0.45) — попадает в очередь проверки,
ниже — отбрасывается. `languages` ограничивает языки ключевых слов,
`extra_keywords` добавляет свои.

В `[recurrence]` — периоды (в днях), допуск по дате и сумме и сколько раз
списание должно повториться, чтобы считаться подпиской.

### `[detection]`

```toml
[detection]
price_change_pct = 1.0      # о подорожании меньше 1 % не сообщать
duplicates = true
duplicate_similarity = 0.85
zombies = true
zombie_days = 45
```

«Зомби» ищутся только среди подписок, где вы хоть раз отметили
использование (`u` в TUI или `subwatch used <сервис>`).

### `[notifications]`

`backend = "auto"` сам определяет демон. В Omarchy 4 уведомления показывает
`omarchy-shell`: кнопок там нет, клик открывает меню действий. С mako,
dunst или swaync появляются настоящие кнопки. `none` отключает показ, но
хуки продолжают работать. Отдельно включаются уведомления об итогах
сканирования, ошибках, бюджете, подорожании, дублях и «зомби».

### `[hooks]`

Команды оболочки на события, подробно — в [EXTENDING.md](EXTENDING.md).

### `[export]`, `[bar]`, `[keybinds]`, `[menu]`, `[ui]`

Календарь `.ics`, модуль панели, горячие клавиши, меню и TUI — описаны в
[OMARCHY.md](OMARCHY.md). В `[ui.keys]` любую клавишу TUI можно
переназначить, имена клавиш — как в Textual: `j`, `G` (Shift+g),
`ctrl+d`, `slash`, `question_mark`.

### `[storage]`, `[logging]`, `[ai]`, `[plugins]`

См. [PRIVACY.md](PRIVACY.md), [AI.md](AI.md) и [EXTENDING.md](EXTENDING.md).
Журнал пишется в journald: `subwatch logs` или
`journalctl --user -t subwatch SUBWATCH_EVENT=scan_finished`.
