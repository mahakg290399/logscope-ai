#!/usr/bin/env bash
# Retrieve OCI Secret Management values using the VM's instance principal.
# Run this script on the Oracle VM, never from a developer workstation.
set -Eeuo pipefail

SECRETS_DIR="${LOGSCOPE_SECRETS_DIR:-/opt/logscope/secrets}"
OCI_CLI="${OCI_CLI:-oci}"

CONFIG_FILE="${LOGSCOPE_OCI_CONFIG_FILE:-/etc/logscope/oci-secrets.conf}"
if [[ -r "$CONFIG_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
  set +a
fi
OCI_REGION="${OCI_REGION:?Set OCI_REGION to the VM region}"

# Secret OCIDs are identifiers, not secret values. Keep them in the VM's root-owned
# configuration rather than putting secret values in shell history or process args.
NVIDIA_SECRET_OCID="${NVIDIA_SECRET_OCID:-}"
OPENAI_SECRET_OCID="${OPENAI_SECRET_OCID:-}"
GEMINI_SECRET_OCID="${GEMINI_SECRET_OCID:-}"

umask 077
install -d -o root -g docker -m 750 "$SECRETS_DIR"

fetch_secret() {
  local name="$1"
  local ocid="$2"
  local output="$SECRETS_DIR/$name"
  local temporary

  [[ -n "$ocid" ]] || return 0
  echo "[OCI:Vault] Retrieving secret '$name' (OCID: $ocid)..."
  temporary="$(mktemp "$SECRETS_DIR/.${name}.XXXXXX")"
  chmod 600 "$temporary"
  trap 'rm -f "$temporary"' RETURN

  if ! "$OCI_CLI" secrets secret-bundle get \
    --auth instance_principal \
    --region "$OCI_REGION" \
    --secret-id "$ocid" \
    --query 'data."secret-bundle-content".content' \
    --raw-output | base64 --decode > "$temporary"; then
    echo "[OCI:Vault] ERROR: Failed to fetch secret '$name' from OCI Vault (Region: $OCI_REGION, OCID: $ocid)" >&2
    return 1
  fi

  [[ -s "$temporary" ]] || { echo "[OCI:Vault] ERROR: Secret '$name' content was empty" >&2; return 1; }
  install -o root -g docker -m 640 "$temporary" "$output"
  rm -f "$temporary"
  trap - RETURN
  echo "[OCI:Vault] Successfully retrieved and stored secret '$name'"
}

fetch_secret NVIDIA_API_KEY "$NVIDIA_SECRET_OCID"
fetch_secret OPENAI_API_KEY "$OPENAI_SECRET_OCID"
fetch_secret GEMINI_API_KEY "$GEMINI_SECRET_OCID"

# Compose reads this file with env_file. It contains no shell syntax and is never
# printed. Existing values are replaced atomically only after successful retrieval.
env_file="$SECRETS_DIR/.env.runtime"
temporary_env="$(mktemp "$SECRETS_DIR/.env.runtime.XXXXXX")"
trap 'rm -f "$temporary_env"' EXIT
chmod 600 "$temporary_env"
{
  printf 'LOGSCOPE_ENV=production\n'
  printf 'LOGSCOPE_HOST=0.0.0.0\n'
  printf 'LOGSCOPE_PORT=8000\n'
  printf 'LOGSCOPE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092\n'
  printf 'LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=false\n'
  if [[ -f "$SECRETS_DIR/NVIDIA_API_KEY" ]]; then
    printf 'NVIDIA_API_KEY=%s\n' "$(<"$SECRETS_DIR/NVIDIA_API_KEY")"
  fi
  if [[ -f "$SECRETS_DIR/OPENAI_API_KEY" ]]; then
    printf 'OPENAI_API_KEY=%s\n' "$(<"$SECRETS_DIR/OPENAI_API_KEY")"
  fi
  if [[ -f "$SECRETS_DIR/GEMINI_API_KEY" ]]; then
    printf 'GEMINI_API_KEY=%s\n' "$(<"$SECRETS_DIR/GEMINI_API_KEY")"
  fi
} > "$temporary_env"
install -o root -g docker -m 640 "$temporary_env" "$env_file"
rm -f "$temporary_env"
trap - EXIT

echo "OCI secrets refreshed in $SECRETS_DIR; values were not printed."
