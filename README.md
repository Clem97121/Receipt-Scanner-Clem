# Receipt-Scanner-Clem
A pet-project designed to make it easier to track expenses by scanning receipts

## Architecture (AWS Lambda)

One container image (`app/Dockerfile`, AWS Lambda Python base) serves three functions:

- `lambda_handlers.webhook` - Telegram webhook behind a Lambda Function URL. Checks the
  `X-Telegram-Bot-Api-Secret-Token` header, handles commands and buttons, uploads photos to S3 and queues them in SQS.
- `lambda_handlers.worker` - SQS-triggered receipt recognition with Gemini. Transient AI failures are retried
  (`MAX_ATTEMPTS`, based on the SQS receive count); the queue's `maxReceiveCount` must be larger, with a DLQ behind it.
- `lambda_handlers.migrate` - applies Alembic migrations; invoke it once per deploy, before switching traffic.

Conversation state (aiogram FSM) is stored in Postgres (`fsm_states`), because Lambda keeps no memory between calls.
On Lambda, secrets are loaded from SSM Parameter Store under `SSM_PARAMETER_PREFIX`; see `.env.example` for all variables.

For local development, `python app/bot.py` runs long polling with a separate test bot token
(Telegram does not allow polling while a webhook is set).

## Running tests

Tests use SQLite and a fake Telegram session, so no real services or secrets are needed.

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs the suite on every pull request, and the deploy workflow only builds and deploys after the tests pass.

## Database migrations

The schema is managed with Alembic (`app/migrations`). The bot applies pending migrations on startup.
A database created before Alembic was added is detected and stamped with the baseline revision automatically.

After changing `app/db/models.py`, generate a migration from the `app/` directory and review it before committing:

```bash
cd app
DATABASE_URL=sqlite+aiosqlite:///./dev.db alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:///./dev.db alembic revision --autogenerate -m "describe the change"
```

`tests/test_migrations.py` fails if the models and the migrations get out of sync.
