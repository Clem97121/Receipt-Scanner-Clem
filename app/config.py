import logging
import os

# On Lambda, secrets live in SSM Parameter Store under this prefix (e.g. /receipt-scanner/BOT_TOKEN).
SSM_PREFIX_ENV = "SSM_PARAMETER_PREFIX"


def load_ssm_parameters() -> None:
    """Copies SecureString parameters from SSM into os.environ, without overriding variables already set.

    Must run before importing modules that read their configuration at import time (bot, tasks, db.database).
    Does nothing outside Lambda, where the prefix is not configured and .env is used instead.
    """
    prefix = os.getenv(SSM_PREFIX_ENV)
    if not prefix:
        return

    import boto3

    prefix = prefix.rstrip("/") + "/"
    client = boto3.client("ssm")
    loaded = []
    for page in client.get_paginator("get_parameters_by_path").paginate(Path=prefix, WithDecryption=True):
        for parameter in page["Parameters"]:
            name = parameter["Name"][len(prefix):]
            if name and name not in os.environ:
                os.environ[name] = parameter["Value"]
                loaded.append(name)
    logging.info(f"Loaded {len(loaded)} parameters from SSM: {sorted(loaded)}")
