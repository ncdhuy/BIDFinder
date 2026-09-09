#!/usr/bin/env bash
set -Eeuo pipefail

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/bidfinder"
ingress_env="$config_dir/ingress.env"
config_file="${CLOUDFLARED_CONFIG:-$config_dir/cloudflared.yml}"
public_url="${BIDFINDER_PUBLIC_URL:-}"

if [[ -f "$ingress_env" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$ingress_env"
  set +a
  config_file="${CLOUDFLARED_CONFIG:-$config_dir/cloudflared.yml}"
  public_url="${BIDFINDER_PUBLIC_URL:-}"
fi

die() {
  echo "ingress: $*" >&2
  exit 2
}

cloudflared_bin="${CLOUDFLARED_BIN:-}"
if [[ -z "$cloudflared_bin" ]]; then
  cloudflared_bin="$(command -v cloudflared || true)"
fi

validate() {
  local public_host
  [[ "$public_url" =~ ^https://[^/[:space:]]+$ ]] || die "BIDFINDER_PUBLIC_URL must be an HTTPS origin"
  [[ -f "$config_file" ]] || die "missing Cloudflare config: $config_file"
  [[ -n "$cloudflared_bin" && -x "$cloudflared_bin" ]] || die "cloudflared binary not found; set CLOUDFLARED_BIN in $ingress_env"
  public_host="${public_url#https://}"
  grep -Eq '^[[:space:]]*tunnel:' "$config_file" || die "Cloudflare config must define a tunnel UUID"
  grep -Eq '^[[:space:]]*credentials-file:' "$config_file" || die "Cloudflare config must use an external credentials-file"
  grep -Fq "hostname: $public_host" "$config_file" || die "Cloudflare config hostname must match BIDFINDER_PUBLIC_URL"
  grep -Eq '^[[:space:]]*path:.*ready' "$config_file" || die "Cloudflare config must deny /ready publicly"
  grep -Eq '^[[:space:]]*path:.*api/warmup' "$config_file" || die "Cloudflare config must deny /api/warmup publicly"
  grep -Eq '^[[:space:]]*path:.*openapi' "$config_file" || die "Cloudflare config must deny API schema publicly"
  grep -Eq 'http://127\.0\.0\.1:8001([/[:space:]]|$)' "$config_file" || die "Cloudflare config must target FastAPI loopback 8001"
  grep -Eq '^[[:space:]]*service:[[:space:]]*http_status:404' "$config_file" || die "Cloudflare config must have a default 404 rule"
  if [[ -f "$ingress_env" ]]; then
    local mode
    mode="$(stat -c '%a' "$ingress_env" 2>/dev/null || true)"
    [[ "$mode" == "600" || "$mode" == "400" ]] || die "$ingress_env must be mode 600 or 400"
  fi
  echo "valid public_url=$public_url config=$config_file"
}

health() {
  [[ -n "$public_url" ]] || die "BIDFINDER_PUBLIC_URL is not configured"
  curl --fail --silent --show-error --max-time 10 "$public_url/health"
  echo
}

status() {
  local active host
  active="inactive"
  if systemctl --user is-active --quiet bidfinder-ingress.service 2>/dev/null; then
    active="active"
  fi
  host="${public_url#https://}"
  host="${host%%/*}"
  echo "ingress=$active public_hostname=${host:-unconfigured}"
  if [[ "$active" == "active" && -n "$public_url" ]]; then
    if health >/dev/null 2>&1; then
      echo "https_health=up"
    else
      echo "https_health=down"
    fi
  else
    echo "https_health=not_checked"
  fi
}

case "${1:-}" in
  validate)
    validate
    ;;
  run)
    validate >/dev/null
    exec "$cloudflared_bin" --no-autoupdate --config "$config_file" tunnel run
    ;;
  health)
    health
    ;;
  status)
    status
    ;;
  *)
    die "usage: $0 {validate|run|health|status}"
    ;;
esac
