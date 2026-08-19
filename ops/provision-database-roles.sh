#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
env_file="${POSTCODE_ENV_FILE:-${repo_dir}/.env.production}"

if [[ ! -f "${env_file}" ]]; then
    echo "Production environment file is missing: ${env_file}" >&2
    exit 1
fi

docker compose --project-directory "${repo_dir}" --env-file "${env_file}" \
    --profile operations run --rm db-role-provisioner
