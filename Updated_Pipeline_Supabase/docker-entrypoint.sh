#!/bin/bash
# LUNA Docker Entrypoint Script
# Starts Ollama in the background, pulls necessary models safely, and starts the Flask app

echo "Starting Ollama service..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama to initialize..."
while ! curl -s http://localhost:11434/api/tags > /dev/null; do
    sleep 2
done

echo "Ollama is ready."

echo "Starting LUNA application on port ${PORT:-5000}..."
# Use python directly
exec python luna_app.py
