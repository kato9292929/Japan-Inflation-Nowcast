import styles from "./page.module.css";
import jin from "@/data/jin_public.json";

// 品目別の推移（基準日比 %）。公開済みの movers_by_date から組み立てる。観測値のみ・予測ではない。
// movers_by_date には「その日に基準日から動いた品」しか載らないため、載っていない日は
// 「変化なし」か「未観測」かを区別できない。表では空欄（·）にして注記で明示する。
// ただし series の imputed_categories_incl に入っている分類は、その日に基準日と対応づけられる品を
// 1 つも観測できなかったことが分かっているので「—」にする。
// 注記に出す品目名・分類名・比重はすべてデータから拾う（ここに直接書かない）。

type Mover = { category: string; item: string; pct: number; promo_tag: boolean };
type Cell = { pct: number; promo: boolean };
type SeriesRow = {
  date: string;
  imputed_excl?: number;
  imputed_incl?: number;
  imputed_categories_excl?: string[];
  imputed_categories_incl?: string[];
};
type Missing = { excl: string[]; incl: string[]; shareExcl: number | null; shareIncl: number | null };

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

function fmt(c: Cell) {
  const rounded = Math.round(c.pct);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${Math.abs(rounded)}${c.promo ? "*" : ""}`;
}

function share(v: number | null) {
  return v === null ? "不明" : `${Math.round(v * 100)}%`;
}

function missingNote(date: string, m: Missing) {
  const onlyExcl = m.excl.filter((c) => !m.incl.includes(c));
  const parts = [
    `${date} は、特売を除く系列で${m.excl.join("・")}を観測できなかった（観測できなかった比重 ${share(m.shareExcl)}）。`,
  ];
  if (m.incl.length > 0) {
    parts.push(
      `このうち${m.incl.join("・")}は、基準日と対応づけられる品を 1 つも観測できなかった（特売込みの系列で比重 ${share(m.shareIncl)}）。表ではこの日のセルを「—」にしている。`,
    );
  }
  if (onlyExcl.length > 0) {
    parts.push(`${onlyExcl.join("・")}は、基準日か当日に特売だった品しか観測できなかった。`);
  }
  return parts.join("");
}

export default function ItemTrails() {
  const { dates, omitted, groups, count, missing, alwaysUp } = buildTrails();
  if (dates.length === 0) return null;

  return (
    <section id="items" className={styles.trails}>
      <span className={`${styles.tag} ${styles.tagGold}`}>ITEM-LEVEL MOVES ／ 品目別の推移</span>
      <h2 className={styles.trailsHead}>何がいくら動いたか（基準日 {jin.base_date} 比 %）</h2>
      <p className={`${styles.jinMeta} mono`}>
        表の観測日に基準日から動いた {count} 品目 · {dates.length} 観測日 · 単一店舗 ·{" "}
        <span className={styles.up}>+ 値上がり</span> <span className={styles.down}>− 値下がり</span> · * 特売 ·
        「·」変化なし、または未観測 · 「—」分類ごと未観測 · † 一部の分類を観測できなかった日
      </p>

      <div className={styles.trailsScroll}>
        <table className={`${styles.trailsTable} mono`}>
          <thead>
            <tr>
              <th className={styles.trailsItem}>品目</th>
              {dates.map((d) => (
                <th key={d}>
                  {d.slice(5)}
                  {missing[d] ? "†" : ""}
                </th>
              ))}
            </tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.category}>
              <tr className={styles.trailsCat}>
                <th colSpan={dates.length + 1}>
                  <span className={styles.trailsCatLabel}>{g.category}</span>
                </th>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.item}>
                  <th className={styles.trailsItem}>{r.item}</th>
                  {dates.map((d) => {
                    const c = r.cells[d];
                    if (!c) {
                      const unobserved = missing[d]?.incl.includes(g.category);
                      return (
                        <td key={d} className={styles.flat}>
                          {unobserved ? "—" : "·"}
                        </td>
                      );
                    }
                    const cls = c.pct >= 0.5 ? styles.up : c.pct <= -0.5 ? styles.down : styles.flat;
                    return (
                      <td key={d} className={cls}>
                        {fmt(c)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>

      <ul className={styles.notes}>
        <li>
          値は同じ商品の基準日（{jin.base_date}）の価格に対する変化率。内容量の違う商品は別の商品として扱う。
        </li>
        {omitted.length > 0 && (
          <li>
            載せている観測日は {dates.map((d) => d.slice(5)).join("・")}。ほかに{" "}
            {omitted.map((d) => d.slice(5)).join("・")} にも観測しているが、表が横に長くなるので省いた。
          </li>
        )}
        <li>
          「·」の日は、その品が基準日と同じ価格だったか、その日の店頭で観測できなかったかのどちらか。公開データでは区別できない。
        </li>
        {Object.entries(missing).map(([d, m]) => (
          <li key={d}>{missingNote(d, m)}</li>
        ))}
        {alwaysUp.length > 0 && (
          <li>
            最初の観測日（{dates[0]}）からプラスで、一度もマイナスにならない品（{alwaysUp.join("、")}
            ）は、基準日の価格が特売や一時的な安値だった可能性がある。その場合、プラスには値上げではなく通常価格への戻りが含まれる。公開データだけではどちらか区別できない。
          </li>
        )}
      </ul>
    </section>
  );
}
