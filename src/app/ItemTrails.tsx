import styles from "./page.module.css";
import jin from "@/data/jin_public.json";

// 品目別の推移（基準日比 %）。公開済みの movers_by_date から組み立てる。観測値のみ・予測ではない。
// movers_by_date には「その日に基準日から動いた品」しか載らないため、載っていない日は
// 「変化なし」か「未観測」かを区別できない。表では空欄（·）にして注記で明示する。

type Mover = { category: string; item: string; pct: number; promo_tag: boolean };
type Cell = { pct: number; promo: boolean };

function buildTrails() {
  const byDate = jin.movers_by_date as unknown as Record<string, Mover[]>;
  const dates = Object.keys(byDate).sort();
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
  const groups = categories.map((category) => ({
    category,
    rows: [...items.values()].filter((r) => r.category === category),
  }));
  return { dates, groups, count: items.size };
}

function fmt(c: Cell) {
  const rounded = Math.round(c.pct);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${Math.abs(rounded)}${c.promo ? "*" : ""}`;
}

export default function ItemTrails() {
  const { dates, groups, count } = buildTrails();
  if (dates.length === 0) return null;

  return (
    <section id="items" className={styles.trails}>
      <span className={`${styles.tag} ${styles.tagGold}`}>ITEM-LEVEL MOVES ／ 品目別の推移</span>
      <h2 className={styles.trailsHead}>何がいくら動いたか（基準日 {jin.base_date} 比 %）</h2>
      <p className={`${styles.jinMeta} mono`}>
        {count} 品目 · {dates.length} 観測日 · 単一店舗 · <span className={styles.up}>+ 値上がり</span>{" "}
        <span className={styles.down}>− 値下がり</span> · * 特売 · · 変化なし、または未観測
      </p>

      <div className={styles.trailsScroll}>
        <table className={`${styles.trailsTable} mono`}>
          <thead>
            <tr>
              <th className={styles.trailsItem}>品目</th>
              {dates.map((d) => (
                <th key={d}>{d.slice(5)}</th>
              ))}
            </tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.category}>
              <tr className={styles.trailsCat}>
                <th colSpan={dates.length + 1}>{g.category}</th>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.item}>
                  <th className={styles.trailsItem}>{r.item}</th>
                  {dates.map((d) => {
                    const c = r.cells[d];
                    if (!c) return <td key={d} className={styles.flat}>·</td>;
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
        <li>
          「·」の日は、その品が基準日と同じ価格だったか、その日の店頭で観測できなかったかのどちらか。公開データでは区別できない。
        </li>
        <li>
          最初の観測日からプラスが続く品（キャベツ、森永牛乳、ロイヤルブレッドなど）は、基準日の価格が特売や安値だったため。値上げではなく通常価格への戻り。
        </li>
      </ul>
    </section>
  );
}
