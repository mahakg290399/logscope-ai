# Oracle Cloud Setup Plan — LogScope AI (Always Free + GitHub Actions)

Status: **not started** — account created, nothing provisioned yet.
Goal: one Ampere A1 VM running `deploy/oracle/docker-compose.production.yml`,
deployed automatically from GitHub on every push to `master`.
Companion docs: `deploy/oracle/README.md` (OCI identity details),
`.github/workflows/ci.yml` + `cd.yml` (pipeline, parameterized — works once
the values below exist).

## 0. Values to collect (fill as you go)

| # | Value | Example | Yours |
|---|-------|---------|-------|
| 1 | Home region (cannot be changed later) | `ap-mumbai-1` | |
| 2 | Compartment name / OCID | `logscope` | |
| 3 | Vault OCID + master key OCID | | |
| 4 | `OPENAI_SECRET_OCID` (and `GEMINI_SECRET_OCID`, optional) | `ocid1.secret...` | |
| 5 | VM OCID (needed for the dynamic-group rule) | | |
| 6 | VM public IP | | |
| 7 | Domain + DNS A record → VM IP | `logscope.example.com` | |
| 8 | GitHub Secrets set (`OCI_HOST`, `OCI_USER`, `OCI_SSH_KEY`) | yes/no | |

## Phase 1 — Tenancy and region

1. Sign in, confirm the **home region**. Ampere A1 capacity varies by region;
   if instance creation returns `out of host capacity`, retry another
   availability domain first, then consider another home region (only possible
   with a fresh tenancy) or upgrade to PAYG (Always Free limits still apply,
   capacity approval is easier).
2. (Optional, recommended) Upgrade to PAYG. You are still $0 inside Always
   Free limits; it only makes capacity and support easier.

## Phase 2 — Identity: compartment, vault, secrets, policy

Follow `deploy/oracle/README.md` for exact CLI commands. Summary:

1. Compartment `logscope-secrets` (or reuse `logscope`).
2. Vault + master key, then store `logscope-openai-api-key` (and Gemini key).
   Record the secret OCIDs → row 4 above.
3. After Phase 3, create dynamic group `logscope-production-vm` with rule
   `instance.id = '<production-instance-ocid>'`, plus policy:
   `Allow dynamic-group logscope-production-vm to read secret-bundles
   in compartment logscope-secrets`.
4. Never put API keys in Git, Docker images, `.env`, or GitHub Secrets.
   Only secret *OCIDs* live on the VM in `/etc/logscope/oci-secrets.conf`
   (`root:root`, `600`).

## Phase 3 — Network (VCN)

1. VCN with one public subnet + internet gateway + route table.
2. Security list: allow **80/443 from `0.0.0.0/0`** (Caddy).
3. SSH (22): do NOT open to the world. Recommended: install **Tailscale** on
   the VM and use `tailscale/github-action` in `cd.yml` so deploys go over
   the tailnet. Fallback: open 22 to your admin IP only (CD from GitHub then
   needs updating — prefer Tailscale).

## Phase 4 — Compute (the free VM)

Shape: `VM.Standard.A1.Flex` (Ampere ARM), **2 OCPU / 12 GB RAM** (current
Always Free max since June 2026 — older guides quoting 4/24 are outdated),
Ubuntu 24.04 ARM minimal, ~100 GB boot volume (stays under the 200 GB free
pool), public IP assigned, your SSH public key.

Cloud-init (or manual) must install: Docker Engine + Compose v2, OCI CLI,
`base64`, `git`, (recommended) Tailscale.

## Phase 5 — VM application layout (git-clone, not copy)

The pipeline deploys with `git pull`, so clone the full repo (public → no
token needed):

```bash
sudo mkdir -p /opt && sudo chown $USER:$USER /opt
git clone https://github.com/<you>/log_tool.git /opt/logscope
```

Then:

1. `/etc/logscope/oci-secrets.conf` (`root:root 600`) with `OCI_REGION`,
   `OPENAI_SECRET_OCID` (+ optional Gemini OCID) and `LOGSCOPE_DOMAIN`
   (the CD pipeline sources this file, so the domain must live here).
2. Deploy user for CI: `logscope-deploy`, key-only SSH, limited sudo:
   `logscope-deploy ALL=(root) NOPASSWD: /opt/logscope/deploy/oracle/bootstrap-secrets.sh`
3. DNS A record → VM IP; set `LOGSCOPE_DOMAIN` when composing.
4. First boot (manual, SSH in):
   ```bash
   cd /opt/logscope/deploy/oracle
   set -a; . /etc/logscope/oci-secrets.conf; set +a
   sudo ./bootstrap-secrets.sh
   LOGSCOPE_DOMAIN=<domain> docker compose \
     --env-file /opt/logscope/secrets/.env.runtime \
     -f docker-compose.production.yml up -d --build
   curl -fsS https://<domain>/api/health
   ```

## Phase 6 — GitHub: secrets, environment, branch protection

1. Repo Settings → Secrets → Actions: `OCI_HOST` (Tailscale IP or public IP),
   `OCI_USER` (`logscope-deploy`), `OCI_SSH_KEY` (private key).
2. Settings → Environments → `production`: required reviewers optional;
   `cd.yml` already targets this environment, so a missing secret fails
   closed instead of half-deploying.
3. Branch protection on `master`: require `CI` checks green before merge.
4. Push → `ci.yml` runs pytest + compose validation; push to `master` →
   `cd.yml` SSHs in, `git pull --ff-only`, refreshes secrets from OCI,
   rebuilds natively on ARM (no QEMU cross-build, no registry needed),
   health-checks `https://<domain>/api/health`.

## Phase 7 — Operate

- Idle reclaim: Oracle may stop Always Free VMs idle 7 days (<15% CPU/mem).
  Kafka + demo-app traffic keeps this stack active; add Uptime Kuma or a
  `curl` cron as a tripwire, not a fake-load hack.
- Backups: enable Always Free block-volume backups before first prod data.
- Rotation: rotate LLM keys in OCI Vault → re-run `bootstrap-secrets.sh` →
  `docker compose up -d` (no repo or pipeline change needed).
- Logs: `docker compose logs`, dashboard `/api/telemetry`, retention jobs
  per PRD (24h samples, 6-month aggregates).
