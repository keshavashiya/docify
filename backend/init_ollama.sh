#!/bin/bash
# Initialize Ollama models on startup

OLLAMA_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
MAX_RETRIES=30
RETRY_INTERVAL=2

echo "[INIT] Waiting for Ollama to be ready at $OLLAMA_URL..."

# Wait for Ollama to be ready
for i in $(seq 1 $MAX_RETRIES); do
    if curl -s "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
        echo "[INIT] ✓ Ollama is ready"
        break
    fi
    echo "[INIT] Attempt $i/$MAX_RETRIES - Ollama not ready yet, waiting..."
    sleep $RETRY_INTERVAL
    
    if [ $i -eq $MAX_RETRIES ]; then
        echo "[INIT] ✗ Ollama failed to start after ${MAX_RETRIES}s"
        exit 1
    fi
done

# Pull embedding model
echo "[INIT] Pulling nomic-embed-text model..."
curl -X POST "$OLLAMA_URL/api/pull" \
  -H "Content-Type: application/json" \
  -d '{"name":"nomic-embed-text","stream":false}' \
  -v 2>&1 | grep -E "status|error|< HTTP"

echo "[INIT] ✓ nomic-embed-text pull requested"

# Pull LLM model with timeout
echo "[INIT] Pulling mistral model (this may take 5-10 minutes)..."
timeout 600 curl -X POST "$OLLAMA_URL/api/pull" \
  -H "Content-Type: application/json" \
  -d '{"name":"mistral","stream":false}' \
  --max-time 600 \
  -v 2>&1 | grep -E "status|error|< HTTP"

if [ $? -eq 0 ] || [ $? -eq 124 ]; then
    echo "[INIT] ✓ mistral pull requested (may still be downloading)"
else
    echo "[INIT] ⚠ mistral pull failed"
fi

echo "[INIT] Ollama initialization complete"
