import { readFile } from "node:fs/promises";
import path from "node:path";
import jin from "@/data/jin_public.json";

export const COUNTRIES = ["jp", "kr", "sg"] as const;
export type Country = (typeof COUNTRIES)[number];
type MetricStatus = "not_fetched" | "not_supported" | "available";
export type InflationRecord = {
  country: Country;
  source: string;
  source_url: string;
  as_of: string | null;
  released_at: string | null;
  fetched_at: string | null;
  frequency: "monthly";
  cpi_yoy: number | null;
  cpi_index: { value: number | null; base_year: number | null; base_value: 100 };
  food_yoy: number | null;
  units: { cpi_yoy: "percent"; cpi_index: "index"; food_yoy: "percent" };
  metric_status: { cpi_yoy: MetricStatus; cpi_index: MetricStatus; food_yoy: MetricStatus };
  yoy_method: "published" | "index_ratio";
  status: "not_fetched" | "ok" | "refresh_failed";
  stale: boolean;
  stale_reasons: string[];
  last_attempt_at: string | null;
  last_error: string | null;
};

export function isCountry(value: string): value is Country {
  return COUNTRIES.some((country) => country === value);
}

const DAY = 86_400_000;
const validNumber = (value: unknown) => typeof value === "number" && Number.isFinite(value);
const nullableNumber = (value: unknown) => value === null || validNumber(value);
const validDate = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));

// JSON.parseの型キャストだけで未検証ファイルを公開しない。
export function validateRecord(input: unknown, country: Country): InflationRecord {
  const r = input as InflationRecord;
  if (!r || r.country !== country || !r.source || !r.source_url || r.frequency !== "monthly"
    || !["not_fetched", "ok", "refresh_failed"].includes(r.status)
    || !["published", "index_ratio"].includes(r.yoy_method)
    || typeof r.stale !== "boolean" || !Array.isArray(r.stale_reasons)
    || !r.stale_reasons.every((reason) => typeof reason === "string")
    || (r.as_of !== null && !/^\d{4}-(0[1-9]|1[0-2])$/.test(r.as_of))
    || (r.fetched_at !== null && !validDate(r.fetched_at))
    || (r.released_at !== null && !validDate(r.released_at))
    || (r.last_attempt_at !== null && !validDate(r.last_attempt_at))
    || (r.last_error !== null && typeof r.last_error !== "string")
    || !nullableNumber(r.cpi_yoy) || !nullableNumber(r.food_yoy)
    || !r.cpi_index || !nullableNumber(r.cpi_index.value) || r.cpi_index.base_value !== 100
    || (r.cpi_index.value !== null && r.cpi_index.value <= 0)
    || (r.cpi_index.base_year !== null && (!Number.isInteger(r.cpi_index.base_year)
      || r.cpi_index.base_year < 1900 || r.cpi_index.base_year > 2100))
    || r.units?.cpi_yoy !== "percent" || r.units?.food_yoy !== "percent" || r.units?.cpi_index !== "index") {
    throw new Error("公的CPIの保存形式が不正です");
  }
  for (const metric of ["cpi_yoy", "cpi_index", "food_yoy"] as const) {
    const status = r.metric_status?.[metric];
    const value = metric === "cpi_index" ? r.cpi_index.value : r[metric];
    if (!["not_fetched", "not_supported", "available"].includes(status)
      || (status === "available") !== (value !== null)
      || (metric !== "food_yoy" && status === "not_supported")) {
      throw new Error("指標の状態と値が一致しません");
    }
  }
  const hasValue = [r.cpi_yoy, r.cpi_index.value, r.food_yoy].some((v) => v !== null);
  if ((hasValue && (!r.as_of || !r.fetched_at || !r.cpi_index.base_year))
    || (r.status === "not_fetched" && hasValue)
    || (r.status === "ok" && (!hasValue || r.cpi_yoy === null || r.cpi_index.value === null))) {
    throw new Error("公的CPIの来歴が不正です");
  }
  return r;
}

export function withFreshness(record: InflationRecord, now = Date.now()): InflationRecord {
  const reasons = new Set(record.stale_reasons);
  if (record.status !== "ok") reasons.add(record.status);
  if (!record.as_of || !record.fetched_at) reasons.add("not_fetched");
  if (Object.values(record.metric_status).includes("not_fetched")) reasons.add("missing_metric");
  if (record.fetched_at) {
    const age = now - Date.parse(record.fetched_at);
    if (age > 7 * DAY) reasons.add("fetch_expired");
    if (age < 0) reasons.add("future_timestamp");
  }
  if (record.as_of) {
    const [year, month] = record.as_of.split("-").map(Number);
    if (now - Date.UTC(year, month, 1) > 62 * DAY) reasons.add("period_expired");
    if (Date.UTC(year, month - 1, 1) > now) reasons.add("future_period");
  }
  if (record.stale && reasons.size === 0) reasons.add("marked_stale");
  return { ...record, stale: reasons.size > 0, stale_reasons: [...reasons] };
}

export function getStoreIndex(now = Date.now()) {
  const observed = Date.parse(`${jin.latest.as_of}T00:00:00+09:00`);
  const reasons = [];
  if (!Number.isFinite(observed)) reasons.push("not_fetched");
  else if (observed > now) reasons.push("future_timestamp");
  else if (now - observed > 3 * DAY) reasons.push("observation_expired");
  if (!validNumber(jin.latest.index.excl_promo) || !validNumber(jin.latest.index.incl_promo)) {
    reasons.push("missing_metric");
  }
  return {
    source: jin.source, type: "store_observation", official_cpi: false,
    scope: "single_store", geographically_representative: false,
    frequency: "daily", unit: "index", base_value: 100,
    excl_promo: jin.latest.index.excl_promo, incl_promo: jin.latest.index.incl_promo,
    base_date: jin.latest.base_date, as_of: jin.latest.as_of, generated_at: jin.generated_at,
    stale: reasons.length > 0, stale_reasons: reasons,
  };
}

export async function getInflation(country: Country, now = Date.now()) {
  const file = path.join(process.cwd(), "data", "inflation", `${country}.json`);
  const record = withFreshness(validateRecord(JSON.parse(await readFile(file, "utf8")), country), now);
  return country === "jp" ? { ...record, store_index: getStoreIndex(now) } : record;
}

export async function getInflationLatest() {
  const now = Date.now();
  return { countries: await Promise.all(COUNTRIES.map((country) => getInflation(country, now))) };
}
