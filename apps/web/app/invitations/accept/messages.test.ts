import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { acceptError } from "./messages";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "accept" });

test("every spoiled invitation reads the same; other failures have their own message", () => {
  expect(acceptError(t("vi"), 200)).toBeNull();
  expect(acceptError(t("vi"), 400)).toBe(
    "Lời mời không hợp lệ hoặc đã hết hạn. Hãy nhờ Company Admin mời lại.",
  );
  expect(acceptError(t("vi"), 422)).toBe("Kiểm tra lại họ tên và mật khẩu.");
  expect(acceptError(t("vi"), 0)).toBe("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
  expect(acceptError(t("vi"), 500)).toBe("Không tạo được tài khoản. Vui lòng thử lại.");
});

test("in English too", () => {
  expect(acceptError(t("en"), 400)).toBe(
    "This invitation is invalid or has expired. Ask a Company Admin to invite you again.",
  );
  expect(acceptError(t("en"), 422)).toBe("Check your full name and password.");
  expect(acceptError(t("en"), 0)).toBe("Can't reach the server. Check your network and try again.");
  expect(acceptError(t("en"), 500)).toBe("Couldn't create the account. Please try again.");
});
