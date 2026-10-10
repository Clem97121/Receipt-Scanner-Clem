locals {
  # One container image, three functions; the handler is chosen by the image command
  functions = {
    webhook = {
      handler     = "lambda_handlers.webhook"
      timeout     = 30
      memory_size = 512
      description = "Telegram webhook: commands, buttons, photo upload"
    }
    worker = {
      handler     = "lambda_handlers.worker"
      timeout     = local.worker_timeout_seconds
      memory_size = 1024
      description = "Recognizes queued receipts with Gemini"
    }
    migrate = {
      handler     = "lambda_handlers.migrate"
      timeout     = 120
      memory_size = 512
      description = "Applies Alembic migrations; invoked once per deploy"
    }
  }

  function_environment = {
    SSM_PARAMETER_PREFIX = local.ssm_prefix
    PHOTOS_BUCKET        = aws_s3_bucket.photos.bucket
    RECEIPTS_QUEUE_URL   = aws_sqs_queue.receipts.url
    BOT_TIMEZONE         = var.bot_timezone
    DEFAULT_CURRENCY     = var.default_currency
  }

  account_id = data.aws_caller_identity.current.account_id
}

# --- IAM: one role per function, each with only what it needs ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  for_each = local.functions

  # Must start with "<project>-": the Terraform IAM user may only manage such roles
  name               = "${var.project}-${each.key}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "function" {
  for_each = local.functions

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.function[each.key].arn}:*"]
  }

  statement {
    sid     = "ReadSecrets"
    actions = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${local.ssm_prefix}",
      "arn:aws:ssm:${var.aws_region}:${local.account_id}:parameter${local.ssm_prefix}/*",
    ]
  }

  dynamic "statement" {
    for_each = each.key == "webhook" ? [1] : []
    content {
      sid       = "UploadAndDeletePhotos"
      actions   = ["s3:PutObject", "s3:DeleteObject"]
      resources = ["${aws_s3_bucket.photos.arn}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "webhook" ? [1] : []
    content {
      sid       = "QueueReceipts"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.receipts.arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "worker" ? [1] : []
    content {
      sid       = "ReadAndDeletePhotos"
      actions   = ["s3:GetObject", "s3:DeleteObject"]
      resources = ["${aws_s3_bucket.photos.arn}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "worker" ? [1] : []
    content {
      sid = "ConsumeReceipts"
      actions = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility", # retry transient AI failures after 10s
      ]
      resources = [aws_sqs_queue.receipts.arn]
    }
  }
}

resource "aws_iam_role_policy" "function" {
  for_each = local.functions

  name   = "${var.project}-${each.key}"
  role   = aws_iam_role.function[each.key].id
  policy = data.aws_iam_policy_document.function[each.key].json
}

# --- Functions ---

resource "aws_cloudwatch_log_group" "function" {
  for_each = local.functions

  name              = "/aws/lambda/${var.project}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "function" {
  for_each = local.functions

  function_name = "${var.project}-${each.key}"
  description   = each.value.description
  role          = aws_iam_role.function[each.key].arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory_size

  image_config {
    command = [each.value.handler]
  }

  environment {
    variables = local.function_environment
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.function[each.key].name
  }

  lifecycle {
    # CI deploys new images with "aws lambda update-function-code"; Terraform must not roll them back
    ignore_changes = [image_uri]
  }

  depends_on = [aws_iam_role_policy.function]
}

# --- Triggers ---

resource "aws_lambda_event_source_mapping" "receipts" {
  event_source_arn        = aws_sqs_queue.receipts.arn
  function_name           = aws_lambda_function.function["worker"].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}

# Public HTTPS endpoint for Telegram; requests are authenticated by the webhook secret header.
# With authorization_type NONE the provider adds the public invoke permissions itself.
resource "aws_lambda_function_url" "webhook" {
  function_name      = aws_lambda_function.function["webhook"].function_name
  authorization_type = "NONE"
}
