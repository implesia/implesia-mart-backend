const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = String(env.ORIGIN || "").replace(/\/$/, "");

    if (url.pathname === "/" || url.pathname === "/health/live") {
      return json({
        service: "implesia-mart-api",
        host: "mart-api.implesia.com",
        origin_configured: Boolean(origin),
        status: origin ? "proxy" : "hostname_ready",
      });
    }

    if (!origin) {
      return json(
        {
          error: {
            code: "origin_not_configured",
            message:
              "mart-api.implesia.com is live. Point ORIGIN at the FastAPI host to proxy /api and /health.",
          },
        },
        503,
      );
    }

    const upstream = new URL(url.pathname + url.search, origin);
    const headers = new Headers(request.headers);
    // ORIGIN_HOST lets the proxy dial an IP while Caddy still matches the app hostname.
    const originHost = String(env.ORIGIN_HOST || new URL(origin).host);
    headers.set("host", originHost);
    headers.delete("cf-connecting-ip");

    return fetch(upstream, {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });
  },
};
