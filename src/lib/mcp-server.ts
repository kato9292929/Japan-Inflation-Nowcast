// JIN の MCP サーバ（読み取り専用）。公開済みのデータ（jin_public.json・data/inflation）だけを返す。
// 計算はしない（計算は Python 側の責務）。予測・確率は返さない。
// どの応答にも notice（公式 CPI ではない・単一店舗・食料のみ・予測ではない）を付ける。
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import jin from "@/data/jin_public.json";
import labelsEn from "@/data/item_labels_en.json";
import { getJinLatest, getJinSeries } from "./jin-data";
import { COUNTRIES, getInflation } from "./inflation-data";

export const MCP_SERVER_NAME = "jin";
export const MCP_SERVER_VERSION = "0.1.0";

export const NOTICE =
  "JIN is an independent store-front observation nowcast, not the official CPI. " +
  "It covers food only, from a single supermarket in the Tokyo area, and is not nationally representative. " +
  "Values are observations, not forecasts. / JIN は独立の店頭観測による速報で、公式 CPI ではない。" +
  "食料のみ・東京圏の単一店舗で、全国を代表しない。値は観測値で、予測ではない。";

const DATE = /^\d{4}-\d{2}-\d{2}$/;

type Mover = { category: string; item: string; pct: number; promo_tag: boolean; note?: string };
type Json = Record<string, unknown>;

const ok = (body: Json) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ notice: NOTICE, ...body }, null, 2) }],
});
const fail = (message: string, extra: Json = {}) => ({
  isError: true,
  content: [{ type: "text" as const, text: JSON.stringify({ error: message, ...extra }, null, 2) }],
});

const moverDates = () => Object.keys(jin.movers_by_date).sort();
const seriesDates = () => jin.series.map((r) => r.date);
const catEn = (c: string) => (labelsEn.categories as Record<string, string>)[c] ?? null;
const itemEn = (i: string) => (labelsEn.items as Record<string, string>)[i] ?? null;

const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

export function buildMcpServer(): McpServer {
  const server = new McpServer(
    { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
    {
      instructions:
        "Japan Inflation Nowcall (JIN): daily store-front food price observations in Tokyo, " +
        "indexed to a fixed base date (= 100), plus the latest official CPI for Japan, Korea and Singapore. " +
        "JIN is not the official CPI and not a forecast; always pass on the notice field when quoting values. " +
        "excl_promo (promotions removed) is the headline series; incl_promo includes promotional prices.",
    },
  );

  server.registerTool(
    "get_nowcast_latest",
    {
      title: "JIN latest food index",
      description:
        "Latest JIN food price index (base date = 100): excl_promo (headline) and incl_promo, " +
        "observation date, matched SKU counts, share of basket weight not observed that day, and coverage note.",
      inputSchema: {},
      annotations: READ_ONLY,
    },
    async () => {
      const l = getJinLatest();
      return ok({
        as_of: l.as_of,
        base_date: l.base_date,
        index: l.index,
        matched_sku: l.matched_sku,
        imputed_weight_share: l.imputed_weight_share ?? null,
        imputed_categories: l.imputed_categories ?? null,
        coverage_note: l.coverage_note,
        methodology: l.methodology,
        source_timestamp: l.source_timestamp,
      });
    },
  );

  server.registerTool(
    "get_nowcast_series",
    {
      title: "JIN daily index series",
      description:
        "JIN food index on every observation date (excl_promo / incl_promo, matched SKU counts). " +
        "Observation dates are irregular. Optional from/to (YYYY-MM-DD, inclusive).",
      inputSchema: {
        from: z.string().regex(DATE).optional().describe("Start date, YYYY-MM-DD (inclusive)"),
        to: z.string().regex(DATE).optional().describe("End date, YYYY-MM-DD (inclusive)"),
      },
      annotations: READ_ONLY,
    },
    async ({ from, to }) => {
      const s = getJinSeries(from ?? null, to ?? null);
      return ok({ base_date: s.base_date, coverage_note: s.coverage_note, count: s.series.length, series: s.series });
    },
  );

  server.registerTool(
    "get_item_moves",
    {
      title: "JIN item-level moves",
      description:
        "Items whose price on the given observation date differs from the same product on the base date, " +
        "as % change, with promo flag. Defaults to the latest date. Items not listed were either unchanged " +
        "or not observed that day (the data cannot tell which). Names are Japanese, with English labels.",
      inputSchema: {
        date: z.string().regex(DATE).optional().describe("Observation date, YYYY-MM-DD. Default: latest."),
      },
      annotations: READ_ONLY,
    },
    async ({ date }) => {
      const dates = moverDates();
      const d = date ?? jin.latest.as_of;
      const byDate = jin.movers_by_date as Record<string, Mover[]>;
      if (!byDate[d]) return fail("no_observation_on_date", { date: d, available_dates: dates });
      const row = (jin.series as Json[]).find((r) => r.date === d) ?? {};
      return ok({
        date: d,
        base_date: jin.base_date,
        unobserved_categories: {
          excl_promo: row.imputed_categories_excl ?? [],
          incl_promo: row.imputed_categories_incl ?? [],
        },
        count: byDate[d].length,
        moves: byDate[d].map((m) => ({
          category: m.category,
          category_en: catEn(m.category),
          item: m.item,
          item_en: itemEn(m.item),
          pct_vs_base: m.pct,
          promo: m.promo_tag,
        })),
      });
    },
  );

  server.registerTool(
    "get_official_cpi",
    {
      title: "Official CPI (latest stored)",
      description:
        "Latest stored official CPI from the national statistics office: headline YoY, index level and food YoY " +
        "where available, with release dates and staleness flags. For Japan, the JIN store index is attached " +
        "separately as store_index (not part of the official figures).",
      inputSchema: { country: z.enum(COUNTRIES).describe("jp (Japan), kr (Korea) or sg (Singapore)") },
      annotations: READ_ONLY,
    },
    async ({ country }) => {
      try {
        return ok(await getInflation(country));
      } catch {
        return fail("inflation_data_unavailable", { country });
      }
    },
  );

  server.registerTool(
    "get_methodology",
    {
      title: "JIN methodology and coverage",
      description: "How the JIN index is built, what it covers, its base date, and the list of observation dates.",
      inputSchema: {},
      annotations: READ_ONLY,
    },
    async () =>
      ok({
        methodology: jin.methodology,
        coverage_note: jin.coverage_note,
        base_date: jin.base_date,
        observation_dates: seriesDates(),
        license: jin.license,
        source: "https://github.com/kato9292929/Japan-Inflation-Nowcast",
      }),
  );

  return server;
}
