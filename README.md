# affiliate-bot

[![affiliate-marketing](https://img.shields.io/badge/affiliate--marketing-0969DA?style=flat-square)](https://github.com/topics/affiliate-marketing)
[![aliexpress](https://img.shields.io/badge/aliexpress-0969DA?style=flat-square)](https://github.com/topics/aliexpress)
[![automation](https://img.shields.io/badge/automation-0969DA?style=flat-square)](https://github.com/topics/automation)
[![python](https://img.shields.io/badge/python-0969DA?style=flat-square)](https://github.com/topics/python)
[![sqlite](https://img.shields.io/badge/sqlite-0969DA?style=flat-square)](https://github.com/topics/sqlite)
[![telegram-bot](https://img.shields.io/badge/telegram--bot-0969DA?style=flat-square)](https://github.com/topics/telegram-bot)

Bot que garimpa ofertas de eletrônicos/tech na [AliExpress Affiliate API](https://portals.aliexpress.com/), prioriza as com maior potencial de conversão em tráfego pago e publica automaticamente num canal do Telegram — sem repetir a mesma oferta duas vezes.

## Como funciona

1. **Busca** — varre uma lista de palavras-chave de nicho (setup gamer, consoles, smart home, áudio/wearables, criadores de conteúdo) na AliExpress.
2. **Filtra** — descarta o que não bate com o nicho e o que não tem desconto mínimo (`MIN_DISCOUNT_PERCENT`).
3. **Pontua** — cada oferta candidata recebe um score (preço na faixa de "compra por impulso", desconto, apelo visual da categoria) que decide qual publicar primeiro.
4. **Deduplica** — checa contra um SQLite local (`database/affiliate_bot.db`) pra nunca publicar o mesmo item duas vezes.
5. **Publica** — envia a oferta escolhida pro Telegram e grava no banco.

Um ciclo publica no máximo 1 oferta e se repete em loop (`main.py`), no intervalo definido por `LOOP_INTERVAL_SECONDS`.

Também tem um gerador de **landing page estática** (`scripts/generate_landing_page.py`) que lista as ofertas já publicadas ordenadas pelo mesmo score.

## Estrutura

```
config.py                  # config central — tudo lê daqui, não de os.environ direto
main.py                    # loop principal (busca -> pontua -> publica -> dorme)
modules/
  aliexpress_client.py     # busca e filtro de ofertas na AliExpress
  orchestrator.py          # liga busca + score + publicação + persistência
  telegram_publisher.py    # envio da mensagem formatada pro Telegram
database/
  db_manager.py            # SQLite: dedup, persistência, view/fórmula de score
scripts/
  generate_landing_page.py # gera dist/index.html a partir de templates/landing.html.j2
  health_check.py          # checa se o bot tá rodando e notifica (macOS)
launchd/                   # plists pra rodar como serviço no macOS
tests/                     # suíte pytest
```

## Setup

Requer Python 3.11+.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# preencher .env com as credenciais reais (ver seção abaixo)
```

### Variáveis de ambiente (`.env`)

| Variável | Descrição |
|---|---|
| `ALIEXPRESS_APP_KEY` / `ALIEXPRESS_APP_SECRET` | credenciais do Portal de Afiliados AliExpress |
| `ALIEXPRESS_TRACKING_ID` | tracking ID pra garantir atribuição de comissão |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | bot e canal de destino no Telegram |
| `MIN_DISCOUNT_PERCENT` | desconto mínimo pra uma oferta ser considerada (padrão 30) |
| `MAX_OFFERS_PER_KEYWORD` | teto de publicações por palavra-chave por ciclo (padrão 3) |
| `LOOP_INTERVAL_SECONDS` | intervalo entre ciclos em `main.py` (padrão 7200 = 2h) |

Nunca commitar o `.env` real — está no `.gitignore`.

## Rodando

```bash
python main.py          # loop contínuo
# ou, via Docker:
docker compose up
```

## Deploy (macOS via launchd)

Os plists em `launchd/` sobem o bot como serviço (`RunAtLoad` + `KeepAlive`, com o loop de intervalo controlado pelo próprio `main.py`) e um health-check periódico que notifica pelo Centro de Notificações do macOS.

```bash
launchctl bootstrap gui/$(id -u) launchd/com.miguelcamilo.affiliatebot.plist
launchctl bootstrap gui/$(id -u) launchd/com.miguelcamilo.affiliatebot.healthcheck.plist
```

## Testes

```bash
pytest
```
