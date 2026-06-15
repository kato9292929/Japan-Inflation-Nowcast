import styles from "./page.module.css";

// excl_promo 8 日間（Day-1..Day-8）。観測値（予測ではない）。
const SPARK = [100.0, 100.8157, 100.8157, 100.5871, 100.7978, 100.8157, 99.5403, 99.5923];

function Sparkline({ data }: { data: number[] }) {
  const W = 600;
  const H = 88;
  const pad = 12;
  const min = Math.min(...data, 100);
  const max = Math.max(...data, 100);
  const span = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * W;
  const y = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad);
  const pts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const baseY = y(100).toFixed(1);
  const lastX = x(data.length - 1).toFixed(1);
  const lastY = y(data[data.length - 1]).toFixed(1);
  return (
    <svg className={styles.sparkSvg} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <line x1="0" y1={baseY} x2={W} y2={baseY} stroke="var(--faint)" strokeWidth="1" strokeDasharray="3 4" />
      <polyline points={pts} fill="none" stroke="var(--cold)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="3.4" fill="var(--signal)" />
    </svg>
  );
}

export default function Home() {
  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>
        <span className={styles.dot} aria-hidden />
        日次食品物価インデックス
      </p>

      <h1 className={styles.h1}>
        Japan Inflation Nowcast <span className={styles.gold}>× x402</span>
      </h1>

      {/* 計器パネル */}
      <section className={styles.panel} aria-label="JP-INFL-FOOD instrument panel">
        <div className={styles.panelBar}>
          <span>JP-INFL-FOOD ／ base 2026-06-04</span>
          <span>as of 2026-06-12</span>
        </div>

        <div className={styles.gauges}>
          <div className={styles.gauge}>
            <div className={styles.gaugeLabel}>excl_promo · 基調</div>
            <div className={`${styles.gaugeVal} ${styles.cold} ${styles.display}`}>99.59</div>
            <div className={styles.gaugeDelta}>−0.41 vs base</div>
            <div className={styles.gaugeSub}>特売除外 · matched 45</div>
          </div>
          <div className={styles.gauge}>
            <div className={styles.gaugeLabel}>incl_promo · 特売込</div>
            <div className={`${styles.gaugeVal} ${styles.cold} ${styles.display}`}>99.53</div>
            <div className={styles.gaugeDelta}>−0.47 vs base</div>
            <div className={styles.gaugeSub}>全 matched 56</div>
          </div>
          <div className={styles.gauge}>
            <div className={styles.gaugeLabel}>上流 CGPI · 前年比</div>
            <div className={`${styles.gaugeVal} ${styles.warm} ${styles.display}`}>+6.3%</div>
            <div className={styles.gaugeDelta}>日銀 企業物価 2026-05</div>
            <div className={styles.gaugeSub}>末端は逆向きに割れる →</div>
          </div>
        </div>

        <div className={styles.spark}>
          <Sparkline data={SPARK} />
          <div className={styles.sparkAxis}>
            <span>Day-1</span>
            <span>excl_promo · baseline 100</span>
            <span>Day-8</span>
          </div>
        </div>
      </section>

      {/* Endpoints */}
      <section className={styles.endpoints}>
        <div className={styles.endpointRow}>
          <div className={styles.epMain}>
            <div className={styles.epPath}>
              <span className={styles.verb}>GET</span>/api/jin/latest
            </div>
            <div className={styles.epDesc}>最新観測日の指数。観測値 + matched + 方法論 + coverage。</div>
          </div>
          <div className={`${styles.epPrice} ${styles.cold}`}>free</div>
        </div>
        <div className={styles.endpointRow}>
          <div className={styles.epMain}>
            <div className={styles.epPath}>
              <span className={styles.verb}>GET</span>/api/jin/series?from=&amp;to=
            </div>
            <div className={styles.epDesc}>指数の時系列。Solana USDC で per-call 決済。</div>
          </div>
          <div className={`${styles.epPrice} ${styles.gold}`}>$0.01</div>
        </div>
        <div className={styles.endpointRow}>
          <div className={styles.epMain}>
            <div className={styles.epPath}>
              <span className={styles.verb}>GET</span>/api/jin/movers?date=
            </div>
            <div className={styles.epDesc}>その日動いた品目。特売タグ付き。POS 集計では潰れる層。</div>
          </div>
          <div className={`${styles.epPrice} ${styles.gold}`}>$0.02</div>
        </div>
      </section>

      <footer className={styles.footer}>
        <span>x402 Inc. — Tokyo</span>
        <a href="https://note.com/x402inc">note.com/x402inc</a>
      </footer>
    </main>
  );
}
