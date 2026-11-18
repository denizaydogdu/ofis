// Page token recovery: a POST that gets 403 "invalid token" (the key file was recreated) saves the draft to
// sessionStorage, fetches the page's HTML again for the fresh <meta name="ofis-token"> and retries ONCE.
// Pure helpers (fetch/storage injected) so they can be checked under node. Nothing but 403 "invalid token" retries.
export const TASLAK_ANAHTARI = 'ofis-taslak';

export function tokenGecersiz(status, data) {
  return status === 403 && !!data && data.error === 'invalid token';
}

export function metadanToken(html) {
  const m = /<meta\s+name="ofis-token"\s+content="([^"]*)"/.exec(String(html || ''));
  return m ? m[1] : '';
}

export function taslakKaydet(storage, path, body) {
  try { storage.setItem(TASLAK_ANAHTARI, JSON.stringify({ path, body })); } catch { /* storage unavailable */ }
}

export function taslakSil(storage) {
  try { storage.removeItem(TASLAK_ANAHTARI); } catch { /* storage unavailable */ }
}

// send(token) -> {status, data}; fetchHtml() -> html text; returns {res, token}
export async function tekrarla(send, token, path, body, { fetchHtml, storage }) {
  let res = await send(token);
  if (!tokenGecersiz(res.status, res.data)) return { res, token };
  taslakKaydet(storage, path, body);
  let fresh = '';
  try { fresh = metadanToken(await fetchHtml()); } catch { /* offline */ }
  if (!fresh) return { res, token };
  res = await send(fresh);
  if (res.status !== 403) taslakSil(storage);
  return { res, token: fresh };
}
