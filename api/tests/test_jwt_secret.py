"""
The API refuses to start with a token secret anyone could know.
"""
from __future__ import annotations

import pytest

from app.config import check_jwt_secret


class TestJwtSecret:
    @pytest.mark.parametrize(
        "secret",
        ["", "change-me-before-deploy", "dev-secret-change-in-production", "a" * 31],
    )
    def test_missing_public_or_short_secrets_are_refused(self, secret):
        with pytest.raises(RuntimeError, match="MAESTRO_JWT_SECRET"):
            check_jwt_secret(secret)

    def test_a_generated_secret_is_accepted(self):
        check_jwt_secret("3f" * 32)  # what `openssl rand -hex 32` prints
