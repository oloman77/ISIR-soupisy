// Cloudflare Pages middleware: protect BOTH static UI and API.
// Fail closed if access is not configured. Never trust a JWT without RS256 verification.
let cachedKeys = null;
let cachedUntil = 0;

const text = (value, status) => new Response(value, {
  status,
  headers: {'Content-Type': 'text/plain; charset=utf-8',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
});
const decode = value => {
  const b64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const bytes = atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='));
  return Uint8Array.from(bytes, ch => ch.charCodeAt(0));
};
async function getKeys(domain) {
  if (cachedKeys && Date.now() < cachedUntil) return cachedKeys;
  const result = await fetch(domain + '/cdn-cgi/access/certs', {
    cf: {cacheEverything: true, cacheTtl: 300}
  });
  if (!result.ok) throw Error('Cloudflare Access certificates unavailable');
  const body = await result.json();
  if (!Array.isArray(body.keys)) throw Error('Invalid Cloudflare Access certificates');
  cachedKeys = body.keys;
  cachedUntil = Date.now() + 300000;
  return cachedKeys;
}
async function identity(jwt, domain, audience) {
  const parts = (jwt || '').split('.');
  if (parts.length !== 3) throw Error('Missing JWT');
  const header = JSON.parse(new TextDecoder().decode(decode(parts[0])));
  const payload = JSON.parse(new TextDecoder().decode(decode(parts[1])));
  if (header.alg !== 'RS256' || !header.kid) throw Error('Unsupported JWT');
  const now = Math.floor(Date.now() / 1000);
  if (!(payload.exp > now) || (payload.nbf && payload.nbf > now)
    || payload.iss !== domain || !Array.isArray(payload.aud)
    || !payload.aud.includes(audience)) throw Error('JWT claim mismatch');
  const keyData = (await getKeys(domain)).find(key => key.kid === header.kid);
  if (!keyData) throw Error('Unknown JWT key');
  const key = await crypto.subtle.importKey('jwk', keyData,
    {name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256'}, false, ['verify']);
  const input = new TextEncoder().encode(parts[0] + '.' + parts[1]);
  const valid = await crypto.subtle.verify('RSASSA-PKCS1-v1_5',
    key, decode(parts[2]), input);
  if (!valid) throw Error('JWT signature invalid');
  return (payload.email || '').trim().toLowerCase();
}
export async function onRequest(context) {
  const {ACCESS_TEAM_DOMAIN, ACCESS_AUD, RADAR_ALLOWED_EMAIL, DB} = context.env;
  const domain = (ACCESS_TEAM_DOMAIN || '').replace(/\/$/, '');
  const allowed = (RADAR_ALLOWED_EMAIL || '').trim().toLowerCase();
  if (!/^https:\/\/[a-z0-9.-]+\.cloudflareaccess\.com$/i.test(domain)
    || !ACCESS_AUD || !allowed) return text('Radar: zabezpečení zatím není nastavené.', 503);
  try {
    const email = await identity(context.request.headers.get('Cf-Access-Jwt-Assertion'),
      domain, ACCESS_AUD);
    if (!email || email !== allowed) return text('Přístup odepřen.', 403);
  } catch (_) {
    return text('Přístup odepřen. Přihlas se přes Cloudflare Access.', 403);
  }
  if (!DB && new URL(context.request.url).pathname.startsWith('/api/'))
    return text('Databázové propojení není nastavené.', 503);
  const response = await context.next();
  // Private, potentially sensitive business notes should never be shared-cached.
  const headers = new Headers(response.headers);
  headers.set('Cache-Control', 'private, no-store');
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  headers.set('X-Frame-Options', 'DENY');
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
}
