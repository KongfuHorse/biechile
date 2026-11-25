// Admin page "刷新网站数据" button: checks the admin login, then asks GitHub to rebuild the website
// from the database (workflow update.yml with export_only=yes). The GitHub token lives only in this
// function's secrets (GITHUB_DISPATCH_TOKEN), never in the page.
const ORIGINS = ["https://biechile.com", "https://www.biechile.com"];

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") ?? "";
  const cors = {
    "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
    "Access-Control-Allow-Headers": "content-type, apikey, authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method === "OPTIONS") return new Response(null, { headers: cors });
  if (req.method !== "POST") return json({ error: "只接受 POST" }, 405);

  const { token } = await req.json().catch(() => ({}));
  const url = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const check = await fetch(`${url}/rest/v1/rpc/admin_request_refresh`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ p_token: token ?? "" }),
  });
  if (!check.ok) {
    const e = await check.json().catch(() => ({}));
    return json({ error: e.message || "登录已过期，请重新登录" }, 401);
  }

  const gh = Deno.env.get("GITHUB_DISPATCH_TOKEN");
  if (!gh) return json({ error: "还没有设置 GitHub 令牌（GITHUB_DISPATCH_TOKEN）" }, 500);
  const r = await fetch("https://api.github.com/repos/KongfuHorse/biechile/actions/workflows/update.yml/dispatches", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${gh}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "biechile-admin",
    },
    body: JSON.stringify({ ref: "main", inputs: { export_only: "yes" } }),
  });
  if (r.status !== 204) return json({ error: `GitHub 没有接受请求（${r.status}）` }, 502);
  return json({ ok: true });
});
