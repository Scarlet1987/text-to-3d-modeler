#!/bin/bash
# Run the modeler GUI with self-update support.
# The server exits with code 42 when the user hits Update in the GUI.
# This wrapper pulls the latest code and restarts automatically.
cd "$(dirname "$0")"
while true; do
    git pull -q 2>/dev/null
    .venv/bin/python -m server.app
    code=$?
    if [ $code -ne 42 ]; then
        echo "server stopped (exit $code)"
        break
    fi
    echo "updating and restarting..."
    sleep 1
done
