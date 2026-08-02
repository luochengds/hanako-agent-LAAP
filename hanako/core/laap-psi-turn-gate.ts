import fs from "fs";
import path from "path";

export type LaapPsiTurnHandle = {
  input: string;
  enabled: true;
};

function required(): boolean {
  return process.env.LAAP_PSI_GATE_REQUIRED === "1"
    || process.env.HANA_LAAP_PSI_REQUIRED === "1";
}

function sidecarBaseUrl(): string {
  return (process.env.LAAP_SIDECAR_URL || "http://127.0.0.1:11521").replace(/\/$/, "");
}

function sidecarToken(): string {
  const fromEnv = process.env.ARIS_SIDECAR_TOKEN?.trim();
  if (fromEnv) return fromEnv;
  const tokenPath = process.env.ARIS_SIDECAR_TOKEN_PATH
    || path.join(process.cwd(), "aris-bridge", "aris-engine", "state", "aris-sidecar.token");
  try {
    return fs.readFileSync(tokenPath, "utf8").trim();
  } catch {
    return "";
  }
}

async function post(pathname: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const token = sidecarToken();
  if (!token) throw new Error("LAAP PSI gate requires ARIS_SIDECAR_TOKEN or a persisted sidecar token");
  const response = await fetch(`${sidecarBaseUrl()}${pathname}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  const body = await response.text();
  let parsed: Record<string, unknown> = {};
  try { parsed = JSON.parse(body) as Record<string, unknown>; } catch { /* preserve status below */ }
  if (!response.ok) {
    throw new Error(`LAAP PSI gate ${pathname} failed (${response.status}): ${body.slice(0, 240)}`);
  }
  return parsed;
}

export async function beginLaapPsiTurn(input: unknown): Promise<LaapPsiTurnHandle | null> {
  if (!required()) return null;
  const text = typeof input === "string" ? input : JSON.stringify(input);
  await post("/before_turn", { user_input: text });
  return { input: text, enabled: true };
}

export async function finishLaapPsiTurn(handle: LaapPsiTurnHandle | null, response: unknown): Promise<void> {
  if (!handle) return;
  const text = typeof response === "string" ? response : JSON.stringify(response);
  await post("/after_turn", { response: text });
}
