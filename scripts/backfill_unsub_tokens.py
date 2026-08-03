"""Preenche o atributo UNSUB_TOKEN pra quem já era assinante antes desse
token existir (assinantes novos já ganham isso no cadastro — ver
netlify/functions/subscribe.js). Roda uma vez manualmente, idempotente
(recalcula o mesmo valor sempre pro mesmo email, não faz mal rodar de
novo)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import brevo_client
from utils.unsubscribe import compute_unsub_token


def main() -> None:
    contacts = brevo_client.list_list_contacts()
    print(f"{len(contacts)} contato(s) no Brevo — preenchendo UNSUB_TOKEN...")

    for i, contact in enumerate(contacts, start=1):
        email = contact.get("email")
        if not email:
            continue
        if (contact.get("attributes") or {}).get("UNSUB_TOKEN"):
            continue
        brevo_client.set_contact_attributes(email, {"UNSUB_TOKEN": compute_unsub_token(email)})
        print(f"  [{i}/{len(contacts)}] {email}")
        time.sleep(0.2)  # não martelar a API

    print("Concluído.")


if __name__ == "__main__":
    main()
