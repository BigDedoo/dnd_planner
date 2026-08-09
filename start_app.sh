#!/usr/bin/env bash

set -euo pipefail

# Navigate to the script's directory
cd "$(dirname "$0")"

# Start Backend
echo "Starting Backend..."
# Using --host 127.0.0.1 to match the Next.js rewrite destination
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Start Frontend
echo "Starting Frontend..."
cd frontend
# Ensure we are using the production build
npm run start -- -p 3000 &
FRONTEND_PID=$!

cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}

# Trap shutdown to stop both child processes.
trap cleanup EXIT INT TERM

# Stop both services if either one exits.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
