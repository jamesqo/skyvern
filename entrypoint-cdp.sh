#!/bin/sh

set -eu

alembic upgrade head
alembic check

SKYVERN_CREDENTIALS_FILE="${SKYVERN_CREDENTIALS_FILE:-/app/.skyvern/credentials.toml}"
export SKYVERN_CREDENTIALS_FILE
mkdir -p "$(dirname "$SKYVERN_CREDENTIALS_FILE")"

if [ ! -f "$SKYVERN_CREDENTIALS_FILE" ]; then
    org_output="$(python scripts/create_organization.py Skyvern-Open-Source)"
    api_token="$(printf '%s\n' "$org_output" | awk '/token=/{gsub(/.*token='\''|'\''.*/, ""); print}')"
    printf '%s\n' \
        '[skyvern]' \
        'configs = [' \
        "    {\"env\" = \"local\", \"host\" = \"http://skyvern:8000/api/v1\", \"orgs\" = [{name=\"Skyvern\", cred=\"$api_token\"}]}" \
        ']' > "$SKYVERN_CREDENTIALS_FILE"
fi

exec python -m skyvern.forge
