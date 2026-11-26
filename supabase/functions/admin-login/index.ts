// Admin login: checks the Cloudflare Turnstile answer first, then the password (admin_login2 in the
// database, which also limits failed tries per IP and per username). The Turnstile secret lives only
// in this function's secrets (TURNSTILE_SECRET), never in the page.
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

  const { username, password, captcha } = await req.json().catch(() => ({}));
  if (!username || !password) return json({ error: "请输入账号和密码" }, 400);
  const ip = (req.headers.get("cf-connecting-ip") || req.headers.get("x-forwarded-for") || "").split(",")[0].trim();

  const secret = Deno.env.get("TURNSTILE_SECRET");
  if (!secret) return json({ error: "人机验证还没有设置（TURNSTILE_SECRET）" }, 500);
  if (!captcha) return json({ error: "请先完成人机验证" }, 400);
  const form = new FormData();
  form.append("secret", secret);
  form.append("response", captcha);
  if (ip) form.append("remoteip", ip);
  const ts = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form })
    .then((r) => r.json()).catch(() => ({ success: false }));
  if (!ts.success) return json({ error: "人机验证没有通过，请重试" }, 403);

  const url = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const r = await fetch(`${url}/rest/v1/rpc/admin_login2`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ p_username: String(username), p_password: String(password), p_ip: ip }),
  });
  const body = await r.json().catch(() => null);
  if (!r.ok || !body) return json({ error: (body && body.message) || "登录失败" }, 500);
  if (!body.token) return json({ error: body.error || "登录失败" }, 401);
  return json({ token: body.token });
});
