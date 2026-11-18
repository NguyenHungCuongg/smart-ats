import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { ActivityEntry } from "../activity";
import { ActivityList } from "./activity";

const ACTOR = { id: "u-1", full_name: "Nguyễn Văn An" };

const ENTRIES: ActivityEntry[] = [
  {
    id: "e-1",
    action: "application.stage_changed",
    actor_type: "USER",
    actor: ACTOR,
    before: { stage: "APPLIED" },
    after: { stage: "SCREENING" },
    created_at: "2026-11-18T10:00:00Z",
  },
  {
    id: "e-2",
    action: "application.created",
    actor_type: "PUBLIC",
    actor: null,
    before: null,
    after: {
      source: "PUBLIC_APPLY",
      candidate_id: "c-1",
      cv_document_id: "cv-1",
      stage: "APPLIED",
    },
    created_at: "2026-11-18T09:00:00Z",
  },
];

const renderList = (
  locale: Locale,
  props: {
    items: ActivityEntry[] | null;
    nextCursor?: string | null;
    loadingMore?: boolean;
    failed?: boolean;
  },
) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <ActivityList
        items={props.items}
        nextCursor={props.nextCursor ?? null}
        loadingMore={props.loadingMore ?? false}
        failed={props.failed ?? false}
        onLoadMore={() => {}}
      />
    </NextIntlClientProvider>,
  );

test("renders activity entries with badges and load-more button in vi and en", () => {
  const viHtml = renderList("vi", { items: ENTRIES, nextCursor: "cursor-1" });
  expect(viHtml).toContain("Nguyễn Văn An đã chuyển Application từ Applied sang Screening.");
  expect(viHtml).toContain(
    "Ứng viên (Public Apply) đã tạo Application (Public Apply, Stage Applied).",
  );
  expect(viHtml).toContain("Public Apply");
  expect(viHtml).toContain("Tải thêm");

  const enHtml = renderList("en", { items: ENTRIES, nextCursor: null });
  expect(enHtml).toContain("Nguyễn Văn An moved the Application from Applied to Screening.");
  expect(enHtml).toContain(
    "Candidate (Public Apply) created the Application (Public Apply, Stage Applied).",
  );
  expect(enHtml).not.toContain("Load more");
});

test("renders loading, empty, and error states", () => {
  expect(renderList("en", { items: null })).toContain('aria-busy="true"');
  expect(renderList("en", { items: [] })).toContain("No activity yet.");
  expect(renderList("vi", { items: null, failed: true })).toContain('role="alert"');
});
