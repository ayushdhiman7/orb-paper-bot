import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "GET" && req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), { status: 405, headers: corsHeaders });
  }

  try {
    const url = Deno.env.get("SUPABASE_URL");
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const allowedEmail = Deno.env.get("DASHBOARD_ALLOWED_EMAIL")?.trim().toLowerCase();
    if (!url || !anonKey || !serviceKey || !allowedEmail) {
      return new Response(JSON.stringify({ error: "Dashboard access is not configured." }), { status: 503, headers: corsHeaders });
    }

    const authHeader = req.headers.get("Authorization") || "";
    const token = authHeader.match(/^Bearer\s+(.+)$/i)?.[1];
    if (!token) return new Response(JSON.stringify({ error: "Authentication required." }), { status: 401, headers: corsHeaders });

    const authClient = createClient(url, anonKey, { auth: { persistSession: false, autoRefreshToken: false } });
    const { data: userData, error: authError } = await authClient.auth.getUser(token);
    const user = userData?.user;
    if (authError || !user) return new Response(JSON.stringify({ error: "Invalid session. Please sign in again." }), { status: 401, headers: corsHeaders });
    if ((user.email || "").trim().toLowerCase() !== allowedEmail) {
      return new Response(JSON.stringify({ error: "This account is not authorized to view the trading dashboard." }), { status: 403, headers: corsHeaders });
    }

    const db = createClient(url, serviceKey, { auth: { persistSession: false, autoRefreshToken: false } });
    const [trades, backtests] = await Promise.all([
      db.from("paper_trades").select("*").order("ts", { ascending: false }).limit(2000),
      db.from("backtest_runs").select("*").order("created_at", { ascending: false }).limit(10),
    ]);
    if (trades.error || backtests.error) {
      console.error("Dashboard query failed", { trades: trades.error?.message, backtests: backtests.error?.message });
      return new Response(JSON.stringify({ error: "Could not load dashboard data." }), { status: 502, headers: corsHeaders });
    }

    return new Response(JSON.stringify({ trades: trades.data || [], backtests: backtests.data || [] }), {
      status: 200,
      headers: { ...corsHeaders, "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error("Dashboard API error", error);
    return new Response(JSON.stringify({ error: "Unexpected dashboard error." }), { status: 500, headers: corsHeaders });
  }
});
