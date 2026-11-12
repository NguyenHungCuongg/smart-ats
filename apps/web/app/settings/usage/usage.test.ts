import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { currentMonthUtc, featureLabel, formatPercent, formatUsd, usageError } from "./usage";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "usage" });

test("currentMonthUtc formats UTC year and month as YYYY-MM", () => {
  expect(currentMonthUtc(new Date("2026-01-05T23:59:59Z"))).toBe("2026-01");
  expect(currentMonthUtc(new Date("2026-12-01T00:00:00Z"))).toBe("2026-12");
});

test("USD and ratio formatters honor locale conventions", () => {
  expect(formatUsd("en", 12.3456)).toBe("$12.3456");
  expect(formatUsd("en", 50)).toBe("$50.00");
  expect(formatPercent("en", 0.825)).toBe("82.5%");
  expect(formatPercent("vi", 0.8)).toContain("80");
});

test("usageError maps 403, 422, and fallback status codes in both languages", () => {
  expect(usageError(t("vi"), 403)).toBe(
    "Chỉ Company Admin và Recruiter mới được xem mức sử dụng AI.",
  );
  expect(usageError(t("en"), 403)).toBe("Only Company Admins and Recruiters can view AI usage.");
  expect(usageError(t("vi"), 422)).toBe("Chọn tháng hợp lệ theo định dạng YYYY-MM.");
  expect(usageError(t("en"), 422)).toBe("Choose a valid month in YYYY-MM format.");
  expect(usageError(t("vi"), 500)).toBe("Không tải được dữ liệu sử dụng AI. Vui lòng thử lại.");
  expect(usageError(t("en"), 500)).toBe("Couldn't load AI usage. Please try again.");
});

test("featureLabel translates all ledger features and falls back to raw code", () => {
  expect(featureLabel(t("en"), "CV_PARSE")).toBe("CV parsing");
  expect(featureLabel(t("en"), "OCR")).toBe("Document OCR");
  expect(featureLabel(t("vi"), "SCORING")).toBe("Chấm điểm ứng viên");
  expect(featureLabel(t("vi"), "INTERVIEW_Q")).toBe("Câu hỏi phỏng vấn");
  expect(featureLabel(t("en"), "EMAIL")).toBe("Email drafting");
  expect(featureLabel(t("vi"), "AGENT")).toBe("Trợ lý AI");
  expect(featureLabel(t("en"), "CUSTOM_OP")).toBe("CUSTOM_OP");
});
