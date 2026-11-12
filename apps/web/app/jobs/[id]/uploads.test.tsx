import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { Batch } from "../uploads";
import { BatchProgress } from "./uploads";

const makeBatch = (
  status: "PENDING" | "SUCCEEDED" | "FAILED",
  error_code: string | null,
): Batch => ({
  id: "batch-1",
  status: status === "PENDING" ? "PROCESSING" : "COMPLETED",
  total: 1,
  processed: status === "PENDING" ? 0 : 1,
  failed: status === "FAILED" ? 1 : 0,
  created_at: "2026-11-12T00:00:00Z",
  items: [
    {
      id: "item-1",
      file_name: "candidate.pdf",
      status,
      dedupe: null,
      error_code,
      error_message: null,
    },
  ],
});

const render = (locale: Locale, batch: Batch) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <BatchProgress
        batch={batch}
        canRetry={true}
        onRetry={() => {}}
        retryingId={null}
        onRetryFailed={() => {}}
      />
    </NextIntlClientProvider>,
  );

test("shows one-click Retry button only on LLM_UNAVAILABLE failed upload items", () => {
  const html = render("en", makeBatch("FAILED", "LLM_UNAVAILABLE"));
  expect(html).toContain('aria-label="Retry candidate.pdf"');
  expect(html).toContain(">Retry</button>");
  expect(html).toContain("The AI service was temporarily unavailable.");
  expect(html).not.toContain('type="file"');
  expect(html).not.toContain("Fix the file");

  const viHtml = render("vi", makeBatch("FAILED", "LLM_UNAVAILABLE"));
  expect(viHtml).toContain('aria-label="Thử lại candidate.pdf"');
  expect(viHtml).toContain("Dịch vụ AI tạm thời không khả dụng.");
});

test("keeps re-upload control for file errors and hides retry controls for succeeded items", () => {
  const corrupt = render("en", makeBatch("FAILED", "UNREADABLE"));
  expect(corrupt).toContain('type="file"');
  expect(corrupt).toContain("Fix the file");
  expect(corrupt).not.toContain(">Retry</button>");

  const ok = render("en", makeBatch("SUCCEEDED", null));
  expect(ok).not.toContain("Retry");
  expect(ok).not.toContain('type="file"');
});
