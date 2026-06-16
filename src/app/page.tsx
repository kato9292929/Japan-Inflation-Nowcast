import styles from "./page.module.css";
import { getJinLatest } from "@/lib/jin-data";
import jin from "@/data/jin_public.json";
import upstream from "@/data/upstream.json";

// 観測トレイル（excl_promo）。観測値のみ・予測ではない。固定基準 100。
function Sparkline({ data }: { data: number[] }) {
  const W = 600;
  const H = 76;
  const pad = 12;
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
      <polyline points={pts} fill="none" stroke="var(--gold)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="3.4" fill="var(--gold)" />
    </svg>
  );
}

// 食品 / 買い物のビジュアル帯。自前の簡易ライン画。near-black に金/緑デュオトーン。雰囲気づけのみ。
function FoodBand() {
  return (
    <svg className={styles.bandSvg} viewBox="0 0 800 180" preserveAspectRatio="xMidYMid meet" aria-hidden role="presentation">
      {/* カゴ */}
      <g stroke="var(--gold)" strokeWidth="2" fill="none" strokeLinejoin="round" strokeLinecap="round">
        <path d="M120 92 L168 150 L292 150 L340 92 Z" />
        <path d="M150 92 L165 150 M200 92 L210 150 M230 92 L230 150 M260 92 L250 150 M310 92 L295 150" opacity="0.5" />
        <path d="M150 70 q80 -34 160 0" />
      </g>
      {/* カゴの中身 — 葉物（緑）, 瓶（金）, りんご（緑） */}
      <g fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M198 92 q-10 -40 14 -56 q10 26 -2 56" stroke="var(--green)" />
        <path d="M206 40 q22 -14 40 -6 q-14 22 -38 14" stroke="var(--green)" />
        <rect x="244" y="50" width="26" height="42" rx="4" stroke="var(--gold)" />
        <path d="M252 50 l0 -12 l10 0 l0 12" stroke="var(--gold)" />
        <circle cx="300" cy="74" r="17" stroke="var(--green)" />
        <path d="M300 57 q4 -8 12 -8" stroke="var(--green)" />
      </g>
      {/* レシート + 価格ティッカー */}
      <g transform="translate(470 36)">
        <path d="M0 8 L0 132 L18 124 L36 132 L54 124 L72 132 L90 124 L108 132 L108 8 Z" fill="var(--panel-2)" stroke="var(--gold)" strokeWidth="2" strokeLinejoin="round" />
        <g stroke="var(--faint)" strokeWidth="2" strokeLinecap="round">
          <path d="M16 34 L92 34" />
          <path d="M16 50 L92 50" />
          <path d="M16 66 L76 66" />
        </g>
        <text x="16" y="98" fontFamily="IBM Plex Mono, monospace" fontSize="15" fill="var(--gold)">¥</text>
        <polyline points="34,96 48,86 60,92 74,78 90,84" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      </g>
      {/* 価格札 */}
      <g transform="translate(620 96)">
        <path d="M0 14 L20 0 L96 0 L96 44 L20 44 Z" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinejoin="round" />
        <circle cx="16" cy="22" r="4" fill="none" stroke="var(--green)" strokeWidth="2" />
        <text x="40" y="29" fontFamily="IBM Plex Mono, monospace" fontSize="16" fill="var(--green)">100</text>
      </g>
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
    <main className={styles.page}>
      {/* ヒーロー */}
      <header className={styles.head}>
        <p className={styles.eyebrow}>
          <span className={styles.dot} aria-hidden />
          OBSERVATION LOG ／ 観測日誌
        </p>
        <h1 className={styles.h1}>
          Japan Inflation <span className={styles.gold}>Nowcast</span>
        </h1>
        <p className={styles.kicker}>東京近郊・単一店舗の店頭食品価格を、毎日 観測。</p>
      </header>

      {/* 実測値パネル（主題） */}
      <section className={styles.panel} aria-label="JP-INFL-FOOD latest reading">
        <div className={`${styles.panelBar} mono`}>
          <span>JP-INFL-FOOD</span>
          <span>base {latest.base_date} = 100</span>
          <span>as of {latest.as_of}</span>
        </div>

        <div className={styles.reads}>
          <div className={styles.read}>
            <div className={styles.readLabel}>excl_promo · 基調（特売除外）</div>
            <div className={`${styles.readVal} mono`}>{excl.toFixed(2)}</div>
            <div className={`${styles.readDelta} ${styles[dExcl.cls]} mono`}>{dExcl.label}</div>
          </div>
          <div className={styles.read}>
            <div className={styles.readLabel}>incl_promo · 特売込</div>
            <div className={`${styles.readVal} mono`}>{incl.toFixed(2)}</div>
            <div className={`${styles.readDelta} ${styles[dIncl.cls]} mono`}>{dIncl.label}</div>
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

        <div className={styles.panelFoot}>
          <span className={`${styles.basket} mono`}>
            対象 {latest.matched_sku.incl} 品目 / 基調 {latest.matched_sku.excl} 取得
          </span>
          <span className={styles.legend}>
            基準比 <span className={styles.up}>▲ 上昇</span> <span className={styles.down}>▼ 下降</span>
          </span>
        </div>
        <p className={styles.cond}>単一店舗・固定基準 Jevons・毎日 手で取得</p>
      </section>

      {/* 食品 / 買い物ビジュアル */}
      <div className={styles.band}>
        <FoodBand />
      </div>

      {/* 上流（実数つき・降格） */}
      <section className={styles.section}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>上流</span>マクロの文脈
        </h2>
        <ul className={styles.upstream}>
          {upstream.items.map((it) => (
            <li key={it.source_url} className={styles.upRow}>
              <span className={`${styles.upDate} mono`}>{it.date}</span>
              <span className={styles.upTitle}>{it.title}</span>
              {it.value ? <span className={`${styles.upVal} ${styles.gold} mono`}>{it.value}</span> : null}
              <a className={`${styles.upSrc} mono`} href={it.source_url} target="_blank" rel="noopener noreferrer">
                {it.source_label} ↗
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* endpoints */}
      <section className={styles.section}>
        <h2 className={styles.h2}>
          <span className={styles.h2num}>配信</span>endpoints
        </h2>
        <ul className={styles.eps}>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/latest</code>
            <span className={styles.epDesc}>最新観測日の指数。観測値 + matched + 方法論。</span>
            <span className={`${styles.badge} ${styles.badgeFree} mono`}>200 ✓ free</span>
          </li>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/series</code>
            <span className={styles.epDesc}>指数の時系列。機械向け。</span>
            <span className={`${styles.badge} mono`}>HTTP/1.1 402 ✓ $0.01</span>
          </li>
          <li className={styles.epRow}>
            <code className={`${styles.epPath} mono`}>GET /api/jin/movers</code>
            <span className={styles.epDesc}>その日動いた品目。特売タグ付き。機械向け。</span>
            <span className={`${styles.badge} mono`}>HTTP/1.1 402 ✓ $0.02</span>
          </li>
        </ul>
        <p className={styles.epNote}>
          決済は Solana USDC。discovery は{" "}
          <a className={`${styles.gold} mono`} href="/.well-known/x402.json">/.well-known/x402.json</a>。
        </p>
      </section>

      {/* 注記 */}
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
