// Phase 5 (AUTH-1) — canonical lead write HTTP boundary for AION Revenue Factory.
//
// Thin, authenticated wrapper over the SECURITY DEFINER RPC
// `apply_revenue_lead_upsert`. Writes ONLY revenue_leads + revenue_sync_events
// (never opportunities/deals). Mirrors the auth + idempotency + optimistic-
// concurrency shape of the existing `revenue-control` function.
//
// Auth: bearer worker token in REVENUE_INGEST_API_KEY (AUTH-2, provisioned out
// of band). If the secret is not configured the endpoint returns 503 rather
// than 500 (graceful when un-provisioned). Never embeds a service-role key in
// any client repo; SUPABASE_SERVICE_ROLE_KEY is an edge-runtime secret used
// only here to invoke the definer RPC.
//
// NOT deployed yet — deploy alongside provisioning REVENUE_INGEST_API_KEY.
//
// Body: { row: <canonical lead row>, idempotency_key: string,
//         actor_type?: string, actor_id?: string, expected_version?: number }

import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, idempotency-key",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

serve(async (request) => {
  if (request.method === "OPTIONS") return json({ ok: true });
  if (request.method !== "POST") return json({ ok: false, error: "Method not allowed" }, 405);

  const expected = Deno.env.get("REVENUE_INGEST_API_KEY");
  if (!expected) {
    // Un-provisioned: fail closed but explicitly (not a 500).
    return json({ ok: false, error: "REVENUE_INGEST_API_KEY not configured" }, 503);
  }

  const header = request.headers.get("authorization") ?? "";
  const [scheme, token] = header.split(/\s+/);
  if (scheme?.toLowerCase() !== "bearer" || token !== expected) {
    return json({ ok: false, error: "Unauthorized" }, 401);
  }

  try {
    const body = await request.json() as {
      row?: Record<string, unknown>;
      idempotency_key?: string;
      actor_type?: string;
      actor_id?: string;
      expected_version?: number;
    };
    const key = body.idempotency_key ?? request.headers.get("idempotency-key");
    if (!body.row || !key) {
      return json({ ok: false, error: "row and idempotency_key are required" }, 400);
    }

    const admin = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
      { auth: { persistSession: false } },
    );

    const { data, error } = await admin.rpc("apply_revenue_lead_upsert", {
      p_row: body.row,
      p_idempotency_key: key,
      p_actor_type: body.actor_type ?? "system",
      p_actor_id: body.actor_id ?? "aion_revenue_factory",
      p_expected_version: body.expected_version ?? null,
    });

    if (error) {
      // 40001 = optimistic-concurrency conflict -> 409, like revenue-control.
      return json({ ok: false, error: error.message }, error.code === "40001" ? 409 : 400);
    }
    return json({ ok: true, result: data });
  } catch (error) {
    return json({ ok: false, error: error instanceof Error ? error.message : String(error) }, 500);
  }
});
