#!/usr/bin/env bash
# Удаление Subwatch.
#
#   ./uninstall.sh             убрать программу и интеграцию, данные оставить
#   ./uninstall.sh --purge     заодно удалить базу, кэш и токены в keyring
#   ./uninstall.sh --purge-all то же и конфигурацию ~/.config/subwatch
#   ./uninstall.sh --dry-run   показать, что будет сделано
#
# Из общих файлов (hyprland.lua, shell.json, omarchy-menu.jsonc) убираются
# только блоки Subwatch, всё остальное остаётся как было.

set -euo pipefail

DRY_RUN=0
PURGE=0
PURGE_ALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --purge) PURGE=1 ;;
    --purge-all) PURGE=1; PURGE_ALL=1 ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Неизвестный параметр: $arg (справка: ./uninstall.sh --help)" >&2
      exit 2
      ;;
  esac
done

bold=$'\e[1m'; green=$'\e[32m'; yellow=$'\e[33m'; dim=$'\e[2m'; reset=$'\e[0m'
[[ -t 1 ]] || { bold=""; green=""; yellow=""; dim=""; reset=""; }

step() { echo "${bold}==>${reset} $*"; }
ok()   { echo "  ${green}✓${reset} $*"; }

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

if command -v subwatch >/dev/null 2>&1; then
  step "Интеграция"
  if (( DRY_RUN )); then
    subwatch integrate remove --dry-run
  else
    subwatch integrate remove
  fi
  if (( PURGE )); then
    step "Данные и токены"
    if (( PURGE_ALL )); then
      run subwatch purge --yes --all
    else
      run subwatch purge --yes
    fi
  fi
else
  ok "subwatch не установлен — интеграцию убирать нечего"
fi

step "Программа"
if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^subwatch '; then
  run uv tool uninstall subwatch
  ok "subwatch удалён"
else
  ok "subwatch уже удалён"
fi

if (( ! PURGE )); then
  echo
  echo "Данные остались в ~/.local/share/subwatch, настройки — в ~/.config/subwatch."
  echo "Удалить и их: ./uninstall.sh --purge (или --purge-all вместе с настройками)."
fi
