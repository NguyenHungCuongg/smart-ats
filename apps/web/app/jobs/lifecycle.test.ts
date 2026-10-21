import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { actionsFor, canEdit, transitionError } from "./lifecycle";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "lifecycle" });

test("each status offers exactly the edges of FR-A3.1", () => {
  expect(actionsFor("DRAFT")).toEqual(["publish"]);
  expect(actionsFor("PUBLISHED")).toEqual(["pause", "close"]);
  expect(actionsFor("PAUSED")).toEqual(["resume", "close"]);
  expect(actionsFor("CLOSED")).toEqual(["archive", "reopen"]);
  expect(actionsFor("ARCHIVED")).toEqual([]);
});

test("only Company Admins and Recruiters edit, and nobody edits an archived Job", () => {
  expect(canEdit("COMPANY_ADMIN", "DRAFT")).toBe(true);
  expect(canEdit("RECRUITER", "CLOSED")).toBe(true);
  expect(canEdit("RECRUITER", "ARCHIVED")).toBe(false);
  expect(canEdit("REVIEWER", "PUBLISHED")).toBe(false);
});

test("a refused transition tells the Recruiter to reload", () => {
  expect(transitionError(t("vi"), 409)).toBe("Trạng thái Job vừa thay đổi. Tải lại trang để xem.");
  expect(transitionError(t("vi"), 500)).toBe("Không đổi được trạng thái Job. Vui lòng thử lại.");
  expect(transitionError(t("en"), 409)).toBe(
    "The Job's status just changed. Reload the page to see it.",
  );
  expect(transitionError(t("en"), 500)).toBe("Couldn't change the Job's status. Please try again.");
});
