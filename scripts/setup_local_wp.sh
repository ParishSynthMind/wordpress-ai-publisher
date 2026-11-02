#!/usr/bin/env bash
# One-time setup of the local WordPress started by docker-compose.yml.
# Installs WordPress, sets pretty permalinks, creates an editor-free admin for local testing
# and an Application Password, and writes the connection settings to .env.local (git-ignored).
set -euo pipefail
PROJECT=${COMPOSE_PROJECT_NAME:-wpai}
PORT=${WP_PORT:-8802}
URL="http://localhost:${PORT}"
ADMIN_USER=${WP_LOCAL_ADMIN:-localadmin}
ADMIN_PASS=${WP_LOCAL_ADMIN_PASSWORD:-$(openssl rand -hex 12)}
wp() { docker compose -p "$PROJECT" run --rm -T cli wp "$@"; }

for i in $(seq 1 30); do
  curl -fsS -o /dev/null "$URL/wp-login.php" 2>/dev/null && break || sleep 2
done

if ! wp core is-installed 2>/dev/null; then
  wp core install --url="$URL" --title="Local Test Blog" --admin_user="$ADMIN_USER" \
     --admin_password="$ADMIN_PASS" --admin_email="admin@example.com" --skip-email
  echo "WP_LOCAL_ADMIN_PASSWORD=$ADMIN_PASS" > .env.local.admin
fi
wp rewrite structure '/%postname%/' --hard >/dev/null
wp option update aipub_force_429 0 >/dev/null

APP_PASS=$(wp user application-password create "$ADMIN_USER" "wordpress-ai-publisher" --porcelain)
cat > .env.local <<ENV
WP_BASE_URL=$URL
WP_USERNAME=$ADMIN_USER
WP_APP_PASSWORD=$APP_PASS
ENV
echo "Local WordPress ready at $URL (settings in .env.local)"
