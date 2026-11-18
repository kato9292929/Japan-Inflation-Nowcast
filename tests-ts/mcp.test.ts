// /mcp（MCP サーバ）のテスト。ルートに JSON-RPC を直接投げ、返る値を jin_public.json と突き合わせる。
import { describe, expect, it } from "vitest";
import jin from "@/data/jin_public.json";
import { NOTICE } from "@/lib/mcp-server";
import { DELETE, GET, OPTIONS, POST } from "@/app/mcp/route";

const HEADERS = {
  "content-type": "application/json",
  accept: "application/json, text/event-stream",
  "mcp-protocol-version": "2025-06-18",
};

async function rpc(method: string, params: Record<string, unknown> = {}) {
  const res = await POST(
    new Request("https://jin.test/mcp", {
      method: "POST",
      headers: HEADERS,
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    }),
  );
  return { res, body: await res.json() };
}

async function call(name: string, args: Record<string, unknown> = {}) {
  const { body } = await rpc("tools/call", { name, arguments: args });
  const result = body.result;
  return { isError: result.isError === true, data: JSON.parse(result.content[0].text) };
}

describe("MCP サーバ", () => {
  it("initialize に応え、サーバ名と CORS・no-store を返す", async () => {
    const { res, body } = await rpc("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "test", version: "0" },
    });
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(body.result.serverInfo.name).toBe("jin");
    expect(body.result.capabilities.tools).toBeTruthy();
  });

  it("5 つのツールを読み取り専用で公開する", async () => {
    const { body } = await rpc("tools/list");
    const names = body.result.tools.map((t: { name: string }) => t.name).sort();
    expect(names).toEqual(
      ["get_item_moves", "get_methodology", "get_nowcast_latest", "get_nowcast_series", "get_official_cpi"].sort(),
    );
    for (const t of body.result.tools) expect(t.annotations.readOnlyHint).toBe(true);
  });

  it("最新値は jin_public.json の latest と一致し、notice が付く", async () => {
    const { isError, data } = await call("get_nowcast_latest");
    expect(isError).toBe(false);
    expect(data.notice).toBe(NOTICE);
    expect(data.notice).toContain("not the official CPI");
    expect(data.as_of).toBe(jin.latest.as_of);
    expect(data.index).toEqual(jin.latest.index);
    expect(data.imputed_categories).toEqual(jin.latest.imputed_categories);
  });

  it("系列は from/to で絞れる", async () => {
    const all = await call("get_nowcast_series");
    expect(all.data.series).toEqual(jin.series);
    const part = await call("get_nowcast_series", { from: "2026-08-01", to: "2026-09-30" });
    expect(part.data.series.map((r: { date: string }) => r.date)).toEqual(["2026-08-18", "2026-09-16"]);
  });

  it("品目別の動きは movers_by_date と一致し、英語名と欠けた分類が付く", async () => {
    const { data } = await call("get_item_moves");
    const src = jin.movers_by_date["2026-10-19" as keyof typeof jin.movers_by_date];
    expect(data.date).toBe("2026-10-19");
    expect(data.count).toBe(src.length);
    expect(data.moves.map((m: { pct_vs_base: number }) => m.pct_vs_base)).toEqual(src.map((m) => m.pct));
    expect(data.moves.every((m: { item_en: string | null }) => m.item_en)).toBe(true);
    expect(data.unobserved_categories.excl_promo).toEqual(["酒類", "飲料", "魚介類"]);
    const komatsuna = data.moves.find((m: { item: string }) => m.item === "国内産 小松菜 1袋");
    expect(komatsuna).toMatchObject({ item_en: "Domestic komatsuna, 1 bag", category_en: "Vegetables & seaweed" });
  });

  it("観測の無い日はエラーにし、観測日の一覧を返す", async () => {
    const { isError, data } = await call("get_item_moves", { date: "2026-07-01" });
    expect(isError).toBe(true);
    expect(data.error).toBe("no_observation_on_date");
    expect(data.available_dates).toContain("2026-10-19");
  });

  it("日付の形式が違えばツールを実行しない", async () => {
    const { body } = await rpc("tools/call", { name: "get_item_moves", arguments: { date: "10/19" } });
    const failed = body.error !== undefined || body.result?.isError === true;
    expect(failed).toBe(true);
  });

  it("公的 CPI は国コードで引け、日本には店頭指数が別枠で付く", async () => {
    const { isError, data } = await call("get_official_cpi", { country: "jp" });
    expect(isError).toBe(false);
    expect(data.country).toBe("jp");
    expect(data.store_index.official_cpi).toBe(false);
    const kr = await call("get_official_cpi", { country: "kr" });
    expect(kr.data.store_index).toBeUndefined();
  });

  it("方法論に観測日の一覧が付く", async () => {
    const { data } = await call("get_methodology");
    expect(data.observation_dates).toEqual(jin.series.map((r) => r.date));
    expect(data.coverage_note).toBe(jin.coverage_note);
  });

  it("GET（SSE）と DELETE は 405 にする（セッションもストリームも持たない）", () => {
    for (const res of [GET(), DELETE()]) {
      expect(res.status).toBe(405);
      expect(res.headers.get("allow")).toBe("POST, OPTIONS");
    }
  });

  it("OPTIONS は 204 で CORS を返す", () => {
    const res = OPTIONS();
    expect(res.status).toBe(204);
    expect(res.headers.get("access-control-allow-headers")).toContain("Mcp-Session-Id");
  });
});
