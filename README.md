# Receipt-Scanner-Clem
A pet-project designed to make it easier to track expenses by scanning receipts

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
