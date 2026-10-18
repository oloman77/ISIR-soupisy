// ISIR Radar security for Cloudflare Pages: protects all static and API requests.
// Free password-based alternative when Cloudflare Zero Trust requires billing setup.
// Fail closed unless RADAR_LOGIN_PASSWORD is configured as a Cloudflare Pages Secret.
// HTTPS only; never log secrets or Authorization headers. Use a unique random password of at least 12 characters.

const ENCODER = new TextEncoder();
const unauthorized = (message, status, challenge = false) => {
  const headers = new Headers({
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex, nofollow, noarchive'
  });
  if (challenge) headers.set('WWW-Authenticate', 'Basic realm="ISIR Radar", charset="UTF-8"');
  return new Response(message, {status, headers});
};

async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', ENCODER.encode(value)));
}
function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let delta = 0;
  for (let i = 0; i < a.length; i++) delta |= a[i] ^ b[i];
  return delta === 0;
}

async function authorized(header, secret) {
  if (!header || header.length > 1200 || !/^Basic /i.test(header)) return false;
  try {
    const base64 = header.slice(6).trim();
    if (!/^[A-Za-z0-9+/]+={0,2}$/.test(base64) || base64.length > 1100) return false;
    const binary = atob(base64);
    const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
    const decoded = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    if (!decoded.startsWith('radar:')) return false;
    const supplied = decoded.slice(6);
    // Equal-length SHA-256 digests avoid revealing matching password prefixes.
    return constantTimeEqual(await digest(supplied), await digest(secret));
  } catch {
    return false;
  }
}

export async function onRequest(context) {
  const {request, env} = context;
  const secret = env.RADAR_LOGIN_PASSWORD;
  if (typeof secret !== 'string' || secret.length < 12 || secret.length > 256)
    return unauthorized('ISIR Radar: ochrana heslem ještě není nastavena.', 503);

  const url = new URL(request.url);
  if (url.protocol !== 'https:')
    return unauthorized('Použij zabezpečené připojení HTTPS.', 403);

  if (!(await authorized(request.headers.get('Authorization'), secret)))
    return unauthorized('Pro vstup do ISIR Radaru zadej uživatelské jméno radar a své heslo.', 401, true);

  // Browsers attach HTTP Basic credentials automatically. Explicitly block CSRF
  // from third-party sites before any writes to the private database.
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method.toUpperCase())) {
    const origin = request.headers.get('Origin');
    if (origin !== url.origin)
      return unauthorized('Požadavek pochází z nepovolené stránky.', 403);
    const contentType = (request.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
    if (contentType !== 'application/json')
      return unauthorized('Neplatný formát požadavku.', 415);
  }

  if (!env.DB && url.pathname.startsWith('/api/'))
    return unauthorized('Databázové propojení není nastavené.', 503);

  const response = await context.next();
  const headers = new Headers(response.headers);
  headers.set('Cache-Control', 'private, no-store');
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'no-referrer');
  headers.set('X-Frame-Options', 'DENY');
  headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
  return new Response(response.body, {
    status: response.status, statusText: response.statusText, headers
  });
}
