import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Japan Inflation Nowcast — 観測日誌",
  description:
    "東京近郊の単一スーパー店頭価格を毎日観測した、固定基準 Jevons の日次食品物価指数。予測ではなく観測。x402 で per-call 配信。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
