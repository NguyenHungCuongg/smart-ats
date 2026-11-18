import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import type { Card } from "../pipeline";
import { KanbanCard } from "./pipeline";

const CARD: Card = {
  id: "app-1",
  full_name: "Nguyễn Văn An",
  email: null,
  stage: "APPLIED",
  rejected_reason: null,
  version: 0,
  source: "UPLOAD",
  total_score: 84.5,
  file_name: "an.pdf",
};

const renderCard = (
  locale: Locale,
  { editable = true, activityOpen = false }: { editable?: boolean; activityOpen?: boolean } = {},
) =>
  renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <KanbanCard
        card={CARD}
        editable={editable}
        selected={false}
        onSelect={() => {}}
        onMove={() => {}}
        asking={null}
        onAnswer={() => {}}
        onCancel={() => {}}
        activityOpen={activityOpen}
        onOpenActivity={() => {}}
      />
    </NextIntlClientProvider>,
  );

test("renders Activity button on KanbanCard even when read-only (Reviewer or ARCHIVED Job)", () => {
  const readOnlyEn = renderCard("en", { editable: false, activityOpen: false });
  expect(readOnlyEn).toContain('aria-label="Activity of Nguyễn Văn An"');
  expect(readOnlyEn).toContain('aria-expanded="false"');
  expect(readOnlyEn).toContain(">Activity</button>");
  expect(readOnlyEn).not.toContain("<select");

  const openVi = renderCard("vi", { editable: false, activityOpen: true });
  expect(openVi).toContain('aria-label="Hoạt động của Nguyễn Văn An"');
  expect(openVi).toContain('aria-expanded="true"');
  expect(openVi).toContain(">Hoạt động</button>");
});
