const origemLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
window.ASSESSOR_API_BASE = location.protocol === "file:" ||
  (origemLocal && location.port !== "8000")
  ? "http://127.0.0.1:8000" : location.origin;

window.erroDaApi = async function (resposta, url, metodo) {
  const texto = await resposta.text();
  let detalhe;
  try {
    const dados = JSON.parse(texto);
    detalhe = dados.detail || dados.resposta || dados.message;
    if (typeof detalhe !== "string") detalhe = JSON.stringify(detalhe);
  } catch {
    detalhe = texto && !texto.trimStart().startsWith("<") ? texto.slice(0, 300) : "";
  }
  return `HTTP ${resposta.status} — ${metodo} ${url}: ${detalhe ||
    "O servidor não enviou um detalhe útil. Abra o Assessor em http://127.0.0.1:8000/."}`;
};
