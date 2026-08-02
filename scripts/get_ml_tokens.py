"""Uso único: troca o authorization code do Mercado Livre pelo primeiro
access_token + refresh_token e grava os dois no .env.

Lê ML_CLIENT_ID e ML_CLIENT_SECRET do .env (nunca aceita segredo por
argumento de linha de comando, pra não vazar em histórico de shell/logs).
Não imprime tokens no terminal — só confirma sucesso e mostra metadados
não sensíveis (expiração, escopo).

Exemplo:
    python scripts/get_ml_tokens.py \\
        --code "TG-xxxxxxxx" \\
        --redirect-uri "https://www.google.com/callback"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def update_env_var(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    env_path.write_text("\n".join(lines) + "\n")


def exchange_code_for_tokens(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode()

    request = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"Erro HTTP {exc.code} ao trocar o code por token:", file=sys.stderr)
        print(body, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True, help="authorization code (TG-...) obtido no redirect")
    parser.add_argument("--redirect-uri", required=True, help="a MESMA redirect_uri cadastrada na aplicação")
    args = parser.parse_args()

    if not config.ML_CLIENT_ID or not config.ML_CLIENT_SECRET:
        print(
            "ML_CLIENT_ID e/ou ML_CLIENT_SECRET estão vazios no .env. "
            "Preencha os dois primeiro e rode de novo.",
            file=sys.stderr,
        )
        sys.exit(1)

    token_data = exchange_code_for_tokens(
        client_id=config.ML_CLIENT_ID,
        client_secret=config.ML_CLIENT_SECRET,
        code=args.code,
        redirect_uri=args.redirect_uri,
    )

    env_path = config.BASE_DIR / ".env"
    update_env_var(env_path, "ML_ACCESS_TOKEN", token_data["access_token"])
    update_env_var(env_path, "ML_REFRESH_TOKEN", token_data["refresh_token"])

    print("Tokens salvos em .env com sucesso (valores não exibidos no terminal).")
    print(f"scope: {token_data.get('scope')}")
    print(f"expires_in: {token_data.get('expires_in')} segundos")
    print(f"user_id: {token_data.get('user_id')}")


if __name__ == "__main__":
    main()
