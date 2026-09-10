/* GET /api/catalogs  ->  { catalogs: [...] }   (replaces data/reference/index.json) */
import { catalogIndex } from "../_lib.js";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=300",
  "access-control-allow-origin": "*",
};

export async function onRequestGet({ env }) {
  if (!env.DB)
    return new Response(JSON.stringify({ error: "D1 binding DB missing" }), {
      status: 500,
      headers: JSON_HEADERS,
    });
  const body = await catalogIndex(env.DB);
  return new Response(JSON.stringify(body), { headers: JSON_HEADERS });
}
