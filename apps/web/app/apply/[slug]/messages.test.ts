import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { applyError } from "./messages";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "apply" });

test("applyError maps statuses to translation keys in Vietnamese", () => {
  expect(applyError(t("vi"), 200)).toBeNull();
  expect(applyError(t("vi"), 201)).toBeNull();
  expect(applyError(t("vi"), 400)).toBe("Không gửi được hồ sơ ứng tuyển. Vui lòng thử lại.");
  expect(applyError(t("vi"), 402)).toBe(
    "Vị trí này tạm ngưng tiếp nhận hồ sơ do đã hết hạn mức xử lý AI. Vui lòng thử lại sau.",
  );
  expect(applyError(t("vi"), 404)).toBe("Liên kết ứng tuyển không tồn tại hoặc đã bị xóa.");
  expect(applyError(t("vi"), 409)).toBe("Vị trí này hiện không nhận hồ sơ ứng tuyển mới.");
  expect(applyError(t("vi"), 429)).toBe(
    "Bạn đã nộp hồ sơ quá nhiều lần. Vui lòng thử lại sau 1 giờ.",
  );
  expect(applyError(t("vi"), 500)).toBe("Không gửi được hồ sơ ứng tuyển. Vui lòng thử lại.");
  expect(applyError(t("vi"), 0)).toBe("Không gửi được hồ sơ ứng tuyển. Vui lòng thử lại.");
});

test("applyError maps statuses to translation keys in English", () => {
  expect(applyError(t("en"), 200)).toBeNull();
  expect(applyError(t("en"), 201)).toBeNull();
  expect(applyError(t("en"), 400)).toBe("Failed to submit application. Please try again.");
  expect(applyError(t("en"), 402)).toBe(
    "Applications for this position are temporarily paused. Please try again later.",
  );
  expect(applyError(t("en"), 404)).toBe(
    "This application link does not exist or has been removed.",
  );
  expect(applyError(t("en"), 409)).toBe("This position is no longer accepting new applications.");
  expect(applyError(t("en"), 429)).toBe(
    "Too many submission attempts. Please try again after 1 hour.",
  );
  expect(applyError(t("en"), 500)).toBe("Failed to submit application. Please try again.");
  expect(applyError(t("en"), 0)).toBe("Failed to submit application. Please try again.");
});
