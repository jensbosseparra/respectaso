# RespectASO — Development Commands
# Run from the project root: just <command>

# Default: show available commands
default:
    @just --list

# Start the Django backend (creates DB, runs migrations, starts server)
backend:
    #!/usr/bin/env bash
    set -euo pipefail

    # Ensure virtualenv deps are available
    if ! python3 -c "import django" 2>/dev/null; then
        echo "Installing dependencies..."
        pip install -r requirements.txt
    fi

    # Run migrations
    python3 manage.py migrate --run-syncdb 2>/dev/null || python3 manage.py migrate

    echo ""
    echo "============================================"
    echo "  RespectASO is running"
    echo "============================================"
    echo ""
    echo "  Open in browser:  http://localhost:8000"
    echo "  Admin panel:      http://localhost:8000/admin/"
    echo ""
    echo "  Press Ctrl+C to stop"
    echo "============================================"
    echo ""

    python3 manage.py runserver 0.0.0.0:8000
