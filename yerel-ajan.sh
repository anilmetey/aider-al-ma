#!/bin/zsh
set -euo pipefail

export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama kapalı. Başlatılıyor..."
  open -a Ollama 2>/dev/null || ollama serve >/tmp/ollama.log 2>&1 &
  for i in {1..30}; do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
      break
    fi
    sleep 1
  done
fi

exec aider --model ollama/qwen2.5-coder:3b --yes-always "$@"
