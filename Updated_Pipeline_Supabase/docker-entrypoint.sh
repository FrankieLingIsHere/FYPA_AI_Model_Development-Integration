#!/bin/bash
# LUNA Docker Entrypoint Script
# Starts the Flask app

echo "Starting LUNA application on port ${PORT:-5000}..."
# Use python directly
exec python luna_app.py
