"""Points the Telegram bot at the Lambda Function URL.

Reads BOT_TOKEN and WEBHOOK_SECRET from SSM and the URL from `terraform output`; prints no secrets.
Run from infra/aws with the same AWS profile as Terraform:

    python scripts/set_webhook.py           # register the webhook
    python scripts/set_webhook.py --info    # show the current webhook status
    python scripts/set_webhook.py --delete  # remove it (e.g. to go back to long polling)
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request

SSM_PREFIX = "/receipt-scanner"


def run(*args: str) -> str:
    result = subprocess.run(list(args), capture_output=True, text=True, shell=sys.platform == "win32")
    if result.returncode != 0:
        sys.exit(f"Command failed: {' '.join(args[:3])} ...\n{result.stderr.strip()}")
    return result.stdout.strip()


def ssm_secret(name: str) -> str:
    value = run("aws", "ssm", "get-parameter", "--name", f"{SSM_PREFIX}/{name}",
                "--with-decryption", "--query", "Parameter.Value", "--output", "text")
    if not value or value == "CHANGE_ME":
        sys.exit(f"{SSM_PREFIX}/{name} is not set yet; set it with aws ssm put-parameter --overwrite")
    return value


def telegram(token: str, method: str, params: dict | None = None) -> dict:
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--info", action="store_true", help="only show the current webhook status")
    parser.add_argument("--delete", action="store_true", help="remove the webhook")
    args = parser.parse_args()

    token = ssm_secret("BOT_TOKEN")

    if args.delete:
        print(telegram(token, "deleteWebhook"))
        return

    if not args.info:
        url = run("terraform", "output", "-raw", "webhook_url")
        result = telegram(token, "setWebhook", {
            "url": url,
            "secret_token": ssm_secret("WEBHOOK_SECRET"),
            "allowed_updates": json.dumps(["message", "callback_query"]),
            "max_connections": 10,
        })
        print("setWebhook:", result.get("description", result))

    info = telegram(token, "getWebhookInfo")["result"]
    print(json.dumps({key: info.get(key) for key in (
        "url", "pending_update_count", "last_error_date", "last_error_message", "max_connections", "allowed_updates"
    )}, indent=2))


if __name__ == "__main__":
    main()
