#!/bin/sh
# Entrypoint script for xray-agent
# Determines whether to use reload (development) or workers (production)

if [ "$ENVIRONMENT" = "production" ] || [ "$ENVIRONMENT" = "prod" ]; then
    echo "🚀 Starting in PRODUCTION mode with single worker..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
else
    echo "🔧 Starting in DEVELOPMENT mode with reload..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
fi
