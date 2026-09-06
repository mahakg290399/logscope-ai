# ==============================================================================
# Oracle Cloud Always Free - Ampere A1 (ARM64) Infrastructure
# Zero secrets hardcoded. Safe for public repositories.
# ==============================================================================

# Look up Availability Domain
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
}

# Look up official Canonical Ubuntu 24.04 ARM64 image
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# 1. Virtual Cloud Network (VCN)
resource "oci_core_vcn" "logscope_vcn" {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "logscope-vcn"
  dns_label      = "logscope"
}

# 2. Internet Gateway
resource "oci_core_internet_gateway" "logscope_igw" {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  vcn_id         = oci_core_vcn.logscope_vcn.id
  display_name   = "logscope-igw"
  enabled        = true
}

# 3. Route Table (Default route to Internet Gateway)
resource "oci_core_route_table" "logscope_rt" {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  vcn_id         = oci_core_vcn.logscope_vcn.id
  display_name   = "logscope-route-table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.logscope_igw.id
  }
}

# 4. Security List (Open Ports 22 for SSH, 80 for HTTP, 443 for HTTPS)
resource "oci_core_security_list" "logscope_sl" {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  vcn_id         = oci_core_vcn.logscope_vcn.id
  display_name   = "logscope-security-list"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
    stateless   = false
  }

  # SSH (Port 22)
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false
    description = "Allow SSH"

    tcp_options {
      min = 22
      max = 22
    }
  }

  # HTTP (Port 80 for Caddy Let's Encrypt challenge & redirect)
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false
    description = "Allow HTTP for Caddy"

    tcp_options {
      min = 80
      max = 80
    }
  }

  # HTTPS (Port 443 for TLS Web App & Ingestion)
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false
    description = "Allow HTTPS for Caddy"

    tcp_options {
      min = 443
      max = 443
    }
  }
}

# 5. Public Regional Subnet
resource "oci_core_subnet" "logscope_subnet" {
  compartment_id    = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  vcn_id            = oci_core_vcn.logscope_vcn.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "logscope-public-subnet"
  dns_label         = "public"
  route_table_id    = oci_core_route_table.logscope_rt.id
  security_list_ids = [oci_core_security_list.logscope_sl.id]
}

# 6. Compute Instance (Ampere A1 Flex on Ubuntu 24.04 ARM64)
resource "oci_core_instance" "logscope_vm" {
  compartment_id      = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = var.instance_display_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_in_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_size_in_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.logscope_subnet.id
    assign_public_ip = true
    display_name     = "primary-vnic"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      repository_url     = var.repository_url
      deploy_user        = var.deploy_user
      ssh_public_key     = var.ssh_public_key
      region             = var.region
      logscope_domain    = var.logscope_domain
      openai_secret_ocid = var.openai_secret_ocid
      gemini_secret_ocid = var.gemini_secret_ocid
      nvidia_secret_ocid = var.nvidia_secret_ocid
    }))
  }
}
