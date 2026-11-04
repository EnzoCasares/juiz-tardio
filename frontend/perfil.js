const USER_STORAGE_KEY = 'assistente_user_id';
let USER_ID = localStorage.getItem(USER_STORAGE_KEY);
if (!USER_ID) {
  USER_ID = window.crypto && crypto.randomUUID
    ? crypto.randomUUID()
    : 'sess-' + Math.random().toString(36).slice(2, 10);
  localStorage.setItem(USER_STORAGE_KEY, USER_ID);
}

const ENDPOINT = '/perfil';

const API_BASE = window.ASSESSOR_API_BASE;

const els = {
  badge: document.getElementById('user-badge'),
  renda: document.getElementById('renda_mensal'),
  objetivo: document.getElementById('objetivo'),
  tolerancia: document.getElementById('tolerancia_risco'),
  preferencias: document.getElementById('preferencias'),
  status: document.getElementById('status'),
  submit: document.getElementById('submit'),
  echo: document.getElementById('echo'),
  echoBody: document.getElementById('echo-body'),
};

els.badge.textContent = USER_ID;

function setStatus(text, kind) {
  els.status.textContent = text;
  els.status.className = 'sheet__status' + (kind ? ` is-${kind}` : '');
}

function montarPayload() {
  const renda = els.renda.value.trim();

  return {
    user_id: USER_ID,
    renda_mensal: renda === '' ? null : Number(renda),
    objetivo: els.objetivo.value.trim() || null,
    tolerancia_risco: els.tolerancia.value || null,
    preferencias: els.preferencias.value.trim() || null,
  };
}

function mostrarResposta(dados) {
  els.echoBody.textContent = JSON.stringify(dados, null, 2);
  els.echo.hidden = false;
}

async function salvar() {
  const payload = montarPayload();

  els.submit.disabled = true;
  setStatus('enviando...');
  els.echo.hidden = true;

  try {
    const resposta = await fetch(API_BASE + ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    let corpo = null;
    try {
      corpo = await resposta.json();
    } catch {
      corpo = { detail: 'a resposta não era JSON' };
    }

    if (!resposta.ok) {
      setStatus(`a api recusou (${resposta.status})`, 'error');
      mostrarResposta(corpo);
      return;
    }

    setStatus('perfil salvo', 'ok');
    mostrarResposta(corpo);
  } catch (erro) {
    setStatus('não consegui falar com a api', 'error');
    mostrarResposta({ erro: String(erro) });
  } finally {
    els.submit.disabled = false;
  }
}

els.submit.addEventListener('click', salvar);
