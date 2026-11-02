// Cloudflare Pages Function: forwards every /api/* request to the real backend
// so the browser stays same-origin (no CORS, login cookie just works).
//
// Set BACKEND_ORIGIN in Pages > Settings > Environment variables, e.g.
//   BACKEND_ORIGIN = https://api-np.axilabz.com      (no trailing path)
// The backend must be hosted elsewhere (FastAPI cannot run on Pages itself).

interface Ctx {
  request: Request;
  env: { BACKEND_ORIGIN?: string };
}

export const onRequest = async ({ request, env }: Ctx): Promise<Response> => {
  if (!env.BACKEND_ORIGIN) {
    return new Response(
      JSON.stringify({ error: { code: 'BACKEND_NOT_CONFIGURED', message: 'BACKEND_ORIGIN is not set on this deployment.' } }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    );
  }
  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, env.BACKEND_ORIGIN);
  const upstream = new Request(target.toString(), request);
  upstream.headers.set('X-Forwarded-Host', incoming.host);
  upstream.headers.set('X-Forwarded-Proto', incoming.protocol.replace(':', ''));
  return fetch(upstream);
};
