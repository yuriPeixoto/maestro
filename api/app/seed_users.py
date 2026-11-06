"""Create accounts in bulk with a temporary password.

    python -m app.seed_users users.json

users.json is a list of {"username": ..., "email": ...}. Existing usernames and
emails are left untouched, so the command is safe to run again. Every account
created here must change its password on first login.

The temporary password is asked for on the terminal and never stored or echoed.
Leave it empty to give each account its own random password, printed once.
"""
from __future__ import annotations

import asyncio
import getpass
import json
import secrets
import sys
from pathlib import Path

from app import auth_db, db
from app.config import settings
from app.permissions import Role

_RANDOM_PASSWORD_BYTES = 9


async def seed(users: list[dict], shared_password: str | None) -> list[tuple[str, str, str]]:
    """Returns (username, outcome, password shown to the operator) per entry."""
    report: list[tuple[str, str, str]] = []
    for entry in users:
        username, email = entry["username"], entry["email"]
        if await auth_db.get_user_by_username(username) or await auth_db.get_user_by_email(email):
            report.append((username, "already exists — skipped", ""))
            continue

        password = shared_password or secrets.token_urlsafe(_RANDOM_PASSWORD_BYTES)
        # Seeded accounts are the installation's first ones: admins unless the file says otherwise.
        role = Role(entry.get("role", Role.ADMIN))
        await auth_db.create_user(username, email, password, must_change_password=True, role=role)
        report.append((username, "created", "" if shared_password else password))
    return report


async def _seed_and_close(users: list[dict], shared_password: str | None) -> list[tuple[str, str, str]]:
    try:
        return await seed(users, shared_password)
    finally:
        await db.dispose_engine()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    db.check_database_url(settings.database_url)

    users = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    shared_password = getpass.getpass("Temporary password (empty = one random password per account): ") or None
    if shared_password:
        auth_db.validate_new_password(shared_password)

    for username, outcome, password in asyncio.run(_seed_and_close(users, shared_password)):
        print(f"{username}: {outcome}" + (f" — temporary password: {password}" if password else ""))


if __name__ == "__main__":
    main()
