# --- Container registry: one image for all Lambda functions ---

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE" # "latest" is re-pointed on every deploy

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images (enough to roll back)"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# --- Receipt photos ---

resource "aws_s3_bucket" "photos" {
  # Bucket names are global; the prefix gets a unique suffix
  bucket_prefix = "${var.project}-photos-"
}

resource "aws_s3_bucket_ownership_controls" "photos" {
  bucket = aws_s3_bucket.photos.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "photos" {
  bucket = aws_s3_bucket.photos.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "photos" {
  bucket = aws_s3_bucket.photos.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "photos" {
  bucket = aws_s3_bucket.photos.id

  rule {
    id     = "expire-old-photos"
    status = "Enabled"

    # Photos are only kept to re-recognize a receipt; the receipt itself stays in the DB
    filter {}

    expiration {
      days = var.photo_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# --- Receipt queue (replaces Celery + Redis) ---

locals {
  worker_timeout_seconds = 330 # two Gemini calls (primary + fallback) at 120s each, plus download and saving

  # Must exceed tasks.MAX_ATTEMPTS (3), so the last attempt can still tell the user what happened
  max_receive_count = 5
}

resource "aws_sqs_queue" "receipts_dlq" {
  name                      = "${var.project}-receipts-dlq"
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "receipts" {
  name = "${var.project}-receipts"

  # AWS recommends at least 6x the function timeout for Lambda event sources.
  # Transient AI failures don't wait this long: the worker shortens it to 10s (receipt_queue.retry_later).
  visibility_timeout_seconds = 6 * local.worker_timeout_seconds
  message_retention_seconds  = 4 * 24 * 3600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.receipts_dlq.arn
    maxReceiveCount     = local.max_receive_count
  })
}

# --- Secrets (read by the functions at cold start, see app/config.py) ---

locals {
  ssm_prefix = "/${var.project}"

  # Values are set outside Terraform so they never land in the state:
  #   aws ssm put-parameter --name /receipt-scanner/BOT_TOKEN --type SecureString --overwrite --value ...
  manual_secrets = toset(["BOT_TOKEN", "GEMINI_API_KEY", "DATABASE_URL"])
}

resource "aws_ssm_parameter" "manual_secret" {
  for_each = local.manual_secrets

  name        = "${local.ssm_prefix}/${each.key}"
  type        = "SecureString"
  value       = "CHANGE_ME"
  description = "Set the real value with: aws ssm put-parameter --overwrite"

  lifecycle {
    ignore_changes = [value]
  }
}

# Telegram allows only A-Z, a-z, 0-9, _ and - in the webhook secret token
resource "random_password" "webhook_secret" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "webhook_secret" {
  name        = "${local.ssm_prefix}/WEBHOOK_SECRET"
  type        = "SecureString"
  value       = random_password.webhook_secret.result
  description = "Sent by Telegram in X-Telegram-Bot-Api-Secret-Token; registered by scripts/set_webhook.py"
}
