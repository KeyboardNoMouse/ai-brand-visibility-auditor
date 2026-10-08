import type { AuditResult } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export async function runAudit(
  brandName: string,
  url: string
): Promise<AuditResult> {
  const resp = await fetch(`${API_BASE}/audits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand_name: brandName, url }),
  });

  if (!resp.ok) {
    let detail = `Request failed with status ${resp.status}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }

  return (await resp.json()) as AuditResult;
}
