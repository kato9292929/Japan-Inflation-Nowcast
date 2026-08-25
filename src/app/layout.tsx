import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  metadataBase: new URL("https://jin.x402jp.com"),
  title: "Japan Inflation Nowcall — x402 API",
  description:
    "東京のあるスーパーの店頭価格を毎日記録して作る、独自の物価指数です。10カテゴリ等加重のJevons幾何平均で日次指数化し、上流のCGPI（企業物価）も取り込むことで、上流から店頭までを接続して観測します。x402エンドポイントとして配信し、per-callで購入できます。",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Japan Inflation Nowcall — x402 API",
    description:
      "東京のあるスーパーの店頭価格を毎日記録して作る、独自の物価指数です。10カテゴリ等加重のJevons幾何平均で日次指数化し、上流のCGPI（企業物価）も取り込むことで、上流から店頭までを接続して観測します。x402エンドポイントとして配信し、per-callで購入できます。",
    url: "https://jin.x402jp.com",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,600&family=Roboto+Condensed:wght@500;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
