#!/bin/bash
# CASM Docker Entrypoint Script
# Starts the Flask app

set -e

is_truthy() {
	case "${1:-}" in
		1|true|TRUE|yes|YES|on|ON) return 0 ;;
		*) return 1 ;;
	esac
}

# Railway and other free-tier hosts should not depend on local Ollama model files.
# This keeps runtime resilient while avoiding accidental large model pulls.
if [ -n "${RAILWAY_PROJECT_ID:-}" ] || [ -n "${RAILWAY_ENVIRONMENT:-}" ] || is_truthy "${HOSTED_ENVIRONMENT:-}"; then
	if ! is_truthy "${ALLOW_LOCAL_OLLAMA_IN_CONTAINER:-false}"; then
		export DISABLE_OLLAMA_EMBEDDINGS=true
		if [ -z "${EMBEDDING_API_URL:-}" ]; then
			export EMBEDDING_PROVIDER_ORDER=model_api
		fi
		echo "Railway/hosted mode detected: local Ollama embeddings disabled to avoid model-size/runtime issues."
	fi
fi

echo "Starting CASM application on port ${PORT:-5000}..."
# Use gunicorn for production-grade request handling.
# --workers 1: single process so background threads (startup, queue worker, heartbeat)
#   are shared and not duplicated across processes.
# --threads 16: allows 16 concurrent in-flight requests without blocking (replaces
#   werkzeug's per-connection thread-per-request which accumulates unboundedly).
# --timeout 180: covers the 120s YOLO warmup + pipeline init with margin so gunicorn
#   does not kill a worker that is still in the middle of startup.
# --worker-tmp-dir /dev/shm: use tmpfs for heartbeat file to avoid disk I/O stalls.
# --worker-class gthread: thread-based worker matching the --threads setting.
# --bind: respect Railway's dynamic PORT env var.
exec gunicorn \
    --workers 1 \
    --worker-class gthread \
    --threads 16 \
    --timeout 180 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --worker-tmp-dir /dev/shm \
    --bind "0.0.0.0:${PORT:-5000}" \
    --access-logfile - \
    --error-logfile - \
    "casm_app:app"
