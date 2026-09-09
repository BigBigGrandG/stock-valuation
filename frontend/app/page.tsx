"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function TickerSearch() {
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();

  const EXAMPLES = [
    { ticker: "NVDA", name: "英伟达", sector: "AI / 算力芯片" },
    { ticker: "AAPL", name: "苹果", sector: "消费电子 / 生态" },
    { ticker: "MSFT", name: "微软", sector: "云计算 / 软件" },
    { ticker: "AVGO", name: "博通", sector: "通信半导体 / 软件" },
  ];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) {
      setError("请输入美股股票代码");
      return;
    }
    if (!/^[A-Z]{1,12}(?:[.-][A-Z0-9]{1,4})?$/.test(t)) {
      setError("请输入有效的美股代码（如 NVDA, AAPL，或股份类别代码 BRK.B, BRK-B）");
      return;
    }
    setError("");
    router.push(`/valuation/${t}`);
  }

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg">
        <h1 className="text-3xl font-bold text-white mb-2 text-center tracking-tight">
          美股估值分析平台
        </h1>
        <p className="text-gray-400 text-center mb-8 text-sm">
          集成市盈率（Forward P/E）、EV/EBITDA、自由现金流收益率（FCF Yield）及现金流折现（DCF）四套估值体系
        </p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={ticker}
              onChange={(e) => {
                setTicker(e.target.value.toUpperCase());
                setError("");
              }}
              placeholder="输入美股代码，如 NVDA / AAPL / MSFT / BRK.B"
              className="flex-1 px-4 py-3 rounded-lg bg-gray-800 text-white border border-gray-600 focus:outline-none focus:border-blue-500 text-base tracking-wider uppercase placeholder:text-gray-500 placeholder:normal-case"
              maxLength={15}
              autoFocus
              autoComplete="off"
            />
            <button
              type="submit"
              className="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold transition-colors shadow-md"
            >
              查询估值
            </button>
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
        </form>

        <div className="mt-8">
          <div className="text-xs text-gray-400 font-medium mb-3 text-center uppercase tracking-wider">
            常用美股标的示例
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {EXAMPLES.map((item) => (
              <button
                key={item.ticker}
                type="button"
                onClick={() => router.push(`/valuation/${item.ticker}`)}
                className="flex flex-col items-center p-3 rounded-lg bg-gray-900/80 border border-gray-800 hover:border-blue-500/50 hover:bg-gray-800/80 transition-all text-center group cursor-pointer"
              >
                <span className="text-base font-bold text-blue-400 group-hover:text-blue-300">
                  {item.ticker}
                </span>
                <span className="text-xs text-gray-300 mt-0.5">{item.name}</span>
                <span className="text-[10px] text-gray-500 mt-1">{item.sector}</span>
              </button>
            ))}
          </div>
        </div>

        <p className="mt-10 text-xs text-gray-500 text-center leading-relaxed">
          ⚠️ 本工具仅供金融教学与估值模型研究用途，不构成任何投资建议。市场数据由公开金融数据源提供，行情可能存在延迟，不保证实时价格；若标的使用固定测试数据将显示 DEMO 标识。
        </p>
      </div>
    </div>
  );
}
