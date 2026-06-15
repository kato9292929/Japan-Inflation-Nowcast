import type { ReactNode } from "react";

export const metadata = {
  title: "Japan Inflation Nowcast API",
  description: "x402 endpoints for an independent daily food-price observation index (not a forecast).",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
