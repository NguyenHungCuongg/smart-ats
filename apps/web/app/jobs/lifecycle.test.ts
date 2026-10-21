import { expect, test } from "vitest";

import { actionsFor, canEdit, transitionError } from "./lifecycle";

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
  expect(transitionError(409)).toBe("Trạng thái Job vừa thay đổi. Tải lại trang để xem.");
  expect(transitionError(500)).toBe("Không đổi được trạng thái Job. Vui lòng thử lại.");
});
