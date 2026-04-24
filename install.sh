#!/usr/bin/env bash
# ============================================================
#  install.sh — установка MCP-сервера 1С:Fresh
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "📦 Установка зависимостей..."
python3 -m pip install --user -r requirements.txt

if [ ! -f "$DIR/.env" ]; then
    echo
    echo "⚠️  Файл .env не найден — создаю из шаблона."
    cp "$DIR/.env.example" "$DIR/.env"
    echo "✋ Отредактируй $DIR/.env и запусти этот скрипт ещё раз."
    exit 0
fi

echo
echo "🔧 Проверка MCP SDK..."
python3 - <<'PY'
import importlib, sys
try:
    importlib.import_module("mcp.server.fastmcp")
    print("✅ mcp SDK установлен")
except ImportError as e:
    print(f"❌ mcp SDK не найден: {e}")
    sys.exit(1)
PY

echo
echo "🔌 Проверка подключения к 1С:Fresh..."
python3 - <<'PY'
from connector import Fresh1C
import config
config.assert_configured()
api = Fresh1C(config.BASE_URL, config.USERNAME, config.PASSWORD,
              verify_ssl=config.VERIFY_SSL, timeout=config.REQUEST_TIMEOUT)
orgs = api.get_organizations()
print(f"✅ Подключение ok. Организаций в базе: {len(orgs)}")
PY

echo
echo "🎉 ГОТОВО!"
echo
echo "Добавь в конфиг MCP-клиента (пример см. mcp-config.example.json),"
echo "заменив путь на:  $DIR/server.py"
echo
echo "Пути к конфигам:"
echo "  • Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "  • Claude Code:    ~/.claude/settings.json (секция mcpServers)"
