#!/usr/bin/env bash
# Deploys a commit on the server: fetch, back up, build images here, restart, wait for health.
# Run from GitHub Actions over SSH (.github/workflows/ci.yml), or by hand on the server:
#   bash infra/deploy.sh                 # latest origin/main
#   bash infra/deploy.sh <commit sha>
# Also works as an SSH forced command; the sha then comes from SSH_ORIGINAL_COMMAND.
set -euo pipefail

cd "$(dirname "$0")/.."
ref="${1:-${SSH_ORIGINAL_COMMAND:-}}"
ref="${ref:-origin/main}"
if [[ "${ref}" != origin/main && ! "${ref}" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "deploy: invalid ref '${ref}'" >&2
  exit 2
fi

compose() { docker compose -f infra/docker-compose.yml --env-file .env "$@"; }

if [[ -z "${ERP_DEPLOY_REEXEC:-}" ]]; then
  # One deploy at a time; the lock is held across the exec below.
  exec 9> /tmp/erp-deploy.lock
  flock -n 9 || { echo "deploy: another deploy is running" >&2; exit 1; }

  [[ -f .env ]] || { echo "deploy: .env missing (cp .env.example .env)" >&2; exit 1; }
  # The server checkout is deploy-only: tracked files are reset, .env and volumes are untouched.
  git fetch --prune origin main
  git reset --hard "${ref}"
  # Re-run with the version of this script from the commit being deployed.
  ERP_DEPLOY_REEXEC=1 exec bash infra/deploy.sh "${ref}"
fi

echo "deploy: $(git log -1 --format='%h %s')"

# Build first: if it fails, the running containers are left as they are.
compose build --pull

if [[ -n "$(compose ps -q --status running backup)" ]]; then
  echo "deploy: backup before upgrade"
  compose exec -T backup sh /backup.sh
fi

if ! compose up -d --remove-orphans; then
  echo "deploy: start failed; migrate log:" >&2
  compose logs --tail 50 migrate >&2
  exit 1
fi

# `up` does not recreate Caddy when only the mounted Caddyfile changed, and a running container
# keeps the old file after git replaces it. Recreate Caddy when its config differs from the checkout.
if ! compose exec -T caddy cat /etc/caddy/Caddyfile 2> /dev/null | cmp -s - infra/Caddyfile; then
  echo "deploy: Caddyfile changed, recreating caddy"
  compose up -d --force-recreate caddy
fi

echo "deploy: waiting for the API to become healthy"
for _ in $(seq 1 60); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q api)" 2> /dev/null || echo starting)
  [[ "${status}" == healthy ]] && break
  sleep 5
done
if [[ "${status}" != healthy ]]; then
  echo "deploy: API not healthy (${status})" >&2
  compose logs --tail 80 migrate api >&2
  exit 1
fi
for service in web worker caddy; do
  if [[ -z "$(compose ps -q --status running "${service}")" ]]; then
    echo "deploy: ${service} is not running" >&2
    compose logs --tail 50 "${service}" >&2
    exit 1
  fi
done

# Images are rebuilt on every deploy; keep the disk from filling up.
docker image prune -f > /dev/null
docker builder prune -f --filter until=168h > /dev/null

compose ps
echo "deploy: ok $(git rev-parse --short HEAD)"
