output "public_ip" {
  description = "Public IP address of the K3s node"
  value       = azurerm_public_ip.pip.ip_address
}

output "ssh_command" {
  description = "Command to connect via SSH"
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.pip.ip_address}"
}

output "azure_storage_connection_string" {
  description = "Connection String for Connecting a Python Application to Azure Blob Storage"
  value       = azurerm_storage_account.app_storage.primary_connection_string
  sensitive   = true
}

output "azure_storage_container_name" {
  description = "Name of the receipt container"
  value       = azurerm_storage_container.receipts_container.name
}