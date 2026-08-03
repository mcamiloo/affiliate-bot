// Externo de propósito (não é .html.j2) — permite um Content-Security-Policy
// sem 'unsafe-inline' pra script-src no netlify.toml, bem mais forte contra
// XSS do que script inline. Sem nenhuma variável Jinja aqui — tudo dinâmico
// vem do DOM (data-count-to), por isso dá pra ser um arquivo estático puro.

var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Highlight do card de assinatura ao chegar via âncora "Email".
document.querySelectorAll('a[href="#subscribe"]').forEach(function (link) {
  link.addEventListener('click', function () {
    var section = document.getElementById('subscribe');
    section.classList.remove('pulse-target');
    void section.offsetWidth; // força reflow pra poder re-disparar a animação
    section.classList.add('pulse-target');
  });
});

// Contador subindo até o total real de ofertas — só estética, sem
// nenhuma lógica de negócio (o número final já vem pronto do servidor).
document.querySelectorAll('[data-count-to]').forEach(function (el) {
  var target = parseInt(el.getAttribute('data-count-to'), 10) || 0;
  if (prefersReducedMotion || target === 0) { el.textContent = target; return; }
  var start = performance.now();
  var duration = 900;
  function tick(now) {
    var progress = Math.min((now - start) / duration, 1);
    el.textContent = Math.round(progress * target);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
});

// Cards aparecem com fade+slide conforme entram na tela, em vez de
// tudo de uma vez — leve, cancelado de vez pra quem prefere menos movimento.
var cards = document.querySelectorAll('.card');
if (prefersReducedMotion || !('IntersectionObserver' in window)) {
  cards.forEach(function (card) { card.style.opacity = 1; card.style.transform = 'none'; });
} else {
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry, i) {
      if (entry.isIntersecting) {
        setTimeout(function () { entry.target.classList.add('is-visible'); }, (i % 4) * 60);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
  cards.forEach(function (card) { observer.observe(card); });
}

document.getElementById('subscribe-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  const form = event.target;
  const messageEl = document.getElementById('form-message');
  const button = form.querySelector('button');
  const email = form.email.value.trim();
  const consent = form.consent.checked;

  messageEl.className = 'form-message visible';
  if (!consent) {
    messageEl.textContent = 'Please check the consent box to subscribe.';
    messageEl.classList.add('error');
    return;
  }

  button.disabled = true;
  button.textContent = 'Subscribing…';

  try {
    const response = await fetch('/.netlify/functions/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, consent }),
    });

    if (response.ok) {
      messageEl.textContent = 'Nearly there! Check your inbox to confirm your subscription.';
      messageEl.classList.add('success');
      form.reset();
    } else {
      const data = await response.json().catch(() => ({}));
      messageEl.textContent = data.error || 'Something went wrong — please try again.';
      messageEl.classList.add('error');
    }
  } catch (err) {
    messageEl.textContent = 'Network error — please try again.';
    messageEl.classList.add('error');
  } finally {
    button.disabled = false;
    button.textContent = 'Subscribe';
  }
});
