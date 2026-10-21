# Окружение

Что я нашёл на машине, где писался Subwatch, и какие выводы из этого сделаны.
Снимок от 22 октября 2026.

## Система

| Что | Версия / значение |
|---|---|
| Omarchy | 4.0.6 (`/etc/os-release`, `BUILD_ID="4.0.6"`, пакет `omarchy 4.0.6-1`) |
| Ядро | 7.2.8-9-omarchy |
| Hyprland | 0.56.2, конфиг на **Lua** |
| Оболочка Omarchy | Quickshell 0.3.2 (`omarchy-shell`): панель, уведомления, меню |
| systemd | 262, есть `--user` менеджер и journald (`/run/systemd/journal/socket`) |
| uwsm | 0.27.1 |
| Терминал | xdg-terminal-exec → Ghostty |
| Shell | bash, есть bash-completion 2.18; zsh и fish не установлены |
| `$XDG_RUNTIME_DIR` | `/run/user/1000`, tmpfs |

## Где лежит Omarchy

В Omarchy 4 всё пакетное содержимое переехало из `~/.local/share/omarchy` в
`/usr/share/omarchy` (`$OMARCHY_PATH`). Каталог принадлежит пакету `omarchy` и
перезаписывается при `omarchy update`, поэтому Subwatch туда ничего не пишет.

```
/usr/share/omarchy/
  bin/        команды omarchy-*  (единая точка входа: omarchy <группа> <действие>)
  default/    дефолты: hypr/*.lua, omarchy/omarchy-menu.jsonc
  config/     шаблоны пользовательских конфигов
  shell/      исходники Quickshell-оболочки и встроенных плагинов
  themes/     стоковые темы
  migrations/ миграции, которые запускаются при обновлении
```

## Что изменилось по сравнению с ТЗ

ТЗ писалось под Omarchy 3.x (Waybar, Walker, mako, `hyprland.conf`). В 4.0.6
этих программ нет:

```
$ which waybar walker elephant makoctl
which: no waybar ... no walker ... no elephant ... no makoctl
```

Их заменила одна Quickshell-оболочка. Ниже соответствие.

### Панель (вместо Waybar)

Раскладка панели хранится в `~/.config/omarchy/shell.json` (ключ `bar.layout`),
файл перечитывается на лету. Панель поддерживает пользовательские модули
`"type": "command"`: команда печатает текст или JSON в формате Waybar
(`{"text", "tooltip", "class"}`), есть `interval`, `onClick`, `onRightClick`,
`onMiddleClick`. Класс `active` подсвечивает модуль цветом `bar.urgent` — этим и
сделана смена цвета при превышении бюджета.

Значит, один и тот же вывод `subwatch bar` работает и в Omarchy 4, и в Waybar.
Для Waybar оставлен отдельный сниппет (`contrib/waybar/`).

Проверено в исходниках: `/usr/share/omarchy/shell/plugins/bar/Bar.qml`,
компонент `CustomCommandModule`.

### Меню (вместо Walker/omarchy-menu на bash)

Меню — Quickshell-плагин `omarchy.menu`. Пользовательские пункты добавляются в
`~/.config/omarchy/extensions/omarchy-menu.jsonc`, файл тоже отслеживается на
лету. Идентификатор с точкой задаёт вложенность (`subwatch.upcoming` попадает в
подменю `subwatch`).

Ограничения, которые пришлось учесть:

- парсер (`MenuModel.stripJsonc`) убирает только комментарии **на отдельной
  строке** и висячие запятые; комментарий в конце строки ломает весь файл;
- `provider` (динамические строки) работает только для встроенных провайдеров
  (`apps`, `fonts`, `power-profiles`), своих добавить нельзя.

Поэтому динамические списки (ближайшие списания и т. п.) Subwatch показывает
через `omarchy-menu-select` — это штатный способ «выбрать один пункт из меню»,
которым пользуются и скрипты самой Omarchy.

### Уведомления (вместо mako)

Демон уведомлений — тоже `omarchy-shell` (`GetServerInformation` возвращает
`quickshell`). Возможности: `persistence body body-markup body-hyperlinks
actions icon-static`. Но кнопки действий карточка не рисует: по клику
вызывается только действие `default`. Зато есть собственный хинт
`omarchy-exec-argv` — команда, которая выполняется по клику (так работает
`omarchy-notification-send --exec`).

Решение: по клику на напоминание открывается меню выбора «Оставить / Отменить /
Отложить». На системах с mako/dunst используются настоящие кнопки
(`notify-send -A`). Подробнее в DECISIONS.md.

### Hyprland (Lua вместо hyprland.conf)

`~/.config/hypr/hyprland.lua` загружает дефолты Omarchy, затем пользовательские
модули через `require("hypr.bindings")` и т. д. `package.path` включает
`~/.config/?.lua`, так что `~/.config/hypr/subwatch.lua` подключается как
`require("hypr.subwatch")`. Директивы `source = ...` в Lua-конфиге нет.

Бинды: `o.bind("SUPER + CTRL + U", "Описание", "команда")`, перед переназначением
занятой клавиши нужен `hl.unbind(...)`. Занятые сочетания отдаёт
`hyprctl binds -j` (поле `modmask`: SHIFT=1, CTRL=4, ALT=8, SUPER=64).
Проверка конфига: `hyprctl reload` и `hyprctl configerrors`.

## Что безопасно трогать

| Путь | Чей | Перезаписывается обновлением? |
|---|---|---|
| `/usr/share/omarchy/**` | пакет | да, всегда. Не трогаем |
| `~/.config/hypr/hyprland.lua` | пользователь | нет; миграции иногда правят его точечно (awk), `omarchy refresh hyprland` сбрасывает с бэкапом |
| `~/.config/hypr/subwatch.lua` | Subwatch | нет, файл наш |
| `~/.config/omarchy/shell.json` | пользователь | нет; миграции правят отдельные ключи через jq, `omarchy refresh shell` сбрасывает |
| `~/.config/omarchy/extensions/omarchy-menu.jsonc` | пользователь | нет |
| `~/.config/omarchy/hooks/post-update.d/` | пользователь | нет |
| `~/.config/systemd/user/` | пользователь | нет |

Во все общие файлы Subwatch пишет только блок между маркерами
`>>> subwatch >>>` и `<<< subwatch <<<` (так же поступает, например, плагин
Altscape в `hyprland.lua`). Перед правкой делается бэкап, после — проверка
(JSON парсится, `hyprctl configerrors` пуст). Если после `omarchy refresh ...`
блок пропал, `subwatch doctor` это покажет, а хук `post-update.d/subwatch`
восстанавливает интеграцию после обновлений.

## Тема

Текущая тема: `~/.local/state/omarchy/current/theme/` (сейчас Vantablack),
цвета в `colors.toml`: `accent`, `background`, `foreground`, `red`, `yellow`,
`green` и т. д. TUI берёт цвета отсюда и перечитывает файл, если тема сменилась.
Хук `theme-set.d` для этого не нужен.

## Python и зависимости

| Что | Состояние |
|---|---|
| python | 3.14.8 (системный) |
| uv | не установлен; в репозитории `extra` есть `uv 0.13.1`. Для разработки скачан отдельный бинарь 0.13.4 |
| pip, pipx | нет |
| mise | есть (2026.10.15) |
| sudo | требует пароль |
| ollama | не установлен |
| keyring | gnome-keyring 51.1 запущен, `org.freedesktop.secrets` на шине; python-keyring выбирает `SecretService` |
| libsecret | 0.21.8, `secret-tool` есть |
| SQLCipher | не установлен |

Все зависимости из ТЗ ставятся через uv на Python 3.14 без сборки из исходников:
pydantic 2.14, typer 0.27 (click теперь вшит внутрь как `typer._click`),
textual 8.2, keyring 25.7, imapclient 4.1, google-api-python-client 2.201,
pdfplumber 0.11. LiteLLM тоже ставится, но тянет 60 пакетов и ~250 МБ — вынесен в
необязательную группу `[ai]`.

## Локаль и шрифты

- `LANG=ru_RU.UTF-8`, локаль `ru_RU.utf8` сгенерирована. Казахской (`kk_KZ`)
  нет, но она и не нужна: форматирование дат и чисел Subwatch делает сам, без
  `locale.setlocale`, чтобы результат не зависел от настроек системы.
- Кириллицу покрывают JetBrainsMono Nerd Font (он же даёт глифы для панели и
  меню), Liberation, Adwaita, iA Writer (`fc-list :lang=ru`). Символ тенге ₸
  есть в JetBrainsMono.

## Сеть

Доступ в интернет есть (PyPI, GitHub отвечают 200). Тесты при этом сеть не
используют: HTTP, IMAP, Gmail и LLM подменяются моками.
