variable "tenancy_ocid" {
  type        = string
  description = "The OCID of the tenancy."
  default     = ""
}

variable "user_ocid" {
  type        = string
  description = "The OCID of the user calling OCI APIs."
  default     = ""
}

variable "fingerprint" {
  type        = string
  description = "The fingerprint of the user's API key."
  default     = ""
}

variable "private_key" {
  type        = string
  description = "The private key content for the user's API key."
  default     = ""
  sensitive   = true
}

variable "compartment_ocid" {
  type        = string
  description = "The OCID of the compartment where resources will be created."
  default     = ""
}

variable "region" {
  type        = string
  description = "The OCI region (e.g. us-ashburn-1, ap-mumbai-1)."
  default     = ""
}

variable "ssh_public_key" {
  type        = string
  description = "Public SSH key text for user ubuntu."
}

variable "repository_url" {
  type        = string
  description = "Public Git repository cloned onto the VM during cloud-init."
}

variable "deploy_user" {
  type        = string
  default     = "logscope-deploy"
  description = "Linux user used by the application CD workflow."
}

variable "logscope_domain" {
  type        = string
  default     = ""
  description = "Public DNS name for the LogScope deployment."
}

variable "openai_secret_ocid" {
  type        = string
  default     = ""
  description = "OCI Vault secret OCID for the OpenAI key."
}

variable "gemini_secret_ocid" {
  type        = string
  default     = ""
  description = "OCI Vault secret OCID for the Gemini key."
}

variable "nvidia_secret_ocid" {
  type        = string
  default     = ""
  description = "OCI Vault secret OCID for the NVIDIA key."
}

variable "instance_display_name" {
  type        = string
  default     = "logscope-production"
  description = "Display name for the Compute VM instance."
}

variable "instance_ocpus" {
  type        = number
  default     = 2
  description = "Number of OCPUs for the Ampere A1 instance (Always Free allows up to 2-4)."
}

variable "instance_memory_in_gbs" {
  type        = number
  default     = 12
  description = "Memory in GB for the Ampere A1 instance (Always Free allows up to 12-24)."
}

variable "boot_volume_size_in_gbs" {
  type        = number
  default     = 50
  description = "Boot volume size in GB (Always Free allows up to 200 GB across tenancy)."
}
