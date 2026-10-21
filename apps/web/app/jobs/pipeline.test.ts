import { expect, test } from "vitest";

import { type Card, ask, bulkTargets, moveError, targets, visible } from "./pipeline";

const card = (changes: Partial<Card>): Card => ({
  id: "a",
  full_name: "Nguyễn Văn An",
  stage: "APPLIED",
  rejected_reason: null,
  version: 0,
  source: "UPLOAD",
  total_score: null,
  file_name: "an.pdf",
  ...changes,
});

test("an active Application moves to any other Stage, either way", () => {
  expect(targets("INTERVIEW")).toEqual([
    "APPLIED",
    "SCREENING",
    "SHORTLISTED",
    "OFFER",
    "HIRED",
    "REJECTED",
  ]);
});

test("HIRED moves nowhere and REJECTED only reopens to an active Stage", () => {
  expect(targets("HIRED")).toEqual([]);
  expect(targets("REJECTED")).toEqual([
    "APPLIED",
    "SCREENING",
    "SHORTLISTED",
    "INTERVIEW",
    "OFFER",
  ]);
});

test("rejecting asks for an optional reason and reopening for a required one", () => {
  expect(ask("SCREENING", "REJECTED")).toBe("reject");
  expect(ask("REJECTED", "SCREENING")).toBe("reopen");
  expect(ask("APPLIED", "OFFER")).toBeNull();
});

test("a bulk move offers the Stages every selected card reaches without a reason", () => {
  const selected = [card({ stage: "APPLIED" }), card({ stage: "OFFER" })];
  expect(bulkTargets(selected)).toEqual([
    "SCREENING",
    "SHORTLISTED",
    "INTERVIEW",
    "HIRED",
    "REJECTED",
  ]);
  expect(bulkTargets([...selected, card({ stage: "REJECTED" })])).toEqual([]);
  expect(bulkTargets([card({ stage: "HIRED" })])).toEqual([]);
});

test("the filter keeps the cards of a source within a Total range", () => {
  const cards = [
    card({ id: "upload-80", total_score: 80 }),
    card({ id: "upload-40", total_score: 40 }),
    card({ id: "upload-none" }),
    card({ id: "apply-90", source: "PUBLIC_APPLY", total_score: 90 }),
  ];
  const ids = (filter: Parameters<typeof visible>[1]) => visible(cards, filter).map((c) => c.id);

  expect(ids({ source: "", min: "", max: "" })).toEqual([
    "upload-80",
    "upload-40",
    "upload-none",
    "apply-90",
  ]);
  expect(ids({ source: "UPLOAD", min: "", max: "" })).toEqual([
    "upload-80",
    "upload-40",
    "upload-none",
  ]);
  // A range leaves out the cards never scored.
  expect(ids({ source: "", min: "50", max: "" })).toEqual(["upload-80", "apply-90"]);
  expect(ids({ source: "UPLOAD", min: "40", max: "80" })).toEqual(["upload-80", "upload-40"]);
});

test("a refused move says why, and a conflict says the board reloads", () => {
  expect(moveError(409)).toBe(
    "Board vừa thay đổi hoặc thao tác không hợp lệ với stage hiện tại. Đã tải lại board.",
  );
  expect(moveError(422)).toBe("Mở lại Application cần ghi lý do.");
  expect(moveError(500)).toBe("Không đổi được stage. Vui lòng thử lại.");
});
