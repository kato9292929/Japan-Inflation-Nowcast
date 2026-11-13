"use client";

import styles from "./page.module.css";
import { useLang, type Lang } from "./lang";

// 品目別の推移の表示側。集計済みの値（ItemTrails から渡る）を JP/EN トグルに合わせて描く。
// 数値・記号（· — † *）は言語によらず同じ。変わるのは見出し・凡例・注記・品目名・分類名だけ。

export type Cell = { pct: number; promo: boolean };
export type Missing = { excl: string[]; incl: string[]; shareExcl: number | null; shareIncl: number | null };
type Row = { category: string; item: string; cells: Record<string, Cell> };
type Labels = { categories: Record<string, string>; items: Record<string, string> };

type Props = {
  dates: string[];
  omitted: string[];
  groups: { category: string; rows: Row[] }[];
  count: number;
  missing: Record<string, Missing>;
  alwaysUp: string[];
  baseDate: string;
  labelsEn: Labels;
};

function fmt(c: Cell) {
  const rounded = Math.round(c.pct);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${Math.abs(rounded)}${c.promo ? "*" : ""}`;
}

function share(v: number | null, lang: Lang) {
  if (v === null) return lang === "ja" ? "不明" : "unknown";
  return `${Math.round(v * 100)}%`;
}

const md = (d: string) => d.slice(5);

export default function ItemTrailsView({ dates, omitted, groups, count, missing, alwaysUp, baseDate, labelsEn }: Props) {
  const lang = useLang();
  const ja = lang === "ja";
  // 英語名が無い名前は日本語のまま出す（データ欠けで空表示にしない）。
  const cat = (c: string) => (ja ? c : labelsEn.categories[c] ?? c);
  const item = (i: string) => (ja ? i : labelsEn.items[i] ?? i);
  const cats = (cs: string[]) => {
    const names = cs.map(cat);
    if (ja) return names.join("・");
    return names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  };

  const missingNote = (date: string, m: Missing) => {
    const onlyExcl = m.excl.filter((c) => !m.incl.includes(c));
    const parts: string[] = [];
    if (ja) {
      parts.push(`${date} は、特売を除く系列で${cats(m.excl)}を観測できなかった（観測できなかった比重 ${share(m.shareExcl, lang)}）。`);
      if (m.incl.length > 0) {
        parts.push(
          `このうち${cats(m.incl)}は、基準日と対応づけられる品を 1 つも観測できなかった（特売込みの系列で比重 ${share(m.shareIncl, lang)}）。表ではこの日のセルを「—」にしている。`,
        );
      }
      if (onlyExcl.length > 0) parts.push(`${cats(onlyExcl)}は、基準日か当日に特売だった品しか観測できなかった。`);
    } else {
      parts.push(
        `On ${date}, ${cats(m.excl)} could not be observed in the excl-promo series (unobserved weight ${share(m.shareExcl, lang)}).`,
      );
      if (m.incl.length > 0) {
        parts.push(
          `Of these, ${cats(m.incl)} had no item matching the base date at all (weight ${share(m.shareIncl, lang)} in the incl-promo series); their cells for that day show “—”.`,
        );
      }
      if (onlyExcl.length > 0) {
        parts.push(`For ${cats(onlyExcl)}, only items on promotion on the base date or that day were observed.`);
      }
    }
    return parts.join(ja ? "" : " ");
  };

  return (
    <section id="items" className={styles.trails} lang={lang}>
      <span className={`${styles.tag} ${styles.tagGold}`}>ITEM-LEVEL MOVES ／ 品目別の推移</span>
      <h2 className={styles.trailsHead}>
        {ja ? `何がいくら動いたか（基準日 ${baseDate} 比 %）` : `What moved, and by how much (% vs base ${baseDate})`}
      </h2>
      {ja ? (
        <p className={`${styles.jinMeta} mono`}>
          表の観測日に基準日から動いた {count} 品目 · {dates.length} 観測日 · 単一店舗 ·{" "}
          <span className={styles.up}>+ 値上がり</span> <span className={styles.down}>− 値下がり</span> · * 特売 ·
          「·」変化なし、または未観測 · 「—」分類ごと未観測 · † 一部の分類を観測できなかった日
        </p>
      ) : (
        <p className={`${styles.jinMeta} mono`}>
          {count} items that moved vs base on the dates shown · {dates.length} observation dates · single store ·{" "}
          <span className={styles.up}>+ up</span> <span className={styles.down}>− down</span> · * promo · “·”
          unchanged or not observed · “—” whole category not observed · † some categories not observed that day
        </p>
      )}

      <div className={styles.trailsScroll}>
        <table className={`${styles.trailsTable} mono`}>
          <thead>
            <tr>
              <th className={styles.trailsItem}>{ja ? "品目" : "Item"}</th>
              {dates.map((d) => (
                <th key={d}>
                  {md(d)}
                  {missing[d] ? "†" : ""}
                </th>
              ))}
            </tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.category}>
              <tr className={styles.trailsCat}>
                <th colSpan={dates.length + 1}>
                  <span className={styles.trailsCatLabel}>{cat(g.category)}</span>
                </th>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.item}>
                  <th className={styles.trailsItem}>{item(r.item)}</th>
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
          {ja
            ? `値は同じ商品の基準日（${baseDate}）の価格に対する変化率。内容量の違う商品は別の商品として扱う。`
            : `Each value is the change from the same product's price on the base date (${baseDate}). A different pack size counts as a different product.`}
        </li>
        {omitted.length > 0 && (
          <li>
            {ja
              ? `載せている観測日は ${dates.map(md).join("・")}。ほかに ${omitted.map(md).join("・")} にも観測しているが、表が横に長くなるので省いた。`
              : `Dates shown: ${dates.map(md).join(", ")}. We also observed on ${omitted.map(md).join(", ")}, but left those dates out to keep the table narrow.`}
          </li>
        )}
        <li>
          {ja
            ? "「·」の日は、その品が基準日と同じ価格だったか、その日の店頭で観測できなかったかのどちらか。公開データでは区別できない。"
            : "On a “·” date, the item was either at its base-date price or not observed in store that day. The public data cannot tell these apart."}
        </li>
        {Object.entries(missing).map(([d, m]) => (
          <li key={d}>{missingNote(d, m)}</li>
        ))}
        {alwaysUp.length > 0 && (
          <li>
            {ja
              ? `最初の観測日（${dates[0]}）からプラスで、一度もマイナスにならない品（${alwaysUp.map(item).join("、")}）は、基準日の価格が特売や一時的な安値だった可能性がある。その場合、プラスには値上げではなく通常価格への戻りが含まれる。公開データだけではどちらか区別できない。`
              : `Items that are up from the first date (${dates[0]}) and never negative (${alwaysUp.map(item).join("; ")}) may have had a promotional or temporarily low price on the base date. If so, part of the rise is a return to the regular price, not a price increase. The public data alone cannot tell which.`}
          </li>
        )}
      </ul>
    </section>
  );
}
