"""Publica ofertas formatadas na comunidade do WhatsApp via automação de UI
do WhatsApp Desktop (macOS).

Não existe API oficial gratuita/simples pra contas pessoais do WhatsApp —
só a WhatsApp Business Cloud API (Meta), que exige verificação de negócio,
templates pré-aprovados e custo por mensagem. Enquanto isso não compensa,
a alternativa é automação de UI via AppleScript/System Events, no mesmo
espírito do utils/notifications.py.

Pré-requisitos pra isso funcionar:

  1. WhatsApp Desktop aberto e logado o tempo todo — o launchd só garante
     o processo Python (main.py) vivo, não o app do WhatsApp.
  2. Permissão de Acessibilidade concedida ao Python (ou ao Terminal, se
     rodar via launchd) em Ajustes do Sistema > Privacidade e Segurança >
     Acessibilidade.
  3. WHATSAPP_COMMUNITY_NAME no .env batendo EXATAMENTE com o nome da
     conversa como aparece na lista lateral do WhatsApp Desktop.

Isso é automação não-oficial (dirige a UI, não uma API) — sujeita aos
termos de uso do WhatsApp e bem mais frágil que o publish_offer do
Telegram (depende de timing e da UI do app não mudar de layout).

Abre o chat clicando direto no botão da conversa na lista lateral (por
descrição de acessibilidade), em vez de simular um atalho de busca — o
app nativo do WhatsApp pra Mac não expõe um atalho de teclado real pra
busca (Cmd+F é "Tela Cheia" nesse app) e sua árvore de acessibilidade
não expõe um AXTextField utilizável pra digitar ali. Por isso o alvo
(WHATSAPP_COMMUNITY_NAME) só é encontrado se a conversa estiver
carregada na lista visível — **fixe a conversa (pin) na lista lateral**
pra garantir que ela sempre apareça, independente de outras conversas
ficarem mais recentes. Os delays abaixo são um ponto de partida; se a
automação errar o alvo (colar antes do chat abrir, etc.), o primeiro
ajuste é aumentá-los.

Roda como canal secundário/best-effort: uma falha aqui nunca desfaz nem
bloqueia a publicação no Telegram, que já aconteceu antes (ver
orchestrator.py) — só fica de fora daquele ciclo e tenta de novo no
próximo, já que a oferta não é marcada como "publicada no WhatsApp" em
lugar nenhum (não há dedupe por canal, só por oferta).
"""

from __future__ import annotations

import logging
import subprocess

import config
from utils.retry import with_retry

logger = logging.getLogger(__name__)

# Delays entre passos da automação (segundos). O WhatsApp Desktop não
# expõe nenhum evento de "terminei de carregar/buscar" pra automação —
# por isso espera fixa, calibrada manualmente na sua máquina.
DELAY_APP_ACTIVATE = 0.8
DELAY_AFTER_OPEN_CHAT = 1.0
DELAY_AFTER_PASTE = 0.4

# Tecla Return (key code do teclado ANSI, independente de layout/idioma).
_KEY_CODE_RETURN = 36


def format_offer_message(
    title: str,
    original_price: float,
    discounted_price: float,
    discount_percent: float,
    link: str,
) -> str:
    """Formata em markdown do WhatsApp (*negrito*, ~riscado~) — diferente do
    Telegram, o WhatsApp não interpreta HTML."""
    return (
        f"🔥 *{title}*\n\n"
        f"De: ~£{original_price:.2f}~\n"
        f"Por: *£{discounted_price:.2f}*\n"
        f"💥 *{discount_percent:.0f}% OFF*\n\n"
        f"🔗 {link}"
    )


def _applescript_string(value: str) -> str:
    # AppleScript exige aspas duplas pra literais de string — escapa barras
    # invertidas e aspas duplas (mesma lógica de utils/notifications.py).
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_applescript(chat_name: str, text: str) -> str:
    # Clipboard é setado por último, o mais perto possível do paste, pra
    # minimizar a janela de corrida com qualquer outra coisa que também
    # escreva na área de transferência enquanto a automação roda (já
    # aconteceu: uma cópia feita em outro app no meio da execução acabou
    # sendo colada em vez do texto da oferta).
    return f"""
tell application "WhatsApp" to activate
delay {DELAY_APP_ACTIVATE}

tell application "System Events"
    tell process "WhatsApp"
        set targetButton to missing value
        repeat with el in (entire contents of window 1)
            try
                if role of el is "AXButton" and description of el contains {_applescript_string(chat_name)} then
                    set targetButton to el
                    exit repeat
                end if
            end try
        end repeat

        if targetButton is missing value then
            error "Conversa " & {_applescript_string(chat_name)} & " não encontrada na lista visível — fixe (pin) a conversa na lista lateral do WhatsApp."
        end if

        click targetButton
        delay {DELAY_AFTER_OPEN_CHAT}

        set the clipboard to {_applescript_string(text)}
        keystroke "v" using {{command down}}
        delay {DELAY_AFTER_PASTE}
        key code {_KEY_CODE_RETURN}
    end tell
end tell
""".strip()


def _send_via_ui_automation(chat_name: str, text: str) -> None:
    script = _build_applescript(chat_name, text)
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"osascript falhou (código {result.returncode}): {result.stderr.strip()}"
        )


@with_retry(exceptions=(RuntimeError,))
def _send_with_retry(chat_name: str, text: str) -> None:
    _send_via_ui_automation(chat_name, text)


def publish_offer(
    title: str,
    original_price: float,
    discounted_price: float,
    discount_percent: float,
    link: str,
) -> None:
    if not config.WHATSAPP_ENABLED:
        logger.debug("WHATSAPP_ENABLED=false — pulando publicação no WhatsApp.")
        return

    if not config.WHATSAPP_COMMUNITY_NAME:
        logger.warning(
            "WHATSAPP_COMMUNITY_NAME não configurado — pulando publicação no WhatsApp."
        )
        return

    text = format_offer_message(title, original_price, discounted_price, discount_percent, link)
    _send_with_retry(config.WHATSAPP_COMMUNITY_NAME, text)
    logger.info("Oferta publicada no WhatsApp (%s): %s", config.WHATSAPP_COMMUNITY_NAME, title)
