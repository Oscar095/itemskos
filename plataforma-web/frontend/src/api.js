// Cliente HTTP de la app. La sesion viaja en una cookie HttpOnly (same-origin
// via el proxy /api de Vite), asi que no hay token que inyectar: solo se
// normalizan los errores y un 401 manda al login.
let alExpirar = () => {};
export const enExpiracion = (fn) => { alExpirar = fn; };

export async function pedir(url, opciones = {}) {
  const { json, ...resto } = opciones;
  const r = await fetch(url, {
    credentials: "same-origin",
    ...resto,
    // X-KOS: el backend rechaza toda escritura sin este encabezado (anti-CSRF).
    headers: { "X-KOS": "1", ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...resto.headers },
    body: json !== undefined ? JSON.stringify(json) : resto.body,
  });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && !url.startsWith("/api/auth/login")) alExpirar();
  if (!r.ok) {
    // FastAPI manda `detail` como texto (400/403/409) o como lista (422).
    const d = Array.isArray(j.detail) ? j.detail.map((x) => x.msg).join("; ") : j.detail;
    const e = new Error(d || `HTTP ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return j;
}
