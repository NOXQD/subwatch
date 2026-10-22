#!/usr/bin/env bash
# Установка Subwatch.
#
#   ./install.sh               поставить или обновить
#   ./install.sh --dry-run     показать, что будет сделано, ничего не меняя
#   ./install.sh --with-ai     вместе с LiteLLM (любой облачный провайдер)
#   ./install.sh --no-sudo     не ставить пакеты через pacman
#   ./install.sh --no-integration   только программа, без таймеров, панели и меню
#
# Скрипт можно запускать сколько угодно раз: всё, что уже сделано, он
# пропускает. Системные файлы Omarchy не трогаются — только ~/.config,
# ~/.local и пользовательские юниты systemd.

set -euo pipefail

DRY_RUN=0
WITH_AI=0
NO_SUDO=0
INTEGRATION=1
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --with-ai) WITH_AI=1 ;;
    --no-sudo) NO_SUDO=1 ;;
    --no-integration) INTEGRATION=0 ;;
    -h|--help)
      sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Неизвестный параметр: $arg (справка: ./install.sh --help)" >&2
      exit 2
      ;;
  esac
done

bold=$'\e[1m'; green=$'\e[32m'; yellow=$'\e[33m'; red=$'\e[31m'; dim=$'\e[2m'; reset=$'\e[0m'
[[ -t 1 ]] || { bold=""; green=""; yellow=""; red=""; dim=""; reset=""; }

step() { echo "${bold}==>${reset} $*"; }
ok()   { echo "  ${green}✓${reset} $*"; }
warn() { echo "  ${yellow}!${reset} $*"; }
die()  { echo "  ${red}✗${reset} $*" >&2; exit 1; }

run() {
  if (( DRY_RUN )); then
    echo "  ${dim}[dry-run]${reset} $*"
  else
    "$@"
  fi
}

BIN_DIR="${UV_TOOL_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
export PATH="$BIN_DIR:$HOME/.local/bin:$PATH"

(( DRY_RUN )) && echo "${yellow}Режим проверки: ничего не будет изменено.${reset}"

# ----------------------------------------------------------------- python
step "Python"
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  fi
done
if [[ -n $PYTHON ]]; then
  ok "$("$PYTHON" --version) ($PYTHON)"
else
  warn "Python 3.12+ не найден — uv скачает подходящую версию сам"
fi

# --------------------------------------------------------------------- uv
step "uv"
if command -v uv >/dev/null 2>&1; then
  ok "$(uv --version)"
else
  if (( ! NO_SUDO )) && command -v pacman >/dev/null 2>&1 && [[ -t 0 ]]; then
    echo "  uv не установлен, ставлю из репозитория Arch (понадобится пароль sudo)"
    if command -v omarchy >/dev/null 2>&1; then
      run omarchy pkg add uv
    else
      run sudo pacman -S --needed --noconfirm uv
    fi
  fi
  if ! command -v uv >/dev/null 2>&1 && (( ! DRY_RUN )); then
    echo "  ставлю uv официальным установщиком в $BIN_DIR"
    command -v curl >/dev/null 2>&1 || die "Нужен curl или uv. Установите uv: sudo pacman -S uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$BIN_DIR" sh >/dev/null
  fi
  if (( DRY_RUN )); then
    echo "  ${dim}[dry-run]${reset} установить uv"
  else
    command -v uv >/dev/null 2>&1 || die "uv так и не появился в PATH"
    ok "$(uv --version)"
  fi
fi

# ---------------------------------------------------- секреты и уведомления
step "Окружение рабочего стола"
if command -v gnome-keyring-daemon >/dev/null 2>&1 || command -v kwalletd6 >/dev/null 2>&1 || command -v kwalletd5 >/dev/null 2>&1; then
  ok "есть хранилище секретов (keyring)"
else
  warn "не найден gnome-keyring или KWallet — токены почты негде хранить; поставьте: omarchy pkg add gnome-keyring"
fi
if command -v omarchy-notification-send >/dev/null 2>&1; then
  ok "уведомления Omarchy"
elif command -v notify-send >/dev/null 2>&1; then
  ok "notify-send"
else
  warn "нет notify-send — напоминания не будут видны; поставьте libnotify"
fi
if command -v fc-list >/dev/null 2>&1 && [[ -z "$(fc-list :lang=ru family 2>/dev/null)" ]]; then
  warn "не найдено шрифтов с кириллицей"
fi

# --------------------------------------------------------------- subwatch
step "Subwatch"
SPEC="$SRC_DIR"
(( WITH_AI )) && SPEC="$SRC_DIR[ai]"
PY_ARGS=()
[[ -n $PYTHON ]] && PY_ARGS=(--python "$PYTHON")
run uv tool install --force --quiet "${PY_ARGS[@]}" "$SPEC"
if (( ! DRY_RUN )); then
  command -v subwatch >/dev/null 2>&1 || die "subwatch не найден после установки. Проверьте, что $BIN_DIR есть в PATH"
  ok "$(subwatch version) → $(command -v subwatch)"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR нет в PATH вашей оболочки — добавьте его в ~/.bashrc" ;;
  esac
fi

# ------------------------------------------------------------------ config
step "Конфигурация"
if (( DRY_RUN )); then
  cfg="${SUBWATCH_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/subwatch/config.toml}"
  if [[ -f $cfg ]]; then ok "уже есть: $cfg"; else echo "  ${dim}[dry-run]${reset} создать $cfg с комментариями"; fi
else
  subwatch config init
  subwatch config check >/dev/null && ok "конфигурация в порядке"
fi

# -------------------------------------------------------------- integration
if (( INTEGRATION )); then
  step "Интеграция: таймеры, панель, меню, клавиши, ярлык, автодополнение"
  if (( DRY_RUN )); then
    if command -v subwatch >/dev/null 2>&1; then
      subwatch integrate apply --dry-run
    else
      echo "  ${dim}[dry-run]${reset} subwatch integrate apply"
    fi
  else
    subwatch integrate apply || warn "часть интеграции не удалась — см. subwatch doctor"
  fi
fi

# ------------------------------------------------------------------ doctor
if (( ! DRY_RUN )); then
  step "Проверка"
  subwatch doctor || true
fi

cat <<EOF

${bold}Готово.${reset} Дальше:
  subwatch auth gmail          подключить Gmail (мастер всё объяснит)
  subwatch auth imap --name yandex --host imap.yandex.ru --user me@yandex.ru
  subwatch import выписка.csv  или импортировать выписку
  subwatch scan                найти подписки
  subwatch                     открыть TUI (или SUPER + CTRL + U)

Настройки: ~/.config/subwatch/config.toml · удалить: ./uninstall.sh
EOF
