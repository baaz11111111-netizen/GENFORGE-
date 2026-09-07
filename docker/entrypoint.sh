#!/bin/sh
# GENFORGE startup — works on Hugging Face Spaces (Docker SDK) AND docker-compose.
# 1. If an HF Storage Bucket is attached (/data exists and is writable), the
#    runtime data dirs are moved there and symlinked back, so project data
#    survives Space restarts. On the free tier (no bucket) local dirs are used
#    and data is ephemeral by design — the Space says so, nothing is faked.
# 2. Ensures all runtime data directories exist.
# 3. Logs an honest environment report (startup_check.py; non-fatal).
# 4. Execs Streamlit on $PORT (HF default 7860; compose sets PORT=8501).
set -e
cd "$(dirname "$0")/.."

# -------------------------------------------------- persistent storage (HF)
if [ -d /data ] && [ -w /data ]; then
    echo "Persistent storage detected at /data — wiring project data there."
    for d in projects uploads outputs temp temp_inputs publishing_state; do
        if [ -L "$d" ]; then
            continue  # already wired
        fi
        mkdir -p "/data/$d"
        if [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
            cp -a "$d/." "/data/$d/" 2>/dev/null || true
            rm -rf "$d"
        fi
        rmdir "$d" 2>/dev/null || rm -rf "$d"
        ln -s "/data/$d" "$d"
    done
else
    mkdir -p projects uploads outputs temp temp_inputs publishing_state
fi

PORT_BIND="${PORT:-7860}"

echo "=== GENFORGE startup check ==="
python startup_check.py || echo "startup_check reported warnings (non-fatal)"

# --------------------------------------------- platform-appropriate flags
if [ -n "$SPACE_ID" ]; then
    # Hugging Face Spaces: served inside the huggingface.co iframe — the
    # standard no-proxy recipe. The public Space carries no credentials,
    # so disabling XSRF/CORS checks here is an accepted trade-off.
    echo "Hugging Face Space detected ($SPACE_ID) — serving on 0.0.0.0:$PORT_BIND"
    CORS_FLAGS="--server.enableCORS false --server.enableXsrfProtection false"
else
    # VPS/compose: XSRF stays ON and CORS is locked to the real origin.
    CORS_FLAGS="--server.enableCORS true --server.enableXsrfProtection true --server.corsAllowedOrigins ${GENFORGE_ALLOWED_ORIGIN:-https://app.example.com}"
fi

echo "=== Starting Streamlit on 0.0.0.0:$PORT_BIND ==="
exec streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PORT_BIND" \
    --server.headless true \
    $CORS_FLAGS \
    --server.maxUploadSize 256 \
    --browser.gatherUsageStats false
