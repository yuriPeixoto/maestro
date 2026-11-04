"""
An .env written for an older version must not stop the API from starting.
"""
from __future__ import annotations

from app.config import Settings


def test_settings_removed_since_are_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MAESTRO_ML_MODELS_DIR=/var/www/maestro/models\nMAESTRO_CLIENT_NAME=Acme\n", encoding="utf-8")

    settings = Settings(_env_file=str(env))

    assert settings.client_name == "Acme"
