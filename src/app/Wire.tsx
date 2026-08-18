"use client";

import { useEffect, useState, type ReactNode } from "react";
import styles from "./page.module.css";

type Lang = "en" | "ja";

// upstream.json の item 形。_ja は optional（欠けても英語に落とす）。
type Item = {
  category: string;
  headline: string;
  headline_ja?: string;
  summary: string;
  summary_ja?: string;
  date: string;
};
type Tick = { label: string; value: string };

// _ja が無い / 空文字なら英語に落とす。データ欠けで空表示にしない。
function pickText(item: Item, key: "headline" | "summary", lang: Lang): string {
  const jaVal = key === "headline" ? item.headline_ja : item.summary_ja;
  const enVal = key === "headline" ? item.headline : item.summary;
  return (lang === "ja" ? jaVal ?? "" : "") || enVal || "";
}

export default function Wire({
  items,
  ticker,
  baseDate,
  coverageNote,
  children,
}: {
  items: Item[];
  ticker: Tick[];
  baseDate: string;
  coverageNote: string;
  children: ReactNode;
}) {
  // SSR は必ず "en" で描く（hydration mismatch を出さない）。
  const [lang, setLang] = useState<Lang>("en");

  // localStorage の読み出しは mount 後にのみ行う。
  useEffect(() => {
    const saved = window.localStorage.getItem("jin.lang");
    if (saved === "ja" || saved === "en") setLang(saved);
  }, []);

  // <html lang> をトグルに追従（任意）。
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const pick = (l: Lang) => {
    setLang(l);
    window.localStorage.setItem("jin.lang", l);
  };

  const ja = lang === "ja";
  const jaCls = ja ? ` ${styles.jaText}` : "";
  const hero = items[0];
  const left = items.slice(1, 4);
  const right = items.slice(4);

  return (
    <div className={styles.shell}>
      {/* マストヘッド */}
      <header className={styles.masthead}>
        <a className={styles.logo} href="#top" aria-label="Japan Inflation Nowcall">
          JIN
        </a>
        <span className={styles.wordmark}>Japan Inflation Nowcall</span>
        <nav className={styles.nav}>
          <a href="#macro">MACRO WIRE</a>
          <a href="#food">FOOD INDEX</a>
          <a href="#api">API</a>
        </nav>
        <div className={styles.langToggle} role="group" aria-label="language">
          <button
            type="button"
            className={ja ? styles.langOn : styles.langOff}
            aria-pressed={ja}
            onClick={() => pick("ja")}
          >
            JP
          </button>
          <span className={styles.langSep}>|</span>
          <button
            type="button"
            className={!ja ? styles.langOn : styles.langOff}
            aria-pressed={!ja}
            onClick={() => pick("en")}
          >
            EN
          </button>
        </div>
      </header>

      {/* 市況ティッカー */}
      <div className={`${styles.ticker} mono`} aria-label="market snapshot">
        {ticker.map((tk) => (
          <span key={tk.label} className={styles.tick}>
            <span className={styles.tickLabel}>{tk.label}</span>
            <span className={styles.tickVal}>{tk.value}</span>
          </span>
        ))}
      </div>

      <main id="top">
        {/* 1. マクロ・ニュースのグリッド（WIRED 風）。見出し・本文のみ言語切替。 */}
        <section id="macro" className={styles.grid}>
          {/* 左レール */}
          <div className={styles.colL}>
            <span className={styles.tag}>TODAY&apos;S PICKS</span>
            {left.map((it) => (
              <article key={it.headline} className={styles.railItem}>
                <span className={styles.kicker}>{it.category}</span>
                <h3 className={`${styles.railHead}${jaCls}`}>{pickText(it, "headline", lang)}</h3>
                <p className={`${styles.railDek}${jaCls}`}>{pickText(it, "summary", lang)}</p>
                <span className={`${styles.byline} mono`}>{it.date}</span>
              </article>
            ))}
          </div>

          {/* 中央リード + API/NOTES を記事として */}
          <div className={styles.colC}>
            <article className={styles.lead}>
              <span className={`${styles.kicker} ${styles.kickerC}`}>{hero.category}</span>
              <h1
                className={`${styles.heroHead}${ja ? ` ${styles.heroHeadJa}${jaCls}` : ""}`}
              >
                {pickText(hero, "headline", lang)}
              </h1>
              <p className={`${styles.heroDek}${jaCls}`}>{pickText(hero, "summary", lang)}</p>
              <span className={`${styles.byline} mono`}>MACRO WIRE · {hero.date}</span>
            </article>

            <article id="api" className={styles.cArticle}>
              <span className={styles.kicker}>API ENDPOINTS</span>
              <ul className={styles.eps}>
                <li className={styles.epRow}>
                  <div className={styles.epTop}>
                    <code className={`${styles.epPath} mono`}>GET /api/jin/latest</code>
                    <span className={`${styles.badge} ${styles.badgeFree} mono`}>200 ✓ free</span>
                  </div>
                  <span className={styles.epDesc}>最新観測日の指数。観測値 + matched + 方法論。</span>
                </li>
                <li className={styles.epRow}>
                  <div className={styles.epTop}>
                    <code className={`${styles.epPath} mono`}>GET /api/jin/series</code>
                    <span className={`${styles.badge} mono`}>HTTP/1.1 402 ✓ $0.01</span>
                  </div>
                  <span className={styles.epDesc}>指数の時系列。機械向け。</span>
                </li>
                <li className={styles.epRow}>
                  <div className={styles.epTop}>
                    <code className={`${styles.epPath} mono`}>GET /api/jin/movers</code>
                    <span className={`${styles.badge} mono`}>HTTP/1.1 402 ✓ $0.02</span>
                  </div>
                  <span className={styles.epDesc}>その日動いた品目。特売タグ付き。機械向け。</span>
                </li>
              </ul>
              <p className={styles.epNote}>
                決済は Solana USDC。discovery は{" "}
                <a className={`${styles.goldLink} mono`} href="/.well-known/x402.json">
                  /.well-known/x402.json
                </a>
                。
              </p>
            </article>

            <article className={styles.cArticle}>
              <span className={styles.kicker}>METHOD / NOTES</span>
              <ul className={styles.notes}>
                <li>
                  日次・固定基準（{baseDate} = 100）の Jevons 指数。マッチした同一 SKU の幾何平均。
                </li>
                <li>{coverageNote}</li>
                <li>excl_promo は基準日・当日いずれかで特売タグの付いた SKU を除外した基調系列。</li>
                <li>これは観測であって予測ではない。確率値や見通しは返さない。</li>
              </ul>
            </article>
          </div>

          {/* 右レール */}
          <div className={styles.colR}>
            <span className={styles.tag}>MARKETS</span>
            {right.map((it) => (
              <article key={it.headline} className={styles.railRItem}>
                <span className={styles.kicker}>{it.category}</span>
                <h3 className={`${styles.railRHead}${jaCls}`}>{pickText(it, "headline", lang)}</h3>
              </article>
            ))}
          </div>
        </section>

        {/* food セクション・footer（ドメイン言語固定・切替対象外）は page.tsx から children で受ける */}
        {children}
      </main>
    </div>
  );
}
