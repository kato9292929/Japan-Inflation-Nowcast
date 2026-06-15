import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Japan Inflation Nowcast — x402 API",
  description:
    "日本のスーパー店頭価格を毎日観測した日次食品物価指数。予測ではなく観測。x402 で per-call 配信。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,600;1,9..144,900&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
