// jin_public.json を読んで返すだけ（計算は Python 側の責務。ここは配信のみ）。
// 観測値 + 方法論 + movers のみ。予測・確率は一切含めない。

import jin from "@/data/jin_public.json";

export function getJinLatest() {
  // latest は観測値 + coverage_note + methodology を内包。source_timestamp を併記。
  // passthrough_gap は追加のみ・nullable（上流CGPI↔下流JIN の観測ブロック。
  // 数値gapは not_comparable で非公開＝予測publishにならない）。欠けても応答は成立する。
  return {
    ...jin.latest,
    source_timestamp: jin.generated_at,
    passthrough_gap: jin.passthrough_gap ?? null,
  };
}

export function getJinSeries(from?: string | null, to?: string | null) {
  const series = jin.series.filter(
    (r) => (!from || r.date >= from) && (!to || r.date <= to),
  );
  return {
    source: jin.source,
    base_date: jin.base_date,
    methodology: jin.methodology,
    coverage_note: jin.coverage_note,
    series,
  };
}

export function getJinMovers(date?: string | null) {
  const as_of = date || jin.latest?.as_of;
  const byDate = jin.movers_by_date as Record<string, unknown[]>;
  const movers = (as_of && byDate[as_of]) || [];
  return {
    source: jin.source,
    as_of,
    movers,
    methodology: jin.methodology,
    coverage_note: jin.coverage_note,
  };
}
