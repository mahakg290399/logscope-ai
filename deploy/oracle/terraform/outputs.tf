output "instance_public_ip" {
  description = "The public IPv4 address of the LogScope VM."
  value       = oci_core_instance.logscope_vm.public_ip
}

output "instance_ocid" {
  description = "The OCID of the LogScope VM instance."
  value       = oci_core_instance.logscope_vm.id
}

output "ssh_command" {
  description = "SSH connection string."
  value       = "ssh -i <your_private_key.key> ubuntu@${oci_core_instance.logscope_vm.public_ip}"
}
