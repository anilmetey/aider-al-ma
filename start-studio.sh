#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

export STUDIO_PORT="${STUDIO_PORT:-8585}"
export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"

# Check if Ollama is running, start if needed
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama kapalı. Başlatılıyor..."
  open -a Ollama 2>/dev/null || ollama serve >/tmp/ollama.log 2>&1 &
  for i in {1..15}; do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
      break
    fi
    sleep 1
  done
fi

PYTHON_EXEC="/opt/homebrew/Cellar/aider/0.86.2/libexec/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
  PYTHON_EXEC="python3"
fi

echo "=========================================================="
echo "⚡ Antigravity Local Studio Başlatılıyor..."
echo "📍 Çalışma Alanı: $(pwd)"
echo "🌐 Arayüz: http://127.0.0.1:${STUDIO_PORT}"
echo "=========================================================="

# Automatically open in browser after 1 second in background
(sleep 1.2 && open "http://127.0.0.1:${STUDIO_PORT}") &

exec "$PYTHON_EXEC" studio/server.py
