import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { newestOnly, scoreBlocker } from "./scoring";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "scoring" });

const confirmed = { criteria_confirmed_at: "2026-10-16T08:00:00Z" };

test("a confirmed Job with Applications and no running run can be scored", () => {
  expect(scoreBlocker(t("vi"), confirmed, 2, null)).toBeNull();
  expect(scoreBlocker(t("vi"), confirmed, 2, { running: false })).toBeNull();
});

test("scoring waits for confirmed criteria, an Application and the running run", () => {
  expect(scoreBlocker(t("vi"), { criteria_confirmed_at: null }, 2, null)).toBe(
    "Xác nhận criteria trước khi chấm điểm.",
  );
  expect(scoreBlocker(t("vi"), confirmed, 0, null)).toBe("Job chưa có Application nào.");
  expect(scoreBlocker(t("vi"), confirmed, 2, { running: true })).toBe("Đang chấm điểm…");
  expect(scoreBlocker(t("en"), { criteria_confirmed_at: null }, 2, null)).toBe(
    "Confirm the criteria before scoring.",
  );
  expect(scoreBlocker(t("en"), confirmed, 0, null)).toBe("The Job has no Applications yet.");
  expect(scoreBlocker(t("en"), confirmed, 2, { running: true })).toBe("Scoring…");
});

test("a load that finishes after a newer one is dropped", async () => {
  const shown: string[] = [];
  const load = newestOnly<string>((value) => shown.push(value));
  let finishOld!: (value: string) => void;

  const old = load(new Promise((resolve) => (finishOld = resolve)));
  await load(Promise.resolve("new run"));
  finishOld("old run");
  await old;

  expect(shown).toEqual(["new run"]);
});
