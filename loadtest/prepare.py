"""Prepare a load test: load-test users (each signed in), a customer and a well-stocked product.

    cd e2e && python ../loadtest/prepare.py --users 20

Writes loadtest/.data/k6-data.json (git-ignored): short-lived access tokens (15 min) plus ids.
Sign-in codes use the acceptance helper: backend logs by default or Mailpit when
E2E_OTP_SOURCE=email. Set E2E_BASE_URL and the test admin credentials for an isolated QA stack.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "e2e"))

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, Api  # noqa: E402 - after the sys.path setup above

PASSWORD = "Capacity-Run-2026x"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, default=20)
    args = parser.parse_args()

    run = uuid.uuid4().hex[:6]
    admin = Api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    customer = admin.post(
        "/customers",
        {"name": f"Load test customer {run}", "email": f"load-{run}@example.com"},
    )
    product = admin.post(
        "/products",
        {
            "sku": f"LOAD-{run}".upper(),
            "name": f"Load test item {run}",
            "unit_price": 10,
            "reorder_level": 0,
            "opening_stock": 1_000_000,
        },
    )
    tokens = []
    for n in range(args.users):
        email = f"load-{run}-{n}@example.com"
        admin.post(
            "/users",
            {
                "name": f"Load User {n}",
                "email": email,
                "password": PASSWORD,
                "role": "SALES",
            },
        )
        tokens.append(Api.login(email, PASSWORD).token)
        print(f"signed in {email}", flush=True)

    out = HERE / ".data" / "k6-data.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "tokens": tokens,
                "customer_id": customer["id"],
                "product_id": product["id"],
            }
        )
    )
    print(f"wrote {out} ({len(tokens)} users)")


if __name__ == "__main__":
    main()
