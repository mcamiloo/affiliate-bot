"""Token de descadastro próprio — link no rodapé do email, além do
{{ unsubscribe }} nativo do Brevo (os dois convivem, ver
templates/newsletter_email.html.j2).

O token é puramente derivado do email + NEWSLETTER_UNSUB_SECRET — não
precisa ser guardado em lugar nenhum, só recalculado na hora de verificar
um clique. O mesmo HMAC é recalculado em JS por
netlify/functions/subscribe.js (que grava o atributo UNSUB_TOKEN no
contato do Brevo no momento do cadastro) — os dois lados têm que usar o
mesmo NEWSLETTER_UNSUB_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac

import config


def compute_unsub_token(email: str) -> str:
    return hmac.new(
        config.NEWSLETTER_UNSUB_SECRET.encode(),
        email.strip().lower().encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_unsub_token(email: str, token: str) -> bool:
    if not config.NEWSLETTER_UNSUB_SECRET or not token:
        return False
    expected = compute_unsub_token(email)
    return hmac.compare_digest(expected, token)
