#!/bin/sh
set -e

ASSETS_CONTAINER_PATH="/opt/remnashop/assets"
ASSETS_DEFAULT_PATH="/opt/remnashop/assets.default"

UVICORN_RELOAD_ARGS=""

echo "Starting asset initialization"

# --- First run: copy default banners if user banners dir is empty ---
USER_BANNERS="${ASSETS_CONTAINER_PATH}/banners"
if [ ! -d "$USER_BANNERS" ] || [ -z "$(ls -A "$USER_BANNERS" 2>/dev/null)" ]; then
    echo "No user banners found — copying defaults"
    cp -a "${ASSETS_DEFAULT_PATH}/banners/." "$USER_BANNERS/"
fi

# --- Bootstrap custom.ftl for each locale in assets.default ---
if [ -d "${ASSETS_DEFAULT_PATH}/translations" ]; then
    for locale_dir in "${ASSETS_DEFAULT_PATH}/translations"/*/; do
        locale=$(basename "$locale_dir")
        CUSTOM_FTL="${ASSETS_CONTAINER_PATH}/translations/${locale}/custom.ftl"
        if [ ! -f "$CUSTOM_FTL" ]; then
            mkdir -p "${ASSETS_CONTAINER_PATH}/translations/${locale}"
            # Copy the template custom.ftl from defaults (contains usage comments, no overrides)
            if [ -f "${ASSETS_DEFAULT_PATH}/translations/${locale}/custom.ftl" ]; then
                cp "${ASSETS_DEFAULT_PATH}/translations/${locale}/custom.ftl" "$CUSTOM_FTL"
                echo "Created custom.ftl for locale: ${locale}"
            else
                touch "$CUSTOM_FTL"
                echo "Created empty custom.ftl for locale: ${locale}"
            fi
        fi
    done
fi

echo "Asset initialization complete"


echo "Migrating database"

if ! alembic -c src/infrastructure/database/alembic.ini upgrade head; then
    echo "Database migration failed! Exiting container..."
    exit 1
fi

echo "Migrations deployed successfully"


if [ "$UVICORN_RELOAD_ENABLED" = "true" ]; then
    echo "Uvicorn will run with reload enabled"
    UVICORN_RELOAD_ARGS="--reload --reload-dir /opt/remnashop/src --reload-dir /opt/remnashop/assets --reload-include *.ftl"
else
    echo "Uvicorn will run without reload"
fi

exec uvicorn src.__main__:application --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-5000}" --factory --use-colors ${UVICORN_RELOAD_ARGS}