// All backend communication lives here so pages remain presentation-only.
import type { OverrideRequest, ValuationResponse } from "./types";

const BACKEND_URL = (
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8002"
).replace(/\/$/, "");

export interface ParsedError {
  title: string;
  message: string;
  code: string;
  advice?: string;
}

export class ApiError extends Error {
  public status: number;
  public detail?: unknown;
  public code?: string;
  public actionableTitle: string;
  public actionableAdvice?: string;

  constructor(
    status: number,
    message: string,
    detail?: unknown,
    code?: string,
    actionableTitle?: string,
    actionableAdvice?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.actionableTitle = actionableTitle || defaultTitleForStatus(status);
    this.actionableAdvice = actionableAdvice;
  }
}

function defaultTitleForStatus(status: number): string {
  switch (status) {
    case 404:
      return "未找到股票标的或暂无财务覆盖";
    case 429:
      return "数据源请求频率超限";
    case 503:
      return "上游金融数据服务暂不可用";
    case 422:
      return "标的暂不适用或数据校验未通过";
    case 0:
      return "网络连接失败或请求超时";
    default:
      return "查询未完成";
  }
}

function extractRawMessage(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail.trim();
  if (typeof detail === "object") {
    const rec = detail as Record<string, unknown>;
    const target = rec.detail ?? rec.message ?? rec.reason ?? rec.error;
    if (typeof target === "string") return target.trim();
    if (Array.isArray(target)) {
      return target
        .map((x) => (typeof x === "string" ? x : (x as Record<string, unknown>)?.msg || ""))
        .filter(Boolean)
        .join("；");
    }
  }
  return "";
}

export function parseApiError(status: number, detail: unknown, ticker = ""): ParsedError {
  const t = ticker ? ticker.toUpperCase() : "";

  if (status === 404) {
    return {
      title: "未找到股票标的或暂无财务覆盖",
      message: t
        ? `未找到股票代码 "${t}" 或上游数据源暂无该标的完整的财务报表与估算数据。`
        : "未找到该股票代码，或暂无该标的的财务数据覆盖。",
      code: "NOT_FOUND",
      advice: "请核对代码拼写是否正确（例如 NVDA、AAPL、MSFT、BRK.B 等知名美股），或尝试其他已覆盖标的。",
    };
  }

  if (status === 429) {
    return {
      title: "数据源请求频率超限 (Rate Limit)",
      message: "上游金融数据接口请求过于频繁，触发了服务商的访问频率限制。",
      code: "RATE_LIMITED",
      advice: "数据服务商限制了短时间内的请求频次，请稍候 30 至 60 秒后再点击“重试”。",
    };
  }

  if (status === 503) {
    const raw = extractRawMessage(detail);
    return {
      title: "上游金融数据服务暂不可用",
      message: raw && !raw.includes("<!DOCTYPE")
        ? `上游财务数据服务连接中断或响应异常：${raw}`
        : "上游金融数据服务暂时不可用或网络连接超时。",
      code: "UPSTREAM_UNAVAILABLE",
      advice: "外部金融数据接口可能正在短暂维护或响应缓慢，请稍后点击“重试”重新发起请求。",
    };
  }

  if (status === 422) {
    if (detail && typeof detail === "object") {
      const rec = detail as Record<string, unknown>;
      const inner = (rec.detail && typeof rec.detail === "object" ? rec.detail : rec) as Record<string, unknown>;
      const errType = String(inner.error || "");

      if (errType === "unsupported_company_type") {
        const reason = inner.reason ? String(inner.reason).toLowerCase() : "";
        const detailMsg = inner.detail ? String(inner.detail).toLowerCase() : "";

        // Specifically identify ETFs, mutual funds, indices, and non-equity assets
        if (
          reason.includes("etf") ||
          reason.includes("mutualfund") ||
          reason.includes("fund") ||
          reason.includes("index") ||
          reason.includes("cryptocurrency") ||
          reason.includes("crypto") ||
          reason.includes("currency_pair") ||
          reason.includes("forex") ||
          reason.includes("future") ||
          reason.includes("option") ||
          reason.includes("spac") ||
          detailMsg.includes("non-equity") ||
          detailMsg.includes("etf")
        ) {
          const nonEquityName = reason.includes("etf") || detailMsg.includes("etf")
            ? "交易所交易基金（ETF）"
            : reason.includes("fund")
            ? "共同基金（Mutual Fund）"
            : reason.includes("index")
            ? "指数标的（Index）"
            : reason.includes("crypto")
            ? "加密货币资产（Crypto）"
            : reason.includes("spac")
            ? "特殊目的收购公司（SPAC）"
            : "非普通股标的（Non-equity）";

          return {
            title: `不支持非普通股标的：${nonEquityName}`,
            message: `${t ? `标的 "${t}" ` : ""}属于${nonEquityName}。此类非个股资产无单一实业公司的财报与现金流数据，不适用内置个股估值模型（DCF / PE / EV / FCF）。`,
            code: "UNSUPPORTED_NON_EQUITY",
            advice: "本系统专用于美股上市公司普通股估值（包含普通股如 NVDA、AAPL、MSFT，以及股份类别如 BRK.B 等），暂不支持 ETF 或指数基金。请输入美股个股代码。",
          };
        }

        // Specifically identify currency mismatch, ADRs or non-USD statements
        if (
          reason.includes("currency_mismatch") ||
          reason.includes("mismatched_currency") ||
          reason.includes("adr") ||
          detailMsg.includes("currency mismatch") ||
          detailMsg.includes("currency") ||
          detailMsg.includes("adr")
        ) {
          return {
            title: "财务报表记账币种与交易币种不一致",
            message: `${t ? `标的 "${t}" ` : ""}官方财务报表记账币种与美股行情币种（USD）不一致（如在美上市 ADR 或非美元财报）。系统遵循会计准则，不对未经审计的跨期汇率做主观编造折算。`,
            code: "UNSUPPORTED_CURRENCY_MISMATCH",
            advice: "建议关注不受汇率跨币种影响的相对估值模型，或查询以美元为财报记账本位币的美股标的。",
          };
        }

        // Specifically identify non-US companies
        if (reason.includes("non_us") || detailMsg.includes("country=")) {
          return {
            title: "暂不支持非美股上市标的",
            message: `${t ? `标的 ${t} ` : ""}注册地或主要上市地非美国本土市场，当前估值系统仅支持美股上市公司（NYSE / NASDAQ）。`,
            code: "UNSUPPORTED_NON_US",
            advice: "请查询美股主要交易所上市的普通股标的。",
          };
        }

        // Specifically identify financial institutions (banks, insurance, brokers)
        if (
          reason.includes("financial") ||
          detailMsg.includes("financial") ||
          reason.includes("bank") ||
          reason.includes("insurance")
        ) {
          return {
            title: "金融机构估值模型受限",
            message: `${t ? `标的 ${t} ` : ""}属于金融服务或银保类机构。由于其存款与负债属于经营性资产，标准企业自由现金流（FCFF DCF）及 EV/EBITDA 模型不直接适用。`,
            code: "UNSUPPORTED_FINANCIAL",
            advice: "建议关注市盈率等适应金融机构特征的估值方法，或查询非金融实体运营公司。",
          };
        }

        // Specifically identify REITs
        if (reason.includes("reit") || detailMsg.includes("reit")) {
          return {
            title: "REITs 标的估值模型受限",
            message: `${t ? `标的 ${t} ` : ""}属于房地产投资信托（REITs），其高分红及特殊折旧结构不适用传统企业 DCF/PE 估值框架。`,
            code: "UNSUPPORTED_REIT",
            advice: "建议查询普通商业实体企业（如 NVDA、AAPL、MSFT 等）。",
          };
        }

        // Specifically identify loss-making companies
        if (reason.includes("loss") || detailMsg.includes("loss")) {
          return {
            title: "公司近期处于亏损状态",
            message: `${t ? `标的 ${t} ` : ""}近期财务数据显示净利润或自由现金流为负，依赖正盈利的四套估值模型无法计算有效公允目标价。`,
            code: "UNSUPPORTED_LOSS_MAKER",
            advice: "对于亏损或早期高成长企业，建议参考市销率（P/S）或等待基本面拐点。",
          };
        }

        return {
          title: "标的类型暂不适用当前估值模型",
          message: `${t ? `标的 ${t} ` : ""}当前暂无适用的估值模型方案。`,
          code: "UNSUPPORTED_COMPANY",
          advice: "建议查询美股市场具备稳定经营现金流的普通股标的（如 NVDA、AAPL、MSFT、BRK.B 等）。",
        };
      }

      if (errType === "invalid_ticker") {
        return {
          title: "股票代码格式无效",
          message: `输入的股票代码 "${t}" 格式不合规。`,
          code: "INVALID_TICKER",
          advice: "美股股票代码支持标准字母代码（如 NVDA、AAPL）以及带股份类别的代码（如 BRK.B、BRK-B 等）。",
        };
      }

      if (errType === "financial_data_validation") {
        return {
          title: "财务数据缺失或校验未通过",
          message: "该公司上报的财报数据不完整或缺少必要估值科目（如前瞻一致预测、稀释股数或经营现金流）。",
          code: "FINANCIAL_VALIDATION_ERROR",
          advice: "模型坚持不伪造缺失数据；对于缺乏必要财务输入项的公司暂无法完成公允估值计算。",
        };
      }

      if (errType === "invalid_override") {
        const raw = typeof inner.detail === "string" ? inner.detail : "";
        return {
          title: "假设参数超出合理取值范围",
          message: raw || "填写的覆盖假设参数超出财务合理范围或破坏约束条件。",
          code: "INVALID_OVERRIDE",
          advice: "请检查输入的参数（例如：WACC 必须大于永续增长率，永续增长率上限通常为 5%）。",
        };
      }
    }

    const rawMsg = extractRawMessage(detail);
    return {
      title: "数据校验未通过或标的不适用",
      message: rawMsg || "输入的参数或从上游获取的报表数据不满足模型计算规范。",
      code: "VALIDATION_FAILED",
      advice: "请确认输入参数无误后重试。",
    };
  }

  const rawMsg = extractRawMessage(detail);
  return {
    title: `查询未完成（HTTP ${status}）`,
    message: rawMsg || "服务端在处理请求或模型计算时发生异常，请稍候重试。",
    code: "SERVER_ERROR",
    advice: "请确认后端服务运行状态正常后重试。",
  };
}

async function handleResponse<T>(res: Response, ticker = ""): Promise<T> {
  const contentType = res.headers.get("content-type") || "";
  if (!res.ok) {
    let detail: unknown;
    if (contentType.includes("application/json")) {
      try {
        detail = await res.json();
      } catch {
        // ignore json parse error
      }
    } else {
      const text = await res.text().catch(() => "");
      if (text.trim()) detail = text;
    }
    const parsed = parseApiError(res.status, detail, ticker);
    throw new ApiError(
      res.status,
      parsed.message,
      detail,
      parsed.code,
      parsed.title,
      parsed.advice,
    );
  }
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      res.status,
      "后端返回了非 JSON 响应，请检查 API 地址或服务状态。",
      undefined,
      "INVALID_CONTENT_TYPE",
      "返回格式异常",
      "请检查后端 API 服务返回内容。",
    );
  }
  return res.json() as Promise<T>;
}

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: OverrideRequest;
  signal?: AbortSignal;
  timeoutMs?: number;
  pathSuffix?: string;
}

export async function requestValuation(
  ticker: string,
  options: RequestOptions = {},
): Promise<ValuationResponse> {
  const timeoutMs = options.timeoutMs ?? 45000;
  const controller = new AbortController();

  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort("TIMEOUT");
  }, timeoutMs);

  const onCallerAbort = () => {
    controller.abort(options.signal?.reason || "ABORTED");
  };

  if (options.signal) {
    if (options.signal.aborted) {
      clearTimeout(timeoutId);
      throw new DOMException("The user aborted a request.", "AbortError");
    }
    options.signal.addEventListener("abort", onCallerAbort);
  }

  const path = options.pathSuffix || "";
  const url = `${BACKEND_URL}/api/v1/valuation/${encodeURIComponent(ticker)}${path}`;

  try {
    const res = await fetch(url, {
      method: options.method || "GET",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
      signal: controller.signal,
    });
    return await handleResponse<ValuationResponse>(res, ticker);
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (timedOut || controller.signal.reason === "TIMEOUT") {
      throw new ApiError(
        0,
        `请求超时（耗时超过 ${Math.round(timeoutMs / 1000)} 秒）。上游金融数据获取耗时较长，请点击“重试”或稍候再次查询。`,
        error,
        "TIMEOUT",
        "请求超时",
        "外部金融数据接口响应较慢，您可以点击重试或稍后再试。",
      );
    }
    if (
      options.signal?.aborted ||
      (error instanceof DOMException && error.name === "AbortError")
    ) {
      throw error;
    }
    throw new ApiError(
      0,
      `无法连接到后端估值服务（${BACKEND_URL}）。请确认后端服务进程已启动且网络畅通。`,
      error,
      "NETWORK_ERROR",
      "后端服务未连接",
      "请检查本地后端服务（端口 8002）是否正常运行。",
    );
  } finally {
    clearTimeout(timeoutId);
    if (options.signal) {
      options.signal.removeEventListener("abort", onCallerAbort);
    }
  }
}

export function fetchValuation(
  ticker: string,
  signalOrOptions?: AbortSignal | { signal?: AbortSignal; timeoutMs?: number },
): Promise<ValuationResponse> {
  if (signalOrOptions instanceof AbortSignal) {
    return requestValuation(ticker, { signal: signalOrOptions });
  }
  return requestValuation(ticker, signalOrOptions);
}

export function postValuationOverride(
  ticker: string,
  overrides: OverrideRequest,
  signal?: AbortSignal,
): Promise<ValuationResponse> {
  return requestValuation(ticker, { method: "POST", body: overrides, signal });
}

export function resetValuation(
  ticker: string,
  signalOrOptions?: AbortSignal | { signal?: AbortSignal; timeoutMs?: number },
): Promise<ValuationResponse> {
  if (signalOrOptions instanceof AbortSignal) {
    return requestValuation(ticker, { signal: signalOrOptions });
  }
  return requestValuation(ticker, signalOrOptions);
}

export { BACKEND_URL };

