// Widget do iPad (app Scriptable, grátis na App Store) — espelha o
// widget nativo do Mac (macos-widget/OmbroPanelWidget/), mas busca os
// dados por rede em vez de ler arquivo local, porque iPad e Mac são
// sandboxes completamente separados. Consome as rotas /api/* de
// scripts/approval_panel.py (protegidas por WIDGET_API_TOKEN, não por
// cookie de sessão) através do domínio público do Tailscale Funnel.
//
// SETUP: troque o valor de TOKEN abaixo pelo WIDGET_API_TOKEN real do
// .env do Mac antes de colar este script no app Scriptable — NUNCA
// commite esse arquivo com o token real preenchido.
//
// Toque no botão "Rodar ciclo agora" (só aparece no tamanho grande, igual
// no Mac) reabre este mesmo script via deep link (scriptable:///run/...)
// com ?run=1 — é a forma padrão do Scriptable de simular um botão dentro
// de um widget (ListWidget não suporta múltiplos alvos de toque nativos
// como um WidgetKit de verdade).

const API_BASE = "https://miguels-macbook-pro.tail598791.ts.net";
const TOKEN = "__WIDGET_API_TOKEN__";

async function fetchSnapshot() {
  const req = new Request(`${API_BASE}/api/widget-snapshot`);
  req.headers = { Authorization: `Bearer ${TOKEN}` };
  req.timeoutInterval = 10;
  const json = await req.loadJSON();
  // loadJSON() só lança erro em falha de rede, não em 401/503 — sem
  // checar o status manualmente, um token errado renderizaria
  // {"error": "unauthorized"} como se fosse um snapshot de verdade.
  if (req.response.statusCode !== 200) {
    throw new Error(`HTTP ${req.response.statusCode}: ${json.error ?? "erro desconhecido"}`);
  }
  return json;
}

async function runCycleNow() {
  const req = new Request(`${API_BASE}/api/cycle/run`);
  req.method = "POST";
  req.headers = { Authorization: `Bearer ${TOKEN}` };
  req.timeoutInterval = 10;
  await req.loadJSON();
  if (req.response.statusCode !== 200) {
    throw new Error(`HTTP ${req.response.statusCode}`);
  }
}

function addStatusDot(stack, running) {
  const dot = stack.addText("●");
  dot.textColor = running ? Color.green() : Color.red();
  dot.font = Font.systemFont(10);
}

function buildErrorWidget(error) {
  const w = new ListWidget();
  const text = w.addText(`OmbroPanel\nErro: ${error?.message ?? error}`);
  text.font = Font.systemFont(11);
  text.textColor = Color.gray();
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
  return w;
}

function buildWidget(snapshot) {
  const w = new ListWidget();
  w.backgroundColor = Color.dynamic(Color.white(), new Color("1c1c1e"));

  const title = w.addText("OmbroPanel");
  title.font = Font.boldSystemFont(12);
  title.textColor = Color.gray();
  w.addSpacer(6);

  const statusRow = w.addStack();
  statusRow.spacing = 6;
  addStatusDot(statusRow, snapshot.main_bot_running);
  addStatusDot(statusRow, snapshot.newsletter_running);
  addStatusDot(statusRow, !snapshot.whatsapp_enabled || snapshot.whatsapp_app_running);
  w.addSpacer(8);

  const big = w.addText(`${snapshot.offers_today}`);
  big.font = Font.heavySystemFont(28);

  const label = w.addText("ofertas hoje");
  label.font = Font.systemFont(10);
  label.textColor = Color.gray();
  w.addSpacer(2);

  const weekLabel = w.addText(`${snapshot.offers_week} essa semana`);
  weekLabel.font = Font.systemFont(10);
  weekLabel.textColor = Color.gray();

  if (config.widgetFamily !== "small") {
    w.addSpacer(8);
    const offersTitle = w.addText("Últimas ofertas");
    offersTitle.font = Font.boldSystemFont(10);
    for (const offer of snapshot.latest_offers.slice(0, 3)) {
      const line = w.addText(`£${offer.price.toFixed(2)} · ${offer.title}`);
      line.font = Font.systemFont(9);
      line.lineLimit = 1;
      w.addSpacer(1);
    }
  }

  if (config.widgetFamily === "large") {
    w.addSpacer(8);
    const button = w.addText("▶ Rodar ciclo agora");
    button.font = Font.boldSystemFont(11);
    button.centerAlignText();
    button.url = `scriptable:///run/${encodeURIComponent(Script.name())}?run=1`;
  }

  w.refreshAfterDate = new Date(Date.now() + 10 * 60 * 1000);
  return w;
}

async function main() {
  // Reentrada via o botão "Rodar ciclo agora" (ver buildWidget) — dispara
  // o ciclo e sai, sem tentar desenhar widget nenhum nessa execução.
  if (args.queryParameters && args.queryParameters.run === "1") {
    await runCycleNow();
    if (!config.runsInWidget) {
      const alert = new Alert();
      alert.title = "Ciclo disparado";
      alert.message = "Pode levar alguns minutos — o widget atualiza sozinho.";
      alert.addAction("OK");
      await alert.presentAlert();
    }
    return;
  }

  let snapshot = null;
  let fetchError = null;
  try {
    snapshot = await fetchSnapshot();
  } catch (error) {
    fetchError = error;
  }

  const widget = snapshot ? buildWidget(snapshot) : buildErrorWidget(fetchError);

  if (config.runsInWidget) {
    Script.setWidget(widget);
  } else {
    await widget.presentLarge();
  }
  Script.complete();
}

await main();
