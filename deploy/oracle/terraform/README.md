# Oracle Cloud Always Free — 1-Click Terraform Deployment

This Terraform module automatically provisions:
1. **Virtual Cloud Network (VCN)** with public subnet and route tables.
2. **Security List** opening ports `22` (SSH), `80` (HTTP), and `443` (HTTPS for Caddy / LogScope).
3. **Ampere A1 Compute Instance** (`VM.Standard.A1.Flex`, 2 OCPU, 12 GB RAM) running **Canonical Ubuntu 24.04 ARM64**.

> **Zero Secrets Policy**: No passwords, API keys, private keys, or account IDs are stored in these files. All values are passed dynamically via variables at execution time.

## OCI permissions

Put `logscope-infra-agent` in a dedicated group and grant it access only to
the deployment compartment:

```text
Allow group logscope-infra-group to manage instance-family in compartment <logscope-compartment>
Allow group logscope-infra-group to manage virtual-network-family in compartment <logscope-compartment>
Allow group logscope-infra-group to manage volume-family in compartment <logscope-compartment>
```

Using `in tenancy` is broader than necessary and lets this user manage those
resource families across the entire tenancy.

---

## 1-Click Deployment via OCI Resource Manager (No CLI Required)

Oracle Cloud provides **Resource Manager** (a free, managed Terraform service) directly inside the console:

### Step 1: Create a Stack
1. In the Oracle Cloud Console search bar, type **Stacks** (or navigate to **Developer Services** > **Resource Manager** > **Stacks**).
2. Click **Create Stack**.
3. Under **Origin**:
   - Select **My Configuration** > **Folder** (or **Zip file**): Upload the [`deploy/oracle/terraform/`](.) folder.
   - *Or* select **Source Code Control** and point to your GitHub repository path `deploy/oracle/terraform`.
4. Click **Next**.

### Step 2: Configure Variables
Fill in the simple parameters:
- **`ssh_public_key`**: Paste the OpenSSH public key matching the private key stored in GitHub as `OCI_SSH_KEY`.
- **`repository_url`**: The public Git repository URL cloned during VM bootstrap.
- **`logscope_domain`**: The DNS name used by Caddy (optional until DNS is ready).
- **`openai_secret_ocid`**, **`gemini_secret_ocid`**, **`nvidia_secret_ocid`**: Vault secret identifiers (not secret values).
- **`compartment_ocid`**: Select your root or logscope compartment from the dropdown (OCI populates this automatically).
- Leave `instance_ocpus=2` and `instance_memory_in_gbs=12` (Always Free defaults).
5. Click **Next** > Click **Create**.

### Step 3: Apply & Launch
1. On your newly created stack page, click **Terraform Actions** > **Apply**.
2. Click **Apply** in the confirmation modal.
3. Resource Manager will run Terraform in the cloud and output:
   - `instance_public_ip` = `xxx.xxx.xxx.xxx`
   - `ssh_command` = `ssh -i <your_key> ubuntu@xxx.xxx.xxx.xxx`

Once complete, your Ubuntu 24.04 ARM VM with ports 80/443/22 open will be live and ready for GitHub Actions CD!

Cloud-init also installs Docker/Compose, Git, and the OCI CLI; creates the
`logscope-deploy` SSH user; clones the repository; and writes the root-owned
`/etc/logscope/oci-secrets.conf`. The application CD workflow only needs to
SSH in and run the deployment compose command.

The OCI API user and the Linux SSH user are intentionally different identities:
the former authenticates Terraform to OCI; the latter is used by GitHub Actions
to deploy application code.
