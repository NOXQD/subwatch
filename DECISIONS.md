# Решения

Журнал решений, которые пришлось принимать по ходу. Формат простой: что решил и
почему. Новые записи — внизу.

## 1. Интеграция под Omarchy 4, а не 3.x

В ТЗ упомянуты Waybar, Walker, mako и `~/.config/hypr/subwatch.conf` через
`source`. На целевой системе Omarchy 4.0.6, где всё это заменено одной
Quickshell-оболочкой, а Hyprland настраивается на Lua (детали в
docs/ENVIRONMENT.md). Делать интеграцию под отсутствующие программы
бессмысленно, поэтому:

- **Панель.** `subwatch bar` печатает JSON в формате Waybar. Его понимают и
  модуль `type: command` панели Omarchy, и `custom/*` в Waybar. Установщик
  добавляет модуль в `~/.config/omarchy/shell.json`; если найден Waybar —
  предлагает сниппет из `contrib/waybar/` (и умеет вставить его сам с бэкапом).
- **Меню.** Пункты добавляются в `~/.config/omarchy/extensions/omarchy-menu.jsonc`.
  Если в системе есть Walker (Omarchy 3.x), дополнительно кладётся меню
  Elephant в `~/.config/elephant/menus/`. На этой машине Walker нет, поэтому
  вариант для Elephant проверен только на уровне генерации файла.
- **Hyprland.** Бинды пишутся в `~/.config/hypr/subwatch.lua`, а в
  `hyprland.lua` добавляется блок с `require("hypr.subwatch")` под проверкой
  `package.searchpath`, чтобы удаление файла не ломало конфиг. Для старого
  `hyprland.conf` поддержан вариант с `subwatch.conf` и `source = ...`.
- **Уведомления.** См. п. 2.

## 2. Действия в уведомлениях

Демон Omarchy поддерживает `actions` формально, но кнопок не рисует и по клику
вызывает только `default`. Зато у него есть хинт `omarchy-exec-argv`. Поэтому:

- бэкенд `omarchy`: уведомление через `omarchy-notification-send --exec`, клик
  открывает `subwatch notify-action <id>` — меню из трёх пунктов (Оставить /
  Отменить / Отложить) через `omarchy-menu-select`;
- бэкенд `notify-send` (mako, dunst, swaync): обычные кнопки `-A keep=...`,
  отдельный фоновый процесс ждёт ответа;
- `auto` выбирает по `GetServerInformation`.

## 3. LiteLLM — необязательная зависимость

LiteLLM ставится на Python 3.14, но тянет ~60 пакетов и ~250 МБ (tokenizers,
tiktoken, aiohttp, openai, jinja2...). Для программы, которая хранит токены от
почты, такая поверхность атаки по умолчанию не оправдана, тем более что AI-слой
выключен по умолчанию. Решение:

- LiteLLM в группе `[ai]` (`uv tool install 'subwatch[ai]'` или
  `./install.sh --with-ai`);
- без него работают встроенные клиенты на `urllib`: Ollama (`/api/chat`) и любой
  OpenAI-совместимый API (OpenAI, OpenRouter, Groq, LM Studio, vLLM...);
- если LiteLLM установлен и провайдер не из этих двух, используется он.

## 4. Шифрование базы без SQLCipher

SQLCipher в системе нет, а `sqlcipher3` пришлось бы собирать. Вместо этого
опция `storage.encrypt`: на диске лежит `subwatch.db.enc` (AES-256-GCM, ключ в
keyring), рабочая копия расшифровывается в `$XDG_RUNTIME_DIR/subwatch/` (tmpfs,
права 600, исчезает при выходе из сессии) и зашифровывается обратно после
записи. Доступ к файлам синхронизирован через `flock`.

## 5. uv на чистой системе

uv в Omarchy не предустановлен. `install.sh` пробует по очереди: уже
установленный uv → `sudo pacman -S --needed uv` (если есть терминал) →
официальный standalone-установщик в `~/.local/bin` (без правки rc-файлов).
Сам Subwatch ставится через `uv tool install`, в изолированное окружение.
