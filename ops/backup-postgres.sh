#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
env_file="${POSTCODE_ENV_FILE:-${repo_dir}/.env.production}"
backup_dir="${POSTCODE_BACKUP_DIR:-/home/postcode/backups/postgres}"
retention_days="${POSTCODE_BACKUP_RETENTION_DAYS:-14}"

if [[ ! -f "${env_file}" ]]; then
    echo "Production environment file is missing: ${env_file}" >&2
    exit 1
fi
if [[ ! "${retention_days}" =~ ^[0-9]+$ ]] || (( retention_days < 2 || retention_days > 90 )); then
    echo "POSTCODE_BACKUP_RETENTION_DAYS must be between 2 and 90." >&2
    exit 1
fi

install -d -m 0700 -- "${backup_dir}"

database_bytes="$({
    docker compose --project-directory "${repo_dir}" --env-file "${env_file}" exec -T postgres \
        sh -ceu 'psql --tuples-only --no-align --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --command="SELECT pg_database_size(current_database())"'
} | tr -d '[:space:]')"
available_bytes="$(df --output=avail -B1 -- "${backup_dir}" | tail -n 1 | tr -d '[:space:]')"
if [[ ! "${database_bytes}" =~ ^[0-9]+$ ]] || [[ ! "${available_bytes}" =~ ^[0-9]+$ ]]; then
    echo "Unable to determine PostgreSQL size or backup filesystem capacity." >&2
    exit 1
fi
minimum_reserve_bytes=$((5 * 1024 * 1024 * 1024))
required_bytes=$((database_bytes * 3 + minimum_reserve_bytes))
if (( available_bytes < required_bytes )); then
    echo "Insufficient backup capacity: ${available_bytes} bytes available, ${required_bytes} required." >&2
    exit 1
fi

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
final_path="${backup_dir}/cafe_postcode_${timestamp}.dump"
temporary_path="$(mktemp --tmpdir="${backup_dir}" '.postgres-backup.XXXXXX')"
checksum_path="${final_path}.sha256"

cleanup() {
    rm -f -- "${temporary_path}"
}
trap cleanup EXIT

docker compose --project-directory "${repo_dir}" --env-file "${env_file}" exec -T postgres \
    sh -ceu 'pg_dump --format=custom --compress=6 --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
    > "${temporary_path}"

if [[ ! -s "${temporary_path}" ]]; then
    echo "PostgreSQL backup is empty." >&2
    exit 1
fi

docker compose --project-directory "${repo_dir}" --env-file "${env_file}" exec -T postgres \
    sh -ceu 'pg_restore --list - >/dev/null' < "${temporary_path}"

chmod 0600 -- "${temporary_path}"
mv -- "${temporary_path}" "${final_path}"
sha256sum -- "${final_path}" > "${checksum_path}"
chmod 0600 -- "${checksum_path}"

find "${backup_dir}" -maxdepth 1 -type f \
    \( -name 'cafe_postcode_*.dump' -o -name 'cafe_postcode_*.dump.sha256' \) \
    -mtime "+${retention_days}" -delete

echo "Verified PostgreSQL backup created: ${final_path}"
