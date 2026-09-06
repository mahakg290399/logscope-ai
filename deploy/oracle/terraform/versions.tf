terraform {
  backend "oci" {
    bucket    = "logscope-terraform-state"
    namespace = "bmsfcd4g3w9x"
    key       = "logscope/production/terraform.tfstate"
    auth      = "APIKey"
  }

  required_version = ">= 1.2.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0.0"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid != "" ? var.tenancy_ocid : null
  user_ocid    = var.user_ocid != "" ? var.user_ocid : null
  fingerprint  = var.fingerprint != "" ? var.fingerprint : null
  private_key  = var.private_key != "" ? var.private_key : null
  region       = var.region != "" ? var.region : null
}
