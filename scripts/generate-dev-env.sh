#!/bin/sh
# Create a .env for LOCAL development with fresh random secrets.
# Never reuse these values anywhere else, and never commit .env.
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ] && [ "${1:-}" != "--force" ]; then
  echo ".env already exists. Re-run with --force to overwrite it." >&2
  exit 1
fi
hex() { python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"; }
cat > .env <<ENV
APP_ENV=development
PAYMENT_MODE=simulation
LIVE_PAYMENTS_ENABLED=false
JWT_SECRET=$(hex 32)
YOGII_ENCRYPTION_KEY=$(hex 32)
YOGII_LOOKUP_HMAC_KEY=$(hex 32)
MOCK_PROVIDER_WEBHOOK_SECRET=$(hex 32)
POSTGRES_DB=yogii
POSTGRES_PASSWORD=$(hex 24)
YOGII_MIGRATOR_PASSWORD=$(hex 24)
YOGII_APP_PASSWORD=$(hex 24)
COOKIE_SECURE=false
CORS_ORIGINS=http://localhost:8080
ENV
chmod 600 .env
echo "Wrote .env with random local secrets (permissions 600)."
