#!/usr/bin/env bash
set -Eeuo pipefail

# Run locally after authenticating the OCI CLI.
# API keys are prompted interactively and are never written to this file.

OCI_PROFILE="DEFAULT"
OCI_CONFIG_FILE="${OCI_CONFIG_FILE:-$HOME/.oci/config}"
REGION="ap-mumbai-1"
COMPARTMENT_OCID="ocid1.tenancy.oc1..aaaaaaaa3n6fdviijf22wewmr3zgjwkkplz6px524uqmodwn6bps6v75ymuq"
LOCAL_ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deployment.local.env"

if [[ "$COMPARTMENT_OCID" == PASTE_* ]]; then
  read -r -p "OCI compartment OCID: " COMPARTMENT_OCID
fi

OCI=(oci --config-file "$OCI_CONFIG_FILE" --profile "$OCI_PROFILE")
KMS_ENDPOINT="https://kmsmanagement.${REGION}.oraclecloud.com"

echo "Creating OCI Vault..."
VAULT_OCID="$(${OCI[@]} kms management vault create \
  --compartment-id "$COMPARTMENT_OCID" \
  --display-name logscope-production-vault \
  --vault-type DEFAULT \
  --endpoint "$KMS_ENDPOINT" \
  --wait-for-state ACTIVE \
  --max-wait-seconds 600 \
  --query 'data.id' --raw-output)"

VAULT_MANAGEMENT_ENDPOINT="$(${OCI[@]} kms management vault get \
  --vault-id "$VAULT_OCID" \
  --region "$REGION" \
  --query 'data."management-endpoint"' --raw-output)"
[[ -n "$VAULT_MANAGEMENT_ENDPOINT" && "$VAULT_MANAGEMENT_ENDPOINT" != "null" ]] || {
  echo "Vault management endpoint was not available." >&2
  exit 1
}

echo "Creating encryption key..."
KEY_OCID="$(${OCI[@]} kms management key create \
  --compartment-id "$COMPARTMENT_OCID" \
  --display-name logscope-production-key \
  --key-shape '{"algorithm":"AES","length":32}' \
  --protection-mode SOFTWARE \
  --endpoint "$VAULT_MANAGEMENT_ENDPOINT" \
  --wait-for-state ENABLED \
  --max-wait-seconds 600 \
  --query 'data.id' --raw-output)"

create_secret() {
  local name="$1"
  local value encoded

  read -r -s -p "Paste ${name}: " value
  echo
  encoded="$(printf '%s' "$value" | base64 | tr -d '\n')"
  unset value

  "${OCI[@]}" vault secret create-base64 \
    --compartment-id "$COMPARTMENT_OCID" \
    --vault-id "$VAULT_OCID" \
    --key-id "$KEY_OCID" \
    --secret-name "$name" \
    --secret-content-content "$encoded" \
    --region "$REGION" \
    --query 'data.id' --raw-output
}

OPENAI_SECRET_OCID="$(create_secret OPENAI_API_KEY)"
GEMINI_SECRET_OCID="$(create_secret GEMINI_API_KEY)"
NVIDIA_SECRET_OCID="$(create_secret NVIDIA_API_KEY)"

upsert_local_value() {
  local key="$1" value="$2"
  if [[ -f "$LOCAL_ENV_FILE" ]] && grep -q "^${key}=" "$LOCAL_ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$LOCAL_ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$LOCAL_ENV_FILE"
  fi
}

upsert_local_value VAULT_OCID "$VAULT_OCID"
upsert_local_value KEY_OCID "$KEY_OCID"
upsert_local_value OPENAI_SECRET_OCID "$OPENAI_SECRET_OCID"
upsert_local_value GEMINI_SECRET_OCID "$GEMINI_SECRET_OCID"
upsert_local_value NVIDIA_SECRET_OCID "$NVIDIA_SECRET_OCID"

echo
echo "Vault and secrets created. Secret OCIDs were saved to: $LOCAL_ENV_FILE"
echo "VAULT_OCID=$VAULT_OCID"
echo "OPENAI_SECRET_OCID=$OPENAI_SECRET_OCID"
echo "GEMINI_SECRET_OCID=$GEMINI_SECRET_OCID"
echo "NVIDIA_SECRET_OCID=$NVIDIA_SECRET_OCID"
