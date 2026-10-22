# Интеграция с Omarchy

Subwatch писался под Omarchy 4, где панель, уведомления и меню — это одна
Quickshell-оболочка, а Hyprland настраивается на Lua. Всё подключается
через пользовательские файлы, пакетный `/usr/share/omarchy` не трогается.
Разбор того, как устроена система и что безопасно менять, — в
[ENVIRONMENT.md](ENVIRONMENT.md).

```bash
subwatch integrate apply                 # подключить всё
subwatch integrate apply --only bar      # только панель
subwatch integrate apply --dry-run       # показать, что изменится
subwatch integrate status                # что подключено
subwatch integrate remove                # убрать
```

Перед правкой общего файла делается копия рядом
(`*.subwatch-bak.<дата>`). Subwatch пишет только блок между маркерами
`>>> subwatch >>>` и `<<< subwatch <<<`; после `integrate remove` файл
становится таким, каким был.

## Панель

В `~/.config/omarchy/shell.json` добавляется модуль `type: command`,
который раз в `bar.interval` секунд вызывает `subwatch bar`. Модуль
показывает ближайшее списание, если оно в пределах `bar.next_within_days`,
и сумму в месяц в остальное время (`bar.mode` меняет это поведение).
Во всплывающей подсказке — сумма, бюджеты, ближайшие списания и сколько
находок ждут проверки. Клик открывает TUI, правый клик — меню, средний
запускает сканирование.

При превышении бюджета модуль получает класс `active` — панель Omarchy
подсвечивает его цветом `urgent` текущей темы. Ответ берётся из кэша,
пока не изменились база, конфиг или дата, поэтому частый опрос ничего не
стоит.

Секция панели выбирается в `bar.section`; перетащить модуль можно и
мышью, Subwatch потом не вернёт его на старое место.

### Waybar

Если на системе Waybar (Omarchy 3.x и другие сборки), `integrate apply`
кладёт `~/.config/waybar/subwatch.jsonc`, добавляет его в `include` и
вставляет `custom/subwatch` в `modules-right`. Если конфиг устроен
необычно (несколько панелей, нет `modules-right`), он не трогается —
готовый сниппет и стили лежат в `contrib/waybar/`. Классы модуля:
`next`, `soon`, `warn-budget`, `over-budget`, `empty`, `error`.

## Меню

В `~/.config/omarchy/extensions/omarchy-menu.jsonc` появляется пункт
«Subwatch» с подменю: ближайшие списания, все подписки, добавить,
очередь проверки, сколько я трачу, пересканировать, настройки. Файл
отслеживается оболочкой, перезапуск не нужен.

Парсер меню Omarchy понимает только комментарии на отдельной строке и
висячие запятые, поэтому блок Subwatch вставляется первым внутри объекта и
каждая его строка заканчивается запятой — строки пользователя при этом не
меняются.

Динамические списки («ближайшие списания») меню Omarchy строить не умеет,
поэтому их показывает `omarchy-menu-select` — тот же механизм выбора
пункта, которым пользуются скрипты самой Omarchy. Без Omarchy
`subwatch menu` ищет Walker, fuzzel, wofi, rofi или fzf (`menu.picker`).

Ещё ставится `~/.local/share/applications/subwatch.desktop` с действиями
— Subwatch появится в списке приложений любой запускалки. Если найден
Walker с Elephant, добавляется и меню Elephant.

## Горячие клавиши

```toml
[keybinds]
open_tui = "SUPER + CTRL + U"
upcoming = "SUPER + CTRL + ALT + U"
menu = "SUPER + CTRL + SHIFT + U"
rescan = ""                  # пусто — без клавиши
add = ""
override_conflicts = false
```

`subwatch keybinds apply` пишет `~/.config/hypr/subwatch.lua` и добавляет
в `hyprland.lua` подключение:

```lua
-- >>> subwatch >>>
if package.searchpath("hypr.subwatch", package.path) then require("hypr.subwatch") end
-- <<< subwatch <<<
```

Проверка `searchpath` нужна, чтобы удалённый файл не ломал конфиг. После
записи выполняются `hyprctl reload` и `hyprctl configerrors`.

Перед этим каждое сочетание сверяется с `hyprctl binds -j`. Занятое
пропускается с предупреждением (и попадает в `subwatch doctor`), а с
`override_conflicts = true` старый бинд снимается через `hl.unbind`, и в
файле остаётся комментарий, что там было раньше. Посмотреть заранее:
`subwatch keybinds show`, проверить: `subwatch keybinds check`.

Для старой схемы с `hyprland.conf` то же самое делается через
`subwatch.conf` и `source = ...`.

## Уведомления

В Omarchy 4 уведомления показывает `omarchy-shell`. Он поддерживает
действия формально, но кнопок не рисует, зато умеет выполнить команду по
клику. Поэтому напоминание Subwatch выглядит так: заголовок «Скоро
списание: Netflix», текст с датой и суммой, а клик открывает меню
«Оставить / Отменить подписку / Отложить на …».

С mako, dunst или swaync (`notify-send`) у уведомления будут настоящие
кнопки. Выбор делается автоматически по имени демона
(`notifications.backend = "auto"`).

## Таймеры

В `~/.config/systemd/user/`:

- `subwatch-scan.timer` → `subwatch scan` по `scan.schedule`, с
  `Nice` и `IOSchedulingClass` из `[scan]`, `Persistent=true` — пропущенный
  запуск выполнится после включения компьютера;
- `subwatch-remind.timer` → `subwatch remind` каждые
  `reminders.check_interval`.

Одновременно работает только одно сканирование (блокировка в
`$XDG_RUNTIME_DIR`), второй запуск сразу выходит с понятным сообщением.

```bash
systemctl --user list-timers 'subwatch-*'
subwatch logs -f
```

## Тема

TUI берёт цвета из `~/.local/state/omarchy/current/theme/colors.toml` и
сам перекрашивается, когда вы меняете тему Omarchy. Отдельные цвета можно
переопределить в `[ui.colors]`, а `ui.theme` позволяет выбрать любую
встроенную тему Textual (`nord`, `gruvbox`, `tokyo-night`…).

## После обновлений Omarchy

Обновления Omarchy правят пользовательские конфиги точечно и блоки
Subwatch не трогают. Но `omarchy refresh hyprland` или
`omarchy refresh shell` сбрасывают файлы целиком. На этот случай ставится
хук `~/.config/omarchy/hooks/post-update.d/subwatch`, который после
каждого `omarchy update` выполняет `subwatch integrate apply`. После
ручного `refresh` достаточно `subwatch doctor --fix`.

## TUI

| Клавиша | Действие |
|---|---|
| `j` / `k`, `g` / `G` | вниз, вверх, в начало, в конец |
| `Enter`, `e` | изменить подписку |
| `a` | добавить |
| `x` | отменить подписку (с открытием страницы отмены) |
| `d` | удалить |
| `u` | отметить использование |
| `/` | поиск по названию и тегам |
| `f` | фильтр по категории и статусу |
| `s` / `S` | сменить поле сортировки / порядок |
| `1`, `r`, `c` | вкладки: подписки, проверка, графики |
| `y` / `n` | подтвердить / отклонить находку на вкладке «Проверка» |
| `R` | сканировать (через таймер, если он установлен) |
| `,` | открыть config.toml |
| `?` | справка |
| `q` | выход |

Все клавиши меняются в `[ui.keys]`.
