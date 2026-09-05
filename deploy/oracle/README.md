# Oracle Always Free deployment

> Layout for CI/CD: clone the full repo to `/opt/logscope` (public repo, no
> token needed) so the pipeline can `git pull --ff-only` from
> `/opt/logscope/deploy/oracle`. The copy-only-the-folder variant below still
> works for manual deploys. Full provisioning order is in
> `docs/ORACLE_SETUP_PLAN.md`; GitHub workflows live in
> `.github/workflows/ci.yml` (pytest + compose validation) and `cd.yml`
> (SSH deploy, native ARM rebuild, instance-principal secret refresh).

This deployment keeps Kafka and LogScope private behind Caddy. Only ports `80` and
`443` should be open in the OCI security list and the VM firewall.

## OCI identity setup

Create the secrets in OCI Secret Management. The CLI's `create-base64` operation
expects a base64-encoded value and returns a secret OCID:

```text
oci vault secret create-base64 --compartment-id <compartment-ocid> \
  --vault-id <vault-ocid> --key-id <master-key-ocid> \
  --secret-name logscope-openai-api-key --secret-content-content <base64-value>
```

Create a dynamic group containing only the production VM. The narrowest matching
rule is:

```text
instance.id = '<production-instance-ocid>'
```

Add a policy in the secret compartment. Replace the dynamic group and compartment
names with the actual values:

```text
Allow dynamic-group logscope-production-vm to read secret-bundles in compartment logscope-secrets
```

The VM uses an instance principal, so no OCI user config or OCI API private key is
stored on disk. Anyone with privileged SSH access to the VM can use that instance
principal; restrict SSH to administrators and rotate application keys as needed.

## VM configuration

Install Docker, Docker Compose v2, the OCI CLI, and `base64`. Copy this deployment
folder to `/opt/logscope`, then create a root-owned configuration file at
`/etc/logscope/oci-secrets.conf`:

```bash
OCI_REGION=us-ashburn-1
OPENAI_SECRET_OCID=ocid1.secret.oc1...
# GEMINI_SECRET_OCID=ocid1.secret.oc1...
```

Protect it with `chown root:root` and `chmod 600`. Source it only from the root
bootstrap service or pass it to the script without printing it. The values in this
file are secret identifiers, not API keys.

Refresh the runtime file and start the stack:

```bash
set -a
. /etc/logscope/oci-secrets.conf
set +a
./bootstrap-secrets.sh
docker compose --env-file /opt/logscope/secrets/.env.runtime \
  -f docker-compose.production.yml up -d --build
```

Do not commit `/opt/logscope/secrets`, `.env.runtime`, OCI configuration files, or
API keys. The bootstrap script retrieves the CURRENT secret bundle using
`--auth instance_principal`, decodes it locally, writes mode-`600` files, and never
prints secret values.
