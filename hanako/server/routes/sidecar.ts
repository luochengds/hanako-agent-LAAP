import { Hono } from "hono";
import fs from "node:fs";
import path from "node:path";

/** Local authenticated proxy for renderer-side Sidecar discovery calls. */
export function createSidecarRoute() {
  const route = new Hono();
  route.get("/sidecar/agents/online", async (c) => {
    const tokenPath = process.env.ARIS_SIDECAR_TOKEN_PATH
      || path.join(process.cwd(), "aris-bridge", "aris-engine", "state", "aris-sidecar.token");
    const token = process.env.ARIS_SIDECAR_TOKEN?.trim()
      || (fs.existsSync(tokenPath) ? fs.readFileSync(tokenPath, "utf8").trim() : "");
    if (!token) return c.json({ error: "sidecar token unavailable" }, 503);
    const response = await fetch("http://127.0.0.1:11521/agents/online", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
    });
  });
  return route;
}
