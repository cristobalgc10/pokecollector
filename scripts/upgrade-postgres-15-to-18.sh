#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE=(docker compose)
DB_SERVICE="${POSTGRES_SERVICE:-postgres}"
DB_USER="${POSTGRES_USER:-pokemon}"
DB_NAME="${POSTGRES_DB:-pokemon_tcg}"
TARGET_MAJOR="18"
BACKUP_DIR="${POSTGRES_UPGRADE_BACKUP_DIR:-${REPO_ROOT}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_PATH="${BACKUP_DIR}/postgres15_to_18_${TIMESTAMP}.sql"
rollback_volume=""
upgrade_completed="false"

log() {
  printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local line_no="${1:-unknown}"
  if [[ "${upgrade_completed}" == "true" ]]; then
    return
  fi

  cat >&2 <<EOF

ERROR: PostgreSQL upgrade failed near line ${line_no}.

Recovery notes:
  * SQL dump path: ${DUMP_PATH}
  * Rollback volume: ${rollback_volume:-not created yet}
  * If only the app services were stopped and the old PostgreSQL volume is still present, you can usually run 'docker compose up -d' to return to the previous state.
  * If the old volume was already removed, restore the previous app version/compose file, remove the new PostgreSQL volume if it exists, and copy the rollback volume back to the original volume name.

Keep any dump and rollback volume until you have verified the application.
EOF
}

trap 'on_error ${LINENO}' ERR

if ! command -v docker >/dev/null 2>&1; then
  fail "docker is required"
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "docker compose is required"
fi

mkdir -p "${BACKUP_DIR}"

log "Checking running PostgreSQL container"
container_id="$(${COMPOSE[@]} ps -q "${DB_SERVICE}")"
if [[ -z "${container_id}" ]]; then
  fail "${DB_SERVICE} is not running. Start the existing PostgreSQL 15 stack before running this upgrade script."
fi

if ! docker inspect "${container_id}" >/dev/null 2>&1; then
  fail "Could not inspect ${DB_SERVICE} container"
fi

source_major="$(${COMPOSE[@]} exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -Atc "SHOW server_version_num;" | tr -d '[:space:]' | cut -c1-2)"
if [[ -z "${source_major}" ]]; then
  fail "Could not detect PostgreSQL server version"
fi

if [[ "${source_major}" == "${TARGET_MAJOR}" ]]; then
  log "PostgreSQL is already ${TARGET_MAJOR}. No major-version upgrade is needed."
  exit 0
fi

if [[ "${source_major}" != "15" && "${ALLOW_NON_15_SOURCE:-false}" != "true" ]]; then
  fail "Detected PostgreSQL major version ${source_major}, expected 15. Set ALLOW_NON_15_SOURCE=true if you intentionally want to dump/restore this version into PostgreSQL ${TARGET_MAJOR}."
fi

volume_name="$(docker inspect "${container_id}" --format '{{ range .Mounts }}{{ if or (eq .Destination "/var/lib/postgresql/data") (eq .Destination "/var/lib/postgresql") }}{{ .Name }}{{ end }}{{ end }}')"
if [[ -z "${volume_name}" ]]; then
  fail "Could not find the Docker volume mounted at /var/lib/postgresql/data or /var/lib/postgresql"
fi

rollback_volume="${volume_name}_pg${source_major}_backup_${TIMESTAMP}"

cat <<EOF

This will upgrade the Docker-managed PostgreSQL data volume from major ${source_major} to ${TARGET_MAJOR} by dump/restore.

It will:
  1. Stop app services while keeping PostgreSQL ${source_major} running
  2. Create SQL dump: ${DUMP_PATH}
  3. Stop the compose stack
  4. Copy the old data volume to rollback volume: ${rollback_volume}
  5. Remove the original old data volume so PostgreSQL ${TARGET_MAJOR} can initialize a fresh one
  6. Start PostgreSQL ${TARGET_MAJOR} with the Docker volume mounted at /var/lib/postgresql
  7. Restore the SQL dump
  8. Rebuild/start the full stack

The old data is preserved in the rollback volume until you delete it manually.
EOF

if [[ "${POSTGRES_UPGRADE_ASSUME_YES:-false}" != "true" ]]; then
  read -r -p "Continue? Type 'upgrade to postgres 18' to proceed: " confirmation
  if [[ "${confirmation}" != "upgrade to postgres 18" ]]; then
    fail "Upgrade cancelled"
  fi
fi

mapfile -t app_services < <("${COMPOSE[@]}" config --services | grep -v -x "${DB_SERVICE}" || true)
if (( ${#app_services[@]} > 0 )); then
  log "Stopping app services before the dump to prevent writes during the upgrade"
  "${COMPOSE[@]}" stop "${app_services[@]}"
fi

log "Creating SQL dump from PostgreSQL ${source_major}"
"${COMPOSE[@]}" exec -T "${DB_SERVICE}" pg_dump \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --clean \
  --if-exists \
  > "${DUMP_PATH}"

if [[ ! -s "${DUMP_PATH}" ]]; then
  fail "SQL dump was not created or is empty: ${DUMP_PATH}"
fi

log "Stopping compose stack"
"${COMPOSE[@]}" down

log "Copying old PostgreSQL ${source_major} volume for rollback"
docker volume create "${rollback_volume}" >/dev/null
docker run --rm \
  -v "${volume_name}:/from:ro" \
  -v "${rollback_volume}:/to" \
  alpine:3.22 \
  sh -c 'cd /from && tar cf - . | tar xf - -C /to'

log "Removing old PostgreSQL ${source_major} volume ${volume_name}"
docker volume rm "${volume_name}" >/dev/null

log "Starting PostgreSQL ${TARGET_MAJOR} with a fresh data volume"
"${COMPOSE[@]}" up -d "${DB_SERVICE}"

log "Waiting for PostgreSQL ${TARGET_MAJOR} to become ready"
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T "${DB_SERVICE}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! "${COMPOSE[@]}" exec -T "${DB_SERVICE}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
  fail "PostgreSQL ${TARGET_MAJOR} did not become ready"
fi

actual_major="$(${COMPOSE[@]} exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -Atc "SHOW server_version_num;" | tr -d '[:space:]' | cut -c1-2)"
if [[ "${actual_major}" != "${TARGET_MAJOR}" ]]; then
  fail "Expected PostgreSQL ${TARGET_MAJOR}, got major version ${actual_major}"
fi

log "Restoring SQL dump into PostgreSQL ${TARGET_MAJOR}"
"${COMPOSE[@]}" exec -T "${DB_SERVICE}" psql \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  -v ON_ERROR_STOP=1 \
  < "${DUMP_PATH}"

log "Rebuilding and starting the full stack"
"${COMPOSE[@]}" up -d --build

log "Verifying restored database"
"${COMPOSE[@]}" exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -Atc "SELECT 'postgres_' || current_setting('server_version'), count(*) FROM information_schema.tables WHERE table_schema = 'public';"

cat <<EOF

PostgreSQL ${TARGET_MAJOR} upgrade completed.

SQL dump:        ${DUMP_PATH}
Rollback volume: ${rollback_volume}

Keep both until you have verified the application. If you need to roll back, stop the stack, restore the old compose/version, remove the new ${volume_name} volume, and copy ${rollback_volume} back to ${volume_name}.
EOF

upgrade_completed="true"
