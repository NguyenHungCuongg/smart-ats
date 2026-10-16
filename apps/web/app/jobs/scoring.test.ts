import { expect, test } from "vitest";

import { scoreBlocker } from "./scoring";

const confirmed = { criteria_confirmed_at: "2026-10-16T08:00:00Z" };

test("a confirmed Job with Applications and no running run can be scored", () => {
  expect(scoreBlocker(confirmed, 2, null)).toBeNull();
  expect(scoreBlocker(confirmed, 2, { running: false })).toBeNull();
});

test("scoring waits for confirmed criteria, an Application and the running run", () => {
  expect(scoreBlocker({ criteria_confirmed_at: null }, 2, null)).toBe(
    "Xác nhận criteria trước khi chấm điểm.",
  );
  expect(scoreBlocker(confirmed, 0, null)).toBe("Job chưa có Application nào.");
  expect(scoreBlocker(confirmed, 2, { running: true })).toBe("Đang chấm điểm…");
});
