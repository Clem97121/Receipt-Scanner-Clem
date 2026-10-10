# AWS infrastructure

Serverless setup for the bot: Telegram webhook on a Lambda Function URL, an SQS-triggered worker Lambda,
S3 for receipt photos, SSM Parameter Store for secrets, Neon (serverless Postgres) as the database.
See the "Architecture" section of the main README for how the pieces talk to each other.

| File | Contents |
|---|---|
| `bootstrap/` | S3 bucket for the Terraform state (applied once, local state) |
| `storage.tf` | ECR repository, photos bucket, receipts queue + DLQ, SSM parameters |
| `lambda.tf` | `webhook`, `worker`, `migrate` functions, their IAM roles, logs, SQS trigger, Function URL |
| `github_oidc.tf` | Role that GitHub Actions assumes to deploy new images (no stored AWS keys) |
| `scripts/set_webhook.py` | Registers the Function URL with Telegram |

Terraform runs as the `receipt-scanner-terraform` IAM user (AWS profile `receipt-scanner`), never as root.
That user may only manage IAM roles named `receipt-scanner-*`.

## First deployment

PowerShell, from the repository root:

```powershell
$env:AWS_PROFILE = "receipt-scanner"

# 1. State bucket (once)
cd infra/aws/bootstrap
terraform init
terraform apply

# 2. Container registry first: the functions need an image to exist
cd ..
terraform init
terraform apply -target="aws_ecr_repository.app"

# 3. Build and push the image (Docker Desktop must be running)
$ECR = terraform output -raw ecr_repository_url
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR.Split("/")[0]
docker build -f ../../app/Dockerfile --platform linux/amd64 --provenance=false -t "${ECR}:latest" ../..
docker push "${ECR}:latest"

# 4. Everything else
terraform apply

# 5. Secrets (Terraform only creates placeholders, so the values never reach the state)
aws ssm put-parameter --overwrite --type SecureString --name /receipt-scanner/BOT_TOKEN --value "<token>"
aws ssm put-parameter --overwrite --type SecureString --name /receipt-scanner/GEMINI_API_KEY --value "<key>"
aws ssm put-parameter --overwrite --type SecureString --name /receipt-scanner/DATABASE_URL --value "<Neon connection string>"

# 6. Create the database schema
aws lambda invoke --function-name receipt-scanner-migrate --cli-binary-format raw-in-base64-out --payload '{}' migrate.json
Get-Content migrate.json   # {"status": "ok"}

# 7. Switch Telegram to the webhook (this is the cutover: long polling stops working for this bot)
python scripts/set_webhook.py
```

The Neon connection string can be pasted as is (`postgresql://...?sslmode=require`); the app converts it for asyncpg.
Lambdas read the secrets at cold start, so after changing one, the next new instance picks it up
(force it with any `aws lambda update-function-configuration` change, or wait a few minutes).

Then set the GitHub repository variable `AWS_DEPLOY_ROLE_ARN` to `terraform output -raw github_deploy_role_arn`:
from then on every push to `main` that touches `app/` runs the tests, builds the image, runs migrations
and deploys (`.github/workflows/deploy-aws.yml`).

## Operations

- Logs: CloudWatch log groups `/aws/lambda/receipt-scanner-{webhook,worker,migrate}`, e.g.
  `aws logs tail /aws/lambda/receipt-scanner-worker --follow`.
- Failed receipts: `terraform output -raw receipts_dlq_url`; inspect with `aws sqs receive-message --queue-url <url>`.
- Webhook status: `python scripts/set_webhook.py --info`; remove it with `--delete` (e.g. to run the bot locally with polling).
- Roll back the app: re-run the deploy workflow for an older commit, or point the functions at an older image tag
  with `aws lambda update-function-code --image-uri <ecr>:<sha>`.
