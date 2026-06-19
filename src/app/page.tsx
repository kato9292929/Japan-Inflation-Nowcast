import styles from "./page.module.css";
import { getJinLatest } from "@/lib/jin-data";
import jin from "@/data/jin_public.json";
import upstream from "@/data/upstream.json";

// 観測トレイル（excl_promo）。観測値のみ・予測ではない。固定基準 100。
function Sparkline({ data }: { data: number[] }) {
  const W = 600;
  const H = 70;
  const pad = 10;
  const min = Math.min(...data, 100);
  const max = Math.max(...data, 100);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (data.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad);
  const pts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const baseY = y(100).toFixed(1);
  const lastX = x(data.length - 1).toFixed(1);
  const lastY = y(data[data.length - 1]).toFixed(1);
  return (
    <svg className={styles.sparkSvg} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="var(--line)" strokeWidth="1" strokeDasharray="3 4" />
      <polyline points={pts} fill="none" stroke="var(--ink)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="3.6" fill="var(--gold)" stroke="var(--ink)" strokeWidth="0.8" />
    </svg>
  );
}

function delta(v: number) {
  const d = v - 100;
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  const cls = d > 0 ? "up" : d < 0 ? "down" : "flat";
  return { label: `${sign}${Math.abs(d).toFixed(2)} vs base`, cls };
}

export default function Home() {
  const latest = getJinLatest();
  const trail = jin.series.map((r) => r.excl);
  const excl = latest.index.excl_promo;
  const incl = latest.index.incl_promo;
  const dExcl = delta(excl);
  const dIncl = delta(incl);

  const hero = upstream.items[0];
  const left = upstream.items.slice(1, 4);
  const right = upstream.items.slice(4);

  return (
    <div className={styles.shell}>
      {/* マストヘッド */}
      <header className={styles.masthead}>
        <a className={styles.logo} href="#top" aria-label="Japan Inflation Nowcast">
          JIN
        </a>
        <span className={styles.wordmark}>Japan Inflation Nowcast</span>
        <nav className={styles.nav}>
          <a href="#macro">MACRO WIRE</a>
          <a href="#food">FOOD INDEX</a>
          <a href="#api">API</a>
        </nav>
      </header>

      {/* 市況ティッカー */}
      <div className={`${styles.ticker} mono`} aria-label="market snapshot">
        {upstream.ticker.map((t) => (
          <span key={t.label} className={styles.tick}>
            <span className={styles.tickLabel}>{t.label}</span>
            <span className={styles.tickVal}>{t.value}</span>
          </span>
        ))}
      </div>

      <main id="top">
        {/* 1. マクロ・ニュースのグリッド（WIRED 風） */}
        <section id="macro" className={styles.grid}>
          {/* 左レール */}
          <div className={styles.colL}>
            <span className={styles.tag}>TODAY&apos;S PICKS</span>
            {left.map((it) => (
              <article key={it.headline} className={styles.railItem}>
                <span className={styles.kicker}>{it.category}</span>
                <h3 className={styles.railHead}>{it.headline}</h3>
                <p className={styles.railDek}>{it.summary}</p>
                <span className={`${styles.byline} mono`}>{it.date}</span>
              </article>
            ))}
          </div>

          {/* 中央リード + API/NOTES を記事として */}
          <div className={styles.colC}>
            <article className={styles.lead}>
              <span className={`${styles.kicker} ${styles.kickerC}`}>{hero.category}</span>
              <h1 className={styles.heroHead}>{hero.headline}</h1>
              <p className={styles.heroDek}>{hero.summary}</p>
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
                <a className={`${styles.goldLink} mono`} href="/.well-known/x402.json">/.well-known/x402.json</a>。
              </p>
            </article>

            <article className={styles.cArticle}>
              <span className={styles.kicker}>METHOD / NOTES</span>
              <ul className={styles.notes}>
                <li>日次・固定基準（{latest.base_date} = 100）の Jevons 指数。マッチした同一 SKU の幾何平均。</li>
                <li>{latest.coverage_note}</li>
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
                <h3 className={styles.railRHead}>{it.headline}</h3>
              </article>
            ))}
          </div>
        </section>

        {/* 2. 食品物価の観測（記事の下） */}
        <section id="food" className={styles.jin}>
          <span className={`${styles.tag} ${styles.tagGold}`}>
            FOOD PRICE OBSERVATION ／ JP-INFL-FOOD
          </span>
          <div className={styles.jinGrid}>
            <div className={styles.jinIntro}>
              <h2 className={styles.jinHead}>
                Tokyo store-front food prices, observed daily
              </h2>
              <p className={`${styles.jinMeta} mono`}>
                base {latest.base_date} = 100 · as of {latest.as_of} · 単一店舗 · 固定基準 Jevons · 毎日 手で取得
              </p>
            </div>

            <div className={styles.reads}>
              <div className={styles.read}>
                <div className={styles.readLabel}>excl_promo · 基調（特売除外）</div>
                <div className={`${styles.readVal} mono`}>{excl.toFixed(2)}</div>
                <div className={`${styles.readDelta} ${styles[dExcl.cls]} mono`}>
                  {dExcl.label} · matched {latest.matched_sku.excl}
                </div>
              </div>
              <div className={styles.read}>
                <div className={styles.readLabel}>incl_promo · 特売込</div>
                <div className={`${styles.readVal} mono`}>{incl.toFixed(2)}</div>
                <div className={`${styles.readDelta} ${styles[dIncl.cls]} mono`}>
                  {dIncl.label} · matched {latest.matched_sku.incl}
                </div>
              </div>
            </div>
          </div>

          <div className={styles.spark}>
            <Sparkline data={trail} />
            <div className={`${styles.sparkAxis} mono`}>
              <span>{jin.series[0].date}</span>
              <span>
                excl_promo · baseline 100 ·{" "}
                <span className={styles.up}>▲ 上昇</span> <span className={styles.down}>▼ 下降</span>
              </span>
              <span>{jin.series[jin.series.length - 1].date}</span>
            </div>
          </div>
        </section>

        <footer className={styles.footer}>
          <span>x402 Inc. — Tokyo</span>
          <a href="https://note.com/x402inc">note.com/x402inc</a>
        </footer>
      </main>
    </div>
  );
}
