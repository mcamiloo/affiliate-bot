// Recebe o cadastro do formulário de opt-in da landing page e repassa
// pro Brevo via fluxo de double opt-in — nunca grava nada localmente
// (o Mac não é alcançável pela internet). Único ponto do projeto que
// roda fora de Python: Netlify Functions não suportam Python, só
// Node/TypeScript e Go, então esta function é propositalmente pequena
// e sem lógica de negócio além de validar e repassar pro Brevo.

const crypto = require("crypto");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Mesmo HMAC de utils/unsubscribe.py (compute_unsub_token) — os dois
// lados têm que usar o mesmo NEWSLETTER_UNSUB_SECRET. Gravado como
// atributo do contato aqui, e referenciado no template do email via
// {{ contact.UNSUB_TOKEN }} pro link de descadastro próprio (que convive
// com o {{ unsubscribe }} nativo do Brevo, não o substitui).
function computeUnsubToken(email, secret) {
  return crypto.createHmac("sha256", secret).update(email.trim().toLowerCase()).digest("hex");
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ error: "Method not allowed" }) };
  }

  let payload;
  try {
    payload = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  const email = (payload.email || "").trim().toLowerCase();
  const consent = payload.consent === true;

  if (!EMAIL_RE.test(email)) {
    return { statusCode: 400, body: JSON.stringify({ error: "Please enter a valid email address." }) };
  }
  if (!consent) {
    return { statusCode: 400, body: JSON.stringify({ error: "Consent is required to subscribe." }) };
  }

  const { BREVO_API_KEY, BREVO_LIST_ID, BREVO_DOI_TEMPLATE_ID, BREVO_DOI_REDIRECT_URL, NEWSLETTER_UNSUB_SECRET } =
    process.env;
  if (!BREVO_API_KEY || !BREVO_LIST_ID || !BREVO_DOI_TEMPLATE_ID || !NEWSLETTER_UNSUB_SECRET) {
    console.error(
      "Env vars ausentes na Netlify (BREVO_API_KEY/BREVO_LIST_ID/BREVO_DOI_TEMPLATE_ID/NEWSLETTER_UNSUB_SECRET)"
    );
    return { statusCode: 500, body: JSON.stringify({ error: "Server misconfigured." }) };
  }

  // IP do submitter, guardado como atributo do contato — prova adicional
  // de consentimento (UK GDPR/PECR), além do timestamp.
  const ip = (event.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";

  const response = await fetch("https://api.brevo.com/v3/contacts/doubleOptinConfirmation", {
    method: "POST",
    headers: {
      "api-key": BREVO_API_KEY,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      email,
      includeListIds: [Number(BREVO_LIST_ID)],
      templateId: Number(BREVO_DOI_TEMPLATE_ID),
      redirectionUrl: BREVO_DOI_REDIRECT_URL || undefined,
      attributes: {
        CONSENT_TIMESTAMP: new Date().toISOString(),
        CONSENT_IP: ip,
        UNSUB_TOKEN: computeUnsubToken(email, NEWSLETTER_UNSUB_SECRET),
      },
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    console.error("Brevo doubleOptinConfirmation falhou:", response.status, detail);
    return { statusCode: 502, body: JSON.stringify({ error: "Could not subscribe right now — please try again." }) };
  }

  return { statusCode: 200, body: JSON.stringify({ ok: true }) };
};
