import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { loginError } from "./messages";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "login" });

test("each failure has its own message; only 401 means a wrong password", () => {
  expect(loginError(t("vi"), 200)).toBeNull();
  expect(loginError(t("vi"), 401)).toBe("Email hoặc mật khẩu không đúng.");
  expect(loginError(t("vi"), 429)).toBe("Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau.");
  expect(loginError(t("vi"), 0)).toBe("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
  expect(loginError(t("vi"), 500)).toBe("Đăng nhập không thành công. Vui lòng thử lại.");
});

test("in English too", () => {
  expect(loginError(t("en"), 401)).toBe("Wrong email or password.");
  expect(loginError(t("en"), 429)).toBe("Too many failed logins. Please try again later.");
  expect(loginError(t("en"), 0)).toBe("Can't reach the server. Check your network and try again.");
  expect(loginError(t("en"), 500)).toBe("Couldn't log in. Please try again.");
});
