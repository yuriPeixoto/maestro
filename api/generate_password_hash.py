#!/usr/bin/env python3
"""Run once with the API venv to generate the admin password hash.

Usage (on the server):
    /opt/maestro/api/.venv/bin/python generate_password_hash.py
"""
import getpass
import bcrypt

pwd = getpass.getpass("Nova senha do admin: ")
confirm = getpass.getpass("Confirmar senha: ")

if pwd != confirm:
    print("Senhas nao conferem.")
    raise SystemExit(1)

if len(pwd) < 8:
    print("Senha muito curta (minimo 8 caracteres).")
    raise SystemExit(1)

hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt(12)).decode()
print("\nAdicione ao /opt/maestro/api/.env:")
print(f'MAESTRO_ADMIN_PASSWORD_HASH="{hashed}"')
