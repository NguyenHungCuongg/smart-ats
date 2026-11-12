import type { useTranslations } from "next-intl";

export type UsageFeature = {
  feature: string;
  calls: number;
  cost_usd: number;
};

export type UsageSummary = {
  month: string;
  scope: "TENANT" | "USER";
  budget_usd: number;
  total_cost_usd: number;
  total_calls: number;
  usage_ratio: number;
  budget_warning: boolean;
  features: UsageFeature[];
};

type Translator = ReturnType<typeof useTranslations<"usage">>;

const FEATURE_KEYS = {
  JOB_PARSE: "features.JOB_PARSE",
  CV_PARSE: "features.CV_PARSE",
  OCR: "features.OCR",
  SCORING: "features.SCORING",
  INTERVIEW_Q: "features.INTERVIEW_Q",
  EMAIL: "features.EMAIL",
  AGENT: "features.AGENT",
  EMBEDDING: "features.EMBEDDING",
} as const;

/** Current calendar month in UTC formatted as YYYY-MM (matches GET /api/usage). */
export function currentMonthUtc(now = new Date()): string {
  const year = now.getUTCFullYear();
  const month = String(now.getUTCMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

export function formatUsd(locale: string, value: number): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value);
}

export function formatPercent(locale: string, ratio: number): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(ratio);
}

export function featureLabel(t: Translator, feature: string): string {
  const key = FEATURE_KEYS[feature as keyof typeof FEATURE_KEYS];
  return key ? t(key) : feature;
}

export function usageError(t: Translator, status: number): string {
  if (status === 403) return t("forbidden");
  if (status === 422) return t("invalidMonth");
  return t("failed");
}
