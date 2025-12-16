#!/bin/bash
# LUNA Supabase Edition - Startup Script
# ========================================
# 
# Quick start script for the LUNA PPE Safety Monitor with Supabase backend.
# 
# Usage:
#   ./start.sh

echo "=========================================="
echo "LUNA Supabase Edition - Starting..."
echo "=========================================="
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo ""
    echo "Please create .env file from .env.example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env with your Supabase credentials."
    exit 1
fi

# Check if venv exists
if [ ! -d venv ]; then
    echo "⚠️  Warning: Virtual environment not found."
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
    echo ""
    echo "Installing dependencies..."
    source venv/bin/activate
    pip install -r requirements.txt
    echo "✓ Dependencies installed"
else
    echo "✓ Virtual environment found"
    source venv/bin/activate
fi

echo ""
echo "Starting LUNA application..."
echo ""
echo "Once started, open your browser to:"
echo "  http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""
echo "=========================================="
echo ""

# Start the application
python luna_app.py
