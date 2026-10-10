output "webhook_url" {
  description = "Telegram webhook endpoint (registered by scripts/set_webhook.py)"
  value       = aws_lambda_function_url.webhook.function_url
}

output "ecr_repository_url" {
  description = "Push the app image here"
  value       = aws_ecr_repository.app.repository_url
}

output "photos_bucket" {
  value = aws_s3_bucket.photos.bucket
}

output "receipts_queue_url" {
  value = aws_sqs_queue.receipts.url
}

output "receipts_dlq_url" {
  description = "Messages that failed every attempt end up here"
  value       = aws_sqs_queue.receipts_dlq.url
}

output "function_names" {
  value = { for key, fn in aws_lambda_function.function : key => fn.function_name }
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub"
  value       = aws_iam_role.github_deploy.arn
}

output "ssm_prefix" {
  value = local.ssm_prefix
}
