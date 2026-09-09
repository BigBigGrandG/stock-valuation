import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "美股估值分析 | Stock Valuation",
  description: "US stock valuation using Forward P/E, EV/EBITDA, FCF Yield, and DCF models",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-gray-950 text-gray-100 antialiased">
        {children}
      </body>
    </html>
  );
}
