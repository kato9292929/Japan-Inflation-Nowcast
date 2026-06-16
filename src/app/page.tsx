import styles from "./page.module.css";
import { getJinLatest } from "@/lib/jin-data";
import jin from "@/data/jin_public.json";
import upstream from "@/data/upstream.json";

// 末端の観測トレイル（excl_promo）。観測値のみ・予測ではない。固定基準 100。
function Sparkline({ data }: { data: number[] }) {
  const W = 560;
  const H = 64;
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
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="var(--rule)" strokeWidth="1" strokeDasharray="2 4" />
      <polyline points={pts} fill="none" stroke="var(--ink)" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="3.2" fill="var(--vermilion)" />
    </svg>
  );
}

export default function Home() {
  const latest = getJinLatest();
  const trail = jin.series.map((r) => r.excl);

  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <p className={styles.eyebrow}>
          <span className={styles.seal} aria-hidden>
            観測
          </span>
          OBSERVATION LOG ／ 観測日誌
        </p>
        <h1 className={styles.h1}>Japan Inflation Nowcast</h1>
        <p className={styles.kicker}>
          東京近郊・単一店舗の店頭価格を、毎日 手で観測する。予測ではなく観測。
        </p>
      </header>

      {/* 1. 上流 — マクロの文脈 */}
      <section className={styles.section}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>上流</span>マクロの文脈
        </h2>
        <p className={styles.lead}>
          末端の店頭価格を読むための背景。主役ではない。一次ソースへのリンクのみを置く。
        </p>
        <ul className={styles.upstream}>
          {upstream.items.map((it) => (
            <li key={it.source_url} className={styles.upRow}>
              <span className={`${styles.upDate} mono`}>{it.date}</span>
              <a className={styles.upTitle} href={it.source_url} target="_blank" rel="noopener noreferrer">
                {it.title}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* 2. 上流から末端へ落ちる導線 */}
      <div className={styles.flow} aria-hidden>
        <span className={styles.flowLine} />
        <span className={styles.flowLabel}>上流から末端へ流れ落ちる</span>
        <span className={styles.flowArrow}>↓</span>
      </div>

      {/* 3. 末端 — 主題 */}
      <section className={`${styles.section} ${styles.terminal}`}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>末端</span>店頭の食品物価（主題）
        </h2>
        <div className={`${styles.meta} mono`}>
          <span>JP-INFL-FOOD</span>
          <span>base {latest.base_date} = 100</span>
          <span>as of {latest.as_of}</span>
        </div>

        <div className={styles.reads}>
          <div className={styles.read}>
            <div className={styles.readLabel}>excl_promo · 基調（特売除外）</div>
            <div className={`${styles.readVal} mono`}>{latest.index.excl_promo.toFixed(2)}</div>
            <div className={`${styles.readSub} mono`}>matched {latest.matched_sku.excl} SKU</div>
          </div>
          <div className={styles.read}>
            <div className={styles.readLabel}>incl_promo · 特売込</div>
            <div className={`${styles.readVal} mono`}>{latest.index.incl_promo.toFixed(2)}</div>
            <div className={`${styles.readSub} mono`}>matched {latest.matched_sku.incl} SKU</div>
          </div>
        </div>

        <div className={styles.spark}>
          <Sparkline data={trail} />
          <div className={`${styles.sparkAxis} mono`}>
            <span>{jin.series[0].date}</span>
            <span>excl_promo · baseline 100</span>
            <span>{jin.series[jin.series.length - 1].date}</span>
          </div>
        </div>
      </section>

      {/* 4. endpoints */}
      <section className={styles.section}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>配信</span>endpoints
        </h2>
        <ul className={styles.eps}>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/latest</code>
            <span className={styles.epDesc}>最新観測日の指数。観測値 + matched + 方法論。</span>
            <span className={`${styles.epPrice} mono`}>free</span>
          </li>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/series</code>
            <span className={styles.epDesc}>指数の時系列。x402（機械向け）。</span>
            <span className={`${styles.epPrice} ${styles.paid} mono`}>$0.01 · 402</span>
          </li>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/movers</code>
            <span className={styles.epDesc}>その日動いた品目。特売タグ付き。x402（機械向け）。</span>
            <span className={`${styles.epPrice} ${styles.paid} mono`}>$0.02 · 402</span>
          </li>
        </ul>
        <p className={styles.epNote}>
          有料系列は機械向けの 402 応答。決済は Solana USDC。詳細は{" "}
          <a className="mono" href="/.well-known/x402.json">/.well-known/x402.json</a> を参照。
        </p>
      </section>

      {/* 5. 注記 */}
      <section className={styles.section}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>注記</span>観測条件
        </h2>
        <ul className={styles.notes}>
          <li>日次・固定基準（{latest.base_date} = 100）の Jevons 指数。マッチした同一 SKU の幾何平均。</li>
          <li>{latest.coverage_note}</li>
          <li>excl_promo は基準日・当日いずれかで特売タグの付いた SKU を除外した基調系列。</li>
          <li>これは観測であって予測ではない。確率値や見通しは返さない。</li>
        </ul>
      </section>

      <footer className={styles.footer}>
        <span>x402 Inc. — Tokyo</span>
        <a href="https://note.com/x402inc">note.com/x402inc</a>
      </footer>
    </main>
  );
}
