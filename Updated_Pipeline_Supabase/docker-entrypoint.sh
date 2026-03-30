#!/bin/bash
# LUNA Docker Entrypoint Script
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

echo "Starting LUNA application on port ${PORT:-5000}..."
# Use python directly
exec python luna_app.py
