import jin from "@/data/jin_public.json";
import labelsEn from "@/data/item_labels_en.json";
import ItemTrailsView, { type Cell, type Missing } from "./ItemTrailsView";

// 品目別の推移（基準日比 %）。公開済みの movers_by_date から組み立てる。観測値のみ・予測ではない。
// movers_by_date には「その日に基準日から動いた品」しか載らないため、載っていない日は
// 「変化なし」か「未観測」かを区別できない。表では空欄（·）にして注記で明示する。
// ただし series の imputed_categories_incl に入っている分類は、その日に基準日と対応づけられる品を
// 1 つも観測できなかったことが分かっているので「—」にする。
// 注記に出す品目名・分類名・比重はすべてデータから拾う（ここに直接書かない）。
// ここ（サーバ側）は集計だけを行い、表示と日英の切り替えは ItemTrailsView（クライアント側）に任せる。
// 英語の品目名・分類名は src/data/item_labels_en.json から引く（無ければ日本語のまま）。

type Mover = { category: string; item: string; pct: number; promo_tag: boolean };
type SeriesRow = {
  date: string;
  imputed_excl?: number;
  imputed_incl?: number;
  imputed_categories_excl?: string[];
  imputed_categories_incl?: string[];
};

// 6 月は観測日が多く表が横に長くなるので、この 2 日だけを載せる（運用者の指定）。7 月以降は全部載せる。
const JUNE_SHOWN = ["2026-06-05", "2026-06-18"];
const shown = (d: string) => !d.startsWith("2026-06") || JUNE_SHOWN.includes(d);

function buildTrails() {
  const byDate = jin.movers_by_date as unknown as Record<string, Mover[]>;
  const allDates = Object.keys(byDate).sort();
  // 表に出さない日の動きは、品目の抽出にも注記の判定にも使わない（表と注記をそろえる）。
  const dates = allDates.filter(shown);
  const omitted = allDates.filter((d) => !shown(d));
  const categories: string[] = [];
  const items = new Map<string, { category: string; item: string; cells: Record<string, Cell> }>();
  for (const date of dates) {
    for (const m of byDate[date] ?? []) {
      if (!categories.includes(m.category)) categories.push(m.category);
      const key = `${m.category}\u0000${m.item}`;
      const row = items.get(key) ?? { category: m.category, item: m.item, cells: {} };
      row.cells[date] = { pct: m.pct, promo: m.promo_tag };
      items.set(key, row);
    }
  }
  const rows = [...items.values()];
  const groups = categories.map((category) => ({
    category,
    rows: rows.filter((r) => r.category === category),
  }));

  // 観測できなかった分類（日付ごと）。series に記録がある日だけ。
  const missing: Record<string, Missing> = {};
  for (const r of jin.series as unknown as SeriesRow[]) {
    const excl = r.imputed_categories_excl ?? [];
    const incl = r.imputed_categories_incl ?? [];
    if (!dates.includes(r.date) || (excl.length === 0 && incl.length === 0)) continue;
    missing[r.date] = { excl, incl, shareExcl: r.imputed_excl ?? null, shareIncl: r.imputed_incl ?? null };
  }

  // 最初の観測日からプラスで、観測したどの日もマイナスにならない品。
  const first = dates[0];
  const alwaysUp = rows
    .filter((r) => {
      const cells = Object.values(r.cells);
      return first !== undefined && r.cells[first]?.pct > 0 && cells.length >= 2 && cells.every((c) => c.pct > 0);
    })
    .map((r) => r.item);

  return { dates, omitted, groups, count: rows.length, missing, alwaysUp };
}

export default function ItemTrails() {
  const data = buildTrails();
  if (data.dates.length === 0) return null;
  return <ItemTrailsView {...data} baseDate={jin.base_date} labelsEn={labelsEn} />;
}
