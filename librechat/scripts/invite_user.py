#!/usr/bin/env python3
"""
Crea un utente LibreChat e invia un'email con le credenziali.

Uso:
    python librechat/scripts/invite_user.py dr@mojalab.com
    python librechat/scripts/invite_user.py dr@mojalab.com --name "Dario Rossi" --username dario
    python librechat/scripts/invite_user.py dr@mojalab.com --no-email

Requisiti:
    - Docker e il container `igr-librechat` devono essere raggiungibili.
    - Il file librechat/librechat.env deve contenere la configurazione email (Resend).
"""

import argparse
import json
import random
import re
import string
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env_file(path: Path) -> dict:
    """Carica le variabili da un file .env semplice."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def generate_password(length: int = 18) -> str:
    """Genera una password sicura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_+"
    while True:
        pwd = "".join(random.SystemRandom().choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*-_+" for c in pwd)
        ):
            return pwd


def validate_email(email: str) -> None:
    if "@" not in email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError(f"Indirizzo email non valido: {email}")


def create_librechat_user(
    email: str,
    name: str,
    username: str,
    password: str,
    container: str = "igr-librechat",
) -> None:
    """Crea l'utente dentro il container LibreChat."""
    cmd = [
        "docker",
        "exec",
        container,
        "npm",
        "run",
        "create-user",
        "--",
        email,
        name,
        username,
        password,
        "--email-verified=true",
    ]
    print(f"[docker] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"create-user ha restituito codice {result.returncode}")


def send_resend_email(
    api_key: str,
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    html: str,
) -> str:
    """Invia un'email tramite l'API Resend. Restituisce l'ID del messaggio."""
    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("id", "<nessun-id>")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"Errore Resend HTTP {exc.code}: {body}")


def build_email_html(
    app_name: str,
    domain: str,
    email: str,
    password: str,
    year: int,
) -> str:
    login_url = f"{domain}/login"
    reset_url = f"{domain}/forgot-password"
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Benvenuto in {app_name}</title>
  <style>
    body {{ margin: 0; padding: 0; background-color: #212121; color: #ffffff; font-family: Arial, Helvetica, sans-serif; }}
    .container {{ max-width: 500px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 22px; font-weight: 700; }}
    p {{ font-size: 14px; line-height: 1.6; }}
    .box {{ background-color: #2c2c2c; padding: 16px; border-radius: 8px; margin: 16px 0; }}
    .credential {{ font-family: monospace; font-size: 15px; color: #10a37f; }}
    .button {{ display: inline-block; padding: 12px 24px; background-color: #10a37f; color: #ffffff; text-decoration: none; border-radius: 4px; margin: 8px 0; }}
    .footer {{ font-size: 12px; color: #aaaaaa; margin-top: 24px; text-align: right; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Benvenuto in {app_name}!</h1>
    <p>Ciao,</p>
    <p>&Egrave; stato creato un account per te su <strong>{app_name}</strong>. Puoi accedere con le credenziali qui sotto.</p>

    <div class="box">
      <p><strong>Email:</strong> <span class="credential">{email}</span></p>
      <p><strong>Password temporanea:</strong> <span class="credential">{password}</span></p>
    </div>

    <p style="text-align: center;">
      <a href="{login_url}" class="button">Accedi a {app_name}</a>
    </p>

    <p>Ti consigliamo di cambiare la password appena possibile usando <a href="{reset_url}" style="color: #10a37f;">"Password dimenticata"</a> o le impostazioni del profilo.</p>

    <p>A presto,<br>Il team di {app_name}</p>

    <div class="footer">&copy; {year} {app_name}. Tutti i diritti riservati.</div>
  </div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crea un utente LibreChat e invia le credenziali via email."
    )
    parser.add_argument("email", help="Email dell'utente da creare")
    parser.add_argument("--name", help="Nome visualizzato (default: parte prima di @)")
    parser.add_argument("--username", help="Username (default: parte prima di @)")
    parser.add_argument("--password", help="Password (default: generata automaticamente)")
    parser.add_argument(
        "--env-file",
        default="librechat/librechat.env",
        help="Path del file .env di LibreChat (default: librechat/librechat.env)",
    )
    parser.add_argument(
        "--container",
        default="igr-librechat",
        help="Nome del container LibreChat (default: igr-librechat)",
    )
    parser.add_argument(
        "--resend-api-key",
        help="API key Resend (default: letta da EMAIL_PASSWORD nel .env)",
    )
    parser.add_argument(
        "--from",
        dest="from_email",
        help="Indirizzo mittente (default: letto da EMAIL_FROM nel .env)",
    )
    parser.add_argument(
        "--from-name",
        help="Nome mittente (default: letto da EMAIL_FROM_NAME nel .env)",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Crea l'utente senza inviare l'email",
    )
    args = parser.parse_args()

    try:
        validate_email(args.email)
    except ValueError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    env = load_env_file(Path(args.env_file))

    defaults = args.email.split("@")[0]
    name = args.name or defaults
    username = args.username or defaults
    password = args.password or generate_password()
    domain = env.get("DOMAIN_CLIENT", "https://chat.matamune.4nk.eu")
    app_name = env.get("APP_TITLE", "LibreChat")
    from_email = args.from_email or env.get("EMAIL_FROM", "matamune@moja-ia.eu")
    from_name = args.from_name or env.get("EMAIL_FROM_NAME", "LibreChat")
    api_key = args.resend_api_key or env.get("EMAIL_PASSWORD")

    if not args.no_email and not api_key:
        print(
            "Errore: API key Resend non trovata. Specifica --resend-api-key o imposta EMAIL_PASSWORD nel .env.",
            file=sys.stderr,
        )
        return 1

    try:
        create_librechat_user(args.email, name, username, password, container=args.container)
    except RuntimeError as exc:
        print(f"Errore durante la creazione dell'utente: {exc}", file=sys.stderr)
        return 1

    print(f"Utente creato: {args.email}")
    print(f"Username: {username}")
    print(f"Password: {password}")

    if args.no_email:
        print("Email non inviata (--no-email).")
        return 0

    html = build_email_html(app_name, domain, args.email, password, 2026)
    subject = f"Benvenuto in {app_name}"

    try:
        message_id = send_resend_email(
            api_key=api_key,
            from_email=from_email,
            from_name=from_name,
            to_email=args.email,
            subject=subject,
            html=html,
        )
        print(f"Email inviata con successo (ID: {message_id})")
    except RuntimeError as exc:
        print(f"Errore durante l'invio dell'email: {exc}", file=sys.stderr)
        print("L'utente è stato creato comunque. Comunica le credenziali manualmente.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
