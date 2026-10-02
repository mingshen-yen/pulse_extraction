// One public URL: the site is served at mingslab.com/pulse_database/ through a
// proxy in the personal site (mingshen-yen/minghsuan,
// functions/pulse_database/[[path]].js), which marks its requests with
// X-Pulse-Proxy. Direct visits to the production pages.dev host are sent
// there; preview hosts (<branch>.pulse-extraction.pages.dev) stay reachable.
const PROD_HOST = "pulse-extraction.pages.dev";
const PUBLIC_URL = "https://mingslab.com/pulse_database";

export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  if (url.hostname === PROD_HOST && !request.headers.has("X-Pulse-Proxy")) {
    return Response.redirect(PUBLIC_URL + url.pathname + url.search, 301);
  }
  return next();
}
