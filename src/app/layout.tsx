import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  metadataBase: new URL("https://jin.x402jp.com"),
  title: "Japan Inflation Nowcall — x402 API",
  description:
    "東京近郊・単一店舗の店頭食品価格を毎日観測した、固定基準 Jevons の日次食品物価指数。予測ではなく観測。x402 で per-call 配信。",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Japan Inflation Nowcall — x402 API",
    description:
      "東京近郊・単一店舗の店頭食品価格を毎日観測した、固定基準 Jevons の日次食品物価指数。予測ではなく観測。x402 で per-call 配信。",
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
