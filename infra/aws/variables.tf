variable "aws_region" {
  description = "AWS region for all resources (Frankfurt is closest to Prague)"
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Name prefix for every resource; the Terraform IAM user may only manage roles named <project>-*"
  type        = string
  default     = "receipt-scanner"
}

variable "image_tag" {
  description = "Image tag used when the Lambda functions are first created; CI deploys newer images itself"
  type        = string
  default     = "latest"
}

variable "photo_retention_days" {
  description = "Receipt photos are deleted from S3 after this many days"
  type        = number
  default     = 90
}

variable "worker_max_concurrency" {
  description = "Maximum receipts recognized in parallel (protects the Gemini quota); 2 is the SQS minimum"
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps Lambda logs"
  type        = number
  default     = 14
}

variable "bot_timezone" {
  description = "Timezone for \"today\" and \"this month\""
  type        = string
  default     = "Europe/Prague"
}

variable "default_currency" {
  description = "Currency of manual expenses"
  type        = string
  default     = "CZK"
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy via OIDC"
  type        = string
  default     = "Clem97121/Receipt-Scanner-Clem"
}

variable "deploy_branch" {
  description = "Only workflows running on this branch may assume the deploy role"
  type        = string
  default     = "main"
}
