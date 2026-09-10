/* GET /api/catalog/:id  ->  full catalog blob   (replaces data/reference/<id>.json) */
import { catalogBlob } from "../../_lib.js";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=300",
  "access-control-allow-origin": "*",
};

export async function onRequestGet({ env, params }) {
  if (!env.DB)
    return new Response(JSON.stringify({ error: "D1 binding DB missing" }), {
      status: 500,
      headers: JSON_HEADERS,
    });
  const blob = await catalogBlob(env.DB, params.id);
  if (!blob)
    return new Response(
      JSON.stringify({ error: `unknown catalog: ${params.id}` }),
      {
        status: 404,
        headers: JSON_HEADERS,
      },
    );
  return new Response(JSON.stringify(blob), { headers: JSON_HEADERS });
}
