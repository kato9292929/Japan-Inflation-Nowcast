import styles from "./page.module.css";
import Wire from "./Wire";
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

  return (
    <Wire
      items={upstream.items}
      ticker={upstream.ticker}
      baseDate={latest.base_date}
      coverageNote={latest.coverage_note}
    >
      {/* 2. 食品物価の観測（記事の下）。ドメイン言語固定・言語切替の対象外。 */}
      <section id="food" className={styles.jin}>
        <span className={`${styles.tag} ${styles.tagGold}`}>
          FOOD PRICE OBSERVATION ／ JP-INFL-FOOD
        </span>
        <div className={styles.jinGrid}>
          <div className={styles.jinIntro}>
            <h2 className={styles.jinHead}>Tokyo store-front food prices, observed daily</h2>
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
    </Wire>
  );
}
