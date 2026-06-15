export default function Home() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 720, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Japan Inflation Nowcast — x402 API</h1>
      <p>
        独立系・日次の食品価格<strong>観測</strong>指数（予測ではありません）。単一店舗・東京メトロ配送圏・
        中価格帯スーパー。全国代表性はありません。
      </p>
      <ul>
        <li>
          <code>GET /api/jin/latest</code> — 無料。最新観測日の指数。
        </li>
        <li>
          <code>GET /api/jin/series?from=&amp;to=</code> — $0.01 (Solana USDC, x402)。時系列。
        </li>
        <li>
          <code>GET /api/jin/movers?date=</code> — $0.02 (Solana USDC, x402)。指定日の mover SKU。
        </li>
        <li>
          <code>GET /.well-known/x402.json</code> — 有料2本の discovery。
        </li>
      </ul>
      <p>観測値 + 方法論 + movers のみを返します。確率・予測値は返しません。</p>
    </main>
  );
}
