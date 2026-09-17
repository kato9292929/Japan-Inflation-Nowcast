import { describe, expect, it, vi } from "vitest";
import { readFile } from "node:fs/promises";
import { NextRequest } from "next/server";
import jin from "@/data/jin_public.json";
import { getInflation, getStoreIndex, validateRecord, withFreshness } from "@/lib/inflation-data";
import { GET as latest, OPTIONS } from "@/app/api/inflation/latest/route";
import { GET as country } from "@/app/api/inflation/[country]/route";

const now = Date.parse("2026-09-17T03:00:00Z");
const request = new NextRequest("https://jin.test/api/inflation/jp");

vi.mock("node:fs/promises", async (original) => {
  const actual = await original<typeof import("node:fs/promises")>();
  return { ...actual, readFile: vi.fn(actual.readFile) };
});

describe("公的CPI配信", () => {
  it("全3か国を返し、未取得値はnullとstaleで区別する", async () => {
    const response = await latest();
    expect(response.status).toBe(200);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    const body = await response.json();
    expect(body.countries.map((r: { country: string }) => r.country)).toEqual(["jp", "kr", "sg"]);
    for (const r of body.countries) {
      expect(r.source).toBeTruthy();
      expect(r).toHaveProperty("as_of");
      if (r.status === "not_fetched") {
        expect(r.cpi_yoy).toBeNull();
        expect(r.cpi_index.value).toBeNull();
        expect(r.stale).toBe(true);
        expect(r.as_of).toBeNull();
      }
    }
    expect(body.countries[1]).not.toHaveProperty("store_index");
  });

  it("日本の店頭指数は既存データ・基準日と完全一致する", async () => {
    const r = await getInflation("jp", Date.parse(jin.latest.as_of) + 86400000);
    expect(r).toHaveProperty("store_index.excl_promo", jin.latest.index.excl_promo);
    expect(r).toHaveProperty("store_index.incl_promo", jin.latest.index.incl_promo);
    expect(r).toHaveProperty("store_index.base_date", jin.latest.base_date);
    expect(r).toHaveProperty("store_index.as_of", jin.latest.as_of);
    expect(r).toHaveProperty("store_index.official_cpi", false);
    expect(r).toHaveProperty("store_index.stale", false);
  });

  it("店頭指数を観測日で失効させる", () => {
    expect(getStoreIndex(Date.parse(jin.latest.as_of) + 10 * 86400000).stale).toBe(true);
    expect(getStoreIndex(Date.parse("2020-01-01")).stale).toBe(true);
  });

  it("単一国は同じ構造で返す", async () => {
    const response = await country(request, { params: Promise.resolve({ country: "jp" }) });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(await getInflation("jp"));
  });

  it("非対応国とパストラバーサルは404、preflightは無料", async () => {
    for (const value of ["us", "../jp", "JP"]) {
      const response = await country(request, { params: Promise.resolve({ country: value }) });
      expect(response.status).toBe(404);
      expect(response.headers.get("access-control-allow-origin")).toBe("*");
    }
    expect(OPTIONS().status).toBe(204);
  });

  it("ファイルの欠落・破損はCORS付き503で明示する", async () => {
    vi.mocked(readFile).mockRejectedValueOnce(new Error("ENOENT"));
    const unavailable = await latest();
    expect(unavailable.status).toBe(503);
    expect(unavailable.headers.get("access-control-allow-origin")).toBe("*");
    vi.mocked(readFile).mockResolvedValueOnce("{broken");
    const invalid = await country(request, { params: Promise.resolve({ country: "jp" }) });
    expect(invalid.status).toBe(503);
    expect(await invalid.json()).toEqual({ error: "inflation_data_unavailable" });
  });

  it("古いファイルを取得日時と対象月の両方で失効させる", async () => {
    const initial = JSON.parse(await readFile("data/inflation/kr.json", "utf8"));
    const good = { ...initial, as_of: "2026-07", fetched_at: "2026-09-17T00:00:00Z",
      cpi_yoy: 2, cpi_index: { value: 102, base_year: 2020, base_value: 100 },
      metric_status: { cpi_yoy: "available", cpi_index: "available", food_yoy: "not_supported" },
      status: "ok", stale: false, stale_reasons: [] };
    const r = validateRecord(good, "kr");
    expect(withFreshness(r, now).stale).toBe(false);
    expect(withFreshness({ ...r, fetched_at: "2026-09-01T00:00:00Z" }, now).stale_reasons).toContain("fetch_expired");
    expect(withFreshness({ ...r, as_of: "2026-01" }, now).stale_reasons).toContain("period_expired");
    expect(withFreshness({ ...r, status: "refresh_failed" }, now).stale).toBe(true);
    expect(withFreshness({ ...r, as_of: "2027-01" }, now).stale).toBe(true);
    expect(() => validateRecord({ ...good, cpi_yoy: "2" }, "kr")).toThrow();
    expect(() => validateRecord({ ...good, fetched_at: null }, "kr")).toThrow();
    expect(() => validateRecord({ ...good, country: "jp" }, "kr")).toThrow();
  });
});
