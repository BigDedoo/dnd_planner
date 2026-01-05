#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

# Start Backend
echo "Starting Backend..."
source venv/bin/activate
# Using --host 127.0.0.1 to match the Next.js rewrite destination
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Start Frontend
echo "Starting Frontend..."
cd frontend
# Ensure we are using the production build
npm run start -- -p 3000 &
FRONTEND_PID=$!

# Trap SIGINT and SIGTERM to kill child processes
trap "kill $BACKEND_PID $FRONTEND_PID" SIGINT SIGTERM

# Wait for processes
wait
