#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
nginx_config="${POSTCODE_NGINX_CONFIG:-${repo_dir}/nginx/cafe-postcode.uz.conf}"
cloudflare_base_url="${CLOUDFLARE_IPS_BASE_URL:-https://www.cloudflare.com}"

if [[ ! -f "${nginx_config}" ]]; then
    echo "Nginx origin configuration is missing: ${nginx_config}" >&2
    exit 1
fi
if [[ "${cloudflare_base_url}" != https://* ]]; then
    echo "CLOUDFLARE_IPS_BASE_URL must use HTTPS." >&2
    exit 1
fi

temp_dir="$(mktemp -d)"
cleanup() {
    rm -rf -- "${temp_dir}"
}
trap cleanup EXIT

curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "${cloudflare_base_url%/}/ips-v4" > "${temp_dir}/official-v4"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "${cloudflare_base_url%/}/ips-v6" > "${temp_dir}/official-v6"

tr -d '\r' < "${temp_dir}/official-v4" | sed '/^[[:space:]]*$/d' > "${temp_dir}/official-v4.clean"
tr -d '\r' < "${temp_dir}/official-v6" | sed '/^[[:space:]]*$/d' > "${temp_dir}/official-v6.clean"
if grep -Ev '^[0-9A-Fa-f:.]+/[0-9]{1,3}$' "${temp_dir}/official-v4.clean" "${temp_dir}/official-v6.clean"; then
    echo "Cloudflare returned an invalid CIDR list." >&2
    exit 1
fi
if [[ ! -s "${temp_dir}/official-v4.clean" || ! -s "${temp_dir}/official-v6.clean" ]]; then
    echo "Cloudflare returned an empty CIDR list." >&2
    exit 1
fi

{
    cat "${temp_dir}/official-v4.clean"
    printf '\n'
    cat "${temp_dir}/official-v6.clean"
    printf '\n'
} | sed '/^[[:space:]]*$/d' | sort -u > "${temp_dir}/official"
awk '
    $1 == "geo" && $2 == "$realip_remote_addr" { in_geo = 1; next }
    in_geo && $1 == "}" { in_geo = 0 }
    in_geo && $2 == "1;" { print $1 }
' "${nginx_config}" | sort -u > "${temp_dir}/geo"
awk '
    $1 == "set_real_ip_from" {
        gsub(/;/, "", $2)
        print $2
    }
' "${nginx_config}" | sort -u > "${temp_dir}/real-ip"

if ! diff -u "${temp_dir}/official" "${temp_dir}/geo"; then
    echo "Nginx Cloudflare geo allowlist is stale or incomplete." >&2
    exit 1
fi
if ! diff -u "${temp_dir}/official" "${temp_dir}/real-ip"; then
    echo "Nginx set_real_ip_from allowlist is stale or incomplete." >&2
    exit 1
fi

echo "Cloudflare origin allowlists match the current official IPv4/IPv6 ranges."
