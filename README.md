# affiliate-bot

[![affiliate-marketing](https://img.shields.io/badge/affiliate--marketing-0969DA?style=flat-square)](https://github.com/topics/affiliate-marketing)
[![aliexpress](https://img.shields.io/badge/aliexpress-0969DA?style=flat-square)](https://github.com/topics/aliexpress)
[![automation](https://img.shields.io/badge/automation-0969DA?style=flat-square)](https://github.com/topics/automation)
[![python](https://img.shields.io/badge/python-0969DA?style=flat-square)](https://github.com/topics/python)
[![sqlite](https://img.shields.io/badge/sqlite-0969DA?style=flat-square)](https://github.com/topics/sqlite)
[![telegram-bot](https://img.shields.io/badge/telegram--bot-0969DA?style=flat-square)](https://github.com/topics/telegram-bot)

Bot que garimpa ofertas de eletrônicos/tech na [AliExpress Affiliate API](https://portals.aliexpress.com/), prioriza as com maior potencial de conversão em tráfego pago e publica automaticamente num canal do Telegram (e, opcionalmente, espelhado numa comunidade do WhatsApp) — sem repetir a mesma oferta duas vezes.

## Como funciona

1. **Busca** — varre uma lista de palavras-chave de nicho (setup gamer, consoles, smart home, áudio/wearables, criadores de conteúdo) na AliExpress.
2. **Filtra** — descarta o que não bate com o nicho e o que não tem desconto mínimo (`MIN_DISCOUNT_PERCENT`).
3. **Pontua** — cada oferta candidata recebe um score (preço na faixa de "compra por impulso", desconto, apelo visual da categoria) que decide qual publicar primeiro.
4. **Deduplica** — checa contra um SQLite local (`database/affiliate_bot.db`) pra nunca publicar o mesmo item duas vezes.
5. **Publica** — envia a oferta escolhida pro Telegram (e, se `WHATSAPP_ENABLED=true`, replica pra comunidade do WhatsApp logo em seguida) e grava no banco.

Um ciclo publica no máximo 1 oferta e se repete em loop (`main.py`), no intervalo definido por `LOOP_INTERVAL_SECONDS`.

Também tem um gerador de **landing page estática** (`scripts/generate_landing_page.py`) que lista as ofertas já publicadas ordenadas pelo mesmo score, uma **newsletter diária por email** (ver [Newsletter](#newsletter-email)) e um **painel de administração remoto** (ver [Painel de administração](#painel-de-administração)).

## Estrutura

```
config.py                  # config central — tudo lê daqui, não de os.environ direto
main.py                    # loop principal (busca -> pontua -> publica -> dorme)
modules/
  aliexpress_client.py     # busca e filtro de ofertas na AliExpress
  orchestrator.py          # liga busca + score + publicação + persistência
  telegram_publisher.py    # envio da mensagem formatada pro Telegram
  whatsapp_publisher.py    # espelha a oferta na comunidade do WhatsApp (automação de UI, opcional)
  brevo_client.py          # cliente HTTP do Brevo (contatos, campanhas, webhook, teste de envio)
  newsletter.py            # monta o HTML da newsletter diária a partir das ofertas
database/
  db_manager.py            # SQLite: dedup, persistência, view/fórmula de score, drafts, eventos de email
scripts/
  generate_landing_page.py # gera dist/index.html a partir de templates/landing.html.j2
  health_check.py          # checa se o bot tá rodando e notifica (macOS)
  send_test_whatsapp_offer.py # teste manual pra calibrar a automação do WhatsApp
  newsletter_scheduler.py  # sorteia horário diário, gera rascunho, sincroniza assinantes
  approval_panel.py        # painel Flask de administração remota (login, fila, analytics)
  write_widget_snapshot.py # gera o JSON que os widgets (Mac/iPad) leem
  setup_brevo_webhook.py   # registra (uma vez) o webhook de analytics no Brevo
  backfill_unsub_tokens.py # preenche o token de descadastro pra assinantes antigos
netlify/functions/
  subscribe.js             # recebe o cadastro da landing page (Node — Netlify Functions não roda Python)
macos-widget/               # widget nativo (macOS) + script do widget do iPad (Scriptable)
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
| `WHATSAPP_ENABLED` | liga/desliga o espelhamento no WhatsApp (padrão `false`) |
| `WHATSAPP_COMMUNITY_NAME` | nome exato da comunidade/conversa no WhatsApp Desktop |
| `MIN_DISCOUNT_PERCENT` | desconto mínimo pra uma oferta ser considerada (padrão 30) |
| `MAX_OFFERS_PER_KEYWORD` | teto de publicações por palavra-chave por ciclo (padrão 3) |
| `LOOP_INTERVAL_SECONDS` | intervalo entre ciclos em `main.py` (padrão 7200 = 2h) |
| `BREVO_API_KEY` / `BREVO_LIST_ID` / `BREVO_DOI_TEMPLATE_ID` | credenciais e IDs do Brevo pra newsletter (ver [Newsletter](#newsletter-email)) |
| `NEWSLETTER_UNSUB_SECRET` | chave do HMAC do link de descadastro próprio — **precisa ser a mesma** nas env vars da Netlify |
| `BREVO_WEBHOOK_SECRET` | segredo enviado pelo Brevo num header em todo evento de webhook (analytics) |
| `APPROVAL_PANEL_SECRET_KEY` / `WIDGET_API_TOKEN` | segredos do painel de administração e da API dos widgets |
| `APPROVAL_PANEL_PUBLIC_URL` | URL pública de onde o painel é alcançável hoje (Tailscale Funnel) |

Nunca commitar o `.env` real — está no `.gitignore`. Ver `.env.example` pra lista completa (inclui endereço físico exigido por lei no rodapé do email, janela de envio, etc.).

## Rodando

```bash
python main.py          # loop contínuo
# ou, via Docker:
docker compose up
```

## WhatsApp (opcional)

Não há API oficial simples/gratuita pra contas pessoais do WhatsApp — o espelhamento usa automação de UI do WhatsApp Desktop via `osascript`/System Events (`modules/whatsapp_publisher.py`), não uma API. É mais frágil que o Telegram e sujeita aos termos de uso do WhatsApp (uso pessoal moderado tende a passar batido; volume alto ou padrão muito robótico corre risco de restrição).

Setup:

1. Deixe o WhatsApp Desktop aberto e logado (precisa continuar aberto pro bot rodar via launchd).
2. Conceda permissão de Acessibilidade ao Python em Ajustes do Sistema > Privacidade e Segurança > Acessibilidade.
3. Preencha `WHATSAPP_COMMUNITY_NAME` no `.env` com o nome **exato** da conversa/comunidade como aparece na lista do WhatsApp.
4. Rode `python scripts/send_test_whatsapp_offer.py` algumas vezes e ajuste as constantes `DELAY_*` no topo de `modules/whatsapp_publisher.py` até a automação abrir o chat certo e mandar a mensagem inteira, de forma confiável.
5. Só então mude `WHATSAPP_ENABLED=true` no `.env` de produção.

## Newsletter (email)

Newsletter diária com as ofertas de maior score, enviada via [Brevo](https://www.brevo.com/), com cadastro por double opt-in (formulário na landing page → `netlify/functions/subscribe.js` → Brevo confirma por email antes de entrar na lista).

- `scripts/newsletter_scheduler.py` (launchd, 24/7) sorteia um horário diário dentro de uma janela UK configurável, gera o conteúdo (`modules/newsletter.py`) e cria a campanha no Brevo **como rascunho** — nunca envia sozinho.
- Aprovação manual acontece no [painel de administração](#painel-de-administração) (`/queue`): aprovar agenda/envia de fato no Brevo, rejeitar cancela a campanha.
- **Descadastro**: cada email tem dois links no rodapé — o `{{ unsubscribe }}` nativo do Brevo, e um link próprio (hash HMAC por destinatário, `utils/unsubscribe.py`) que atualiza a tabela local `subscribers` na hora e bloqueia o contato no Brevo, sem esperar o próximo sync periódico.
- **Analytics**: um webhook do Brevo (registrado uma vez via `scripts/setup_brevo_webhook.py`) reporta entregue/aberto/clicado/bounce em tempo real pra `/api/brevo-webhook`, guardado em `email_events` e mostrado em `/newsletter/stats`. Autenticado por um header secreto (não na URL) + allowlist do IP publicado pelo Brevo — o Brevo não assina o payload dos webhooks.
- **Email avulso**: `/newsletter/compose` deixa colar ou subir um `.html` pronto, com um botão "Mandar teste" (só pra `NEWSLETTER_TEST_EMAIL`) antes de entrar na mesma fila de aprovação dos automáticos.

## Painel de administração

`scripts/approval_panel.py` — Flask, bind exclusivo em `127.0.0.1`. Alcançável de fora só via [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) (`APPROVAL_PANEL_PUBLIC_URL`), pensado pra futuramente ser proxiado em `ombrotechwear.co.uk/sistema` via Netlify (redirect ainda não configurado). Exige login (usuário único, tabela `admin_users`, senha padrão forçada a trocar no primeiro acesso).

Páginas: `/home` (status dos serviços + resumo), `/queue` (aprovação de emails), `/offers` (publicadas, com opção de ocultar), `/schedule` (horários da newsletter), `/subscribers` (busca + última interação), `/newsletter/stats` (analytics por campanha), `/newsletter/compose` (email avulso).

```bash
launchctl bootstrap gui/$(id -u) launchd/com.miguelcamilo.affiliatebot.panel.plist
```

## Widgets (macOS + iPad)

`macos-widget/` — widget nativo WidgetKit pro macOS (Xcode, gerado via `xcodegen generate` a partir de `project.yml`) mostrando o mesmo status do painel na área de trabalho, com botão pra rodar um ciclo manual.

A extensão roda em App Sandbox (exigência do WidgetKit) e por isso não lê o SQLite/log direto: `scripts/write_widget_snapshot.py` (launchd, a cada poucos minutos) materializa `state/widget_snapshot.json`, que o widget só tem permissão de ler via entitlement. O botão "Rodar ciclo agora" escreve num arquivo-gatilho que outro launchd agent (`WatchPaths`) observa pra rodar o ciclo de verdade fora do sandbox.

O widget do **iPad** (`macos-widget/ipad-widget/OmbroPanel.js`) usa o app grátis [Scriptable](https://scriptable.app/) em vez de um app nativo (sem conta paga da Apple Developer Program, um app sideloaded expira em 7 dias) — busca os dados via duas rotas autenticadas por token no painel (`/api/widget-snapshot`, `/api/cycle/run`), alcançáveis pela URL pública do Tailscale Funnel.

## Deploy (macOS via launchd)

Os plists em `launchd/` sobem cada peça como serviço:

| Plist | O que roda |
|---|---|
| `com.miguelcamilo.affiliatebot.plist` | bot principal (`main.py`, `RunAtLoad` + `KeepAlive`) |
| `com.miguelcamilo.affiliatebot.healthcheck.plist` | checagem periódica com notificação no macOS |
| `com.miguelcamilo.affiliatebot.newsletter.plist` | `newsletter_scheduler.py`, 24/7 |
| `com.miguelcamilo.affiliatebot.panel.plist` | painel de administração (`approval_panel.py`) |
| `com.miguelcamilo.affiliatebot.widgetsnapshot.plist` | atualiza o JSON que os widgets leem, a cada 5min |
| `com.miguelcamilo.affiliatebot.widgettrigger.plist` | `WatchPaths` — roda um ciclo quando o widget pede |

```bash
launchctl bootstrap gui/$(id -u) launchd/com.miguelcamilo.affiliatebot.plist
launchctl bootstrap gui/$(id -u) launchd/com.miguelcamilo.affiliatebot.healthcheck.plist
```

## Testes

```bash
pytest
```
