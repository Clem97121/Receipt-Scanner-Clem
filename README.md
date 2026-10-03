# Receipt-Scanner-Clem
A pet-project designed to make it easier to track expenses by scanning receipts

## Running tests

Tests use SQLite and a fake Telegram session, so no real services or secrets are needed.

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs the suite on every pull request, and the deploy workflow only builds and deploys after the tests pass.
