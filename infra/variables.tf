variable "resource_group_name" {
  description = "Azure resource group name"
  type        = string
  default     = "receipt_scanner"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "southafricanorth"
}

variable "vm_size" {
  description = "Virtual machine size"
  type        = string
  default     = "Standard_B2als_v2" # 2 vCPUs, 4 GiB RAM — optimal for K3s
}

variable "admin_username" {
  description = "VM administrator username"
  type        = string
  default     = "devops"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}