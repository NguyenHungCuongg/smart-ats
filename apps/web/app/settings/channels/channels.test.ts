import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { getChannelErrorMessage } from "./channels";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "channels" });

test("maps callback error codes to localized error messages", () => {
  // Vietnamese
  expect(getChannelErrorMessage(t("vi"), null)).toBeNull();
  expect(getChannelErrorMessage(t("vi"), "cancelled")).toBe("Đăng nhập Facebook đã bị hủy.");
  expect(getChannelErrorMessage(t("vi"), "no_role")).toContain(
    "vai trò (Admin, Developer, Tester)",
  );
  expect(getChannelErrorMessage(t("vi"), "no_pages")).toBe(
    "Tài khoản Facebook này không quản lý bất kỳ Facebook Page nào.",
  );
  expect(getChannelErrorMessage(t("vi"), "invalid_selection")).toBe(
    "Lựa chọn Page đã hết hạn hoặc không hợp lệ. Vui lòng kết nối lại.",
  );
  expect(getChannelErrorMessage(t("vi"), "oauth_failed")).toBe(
    "Kết nối Facebook thất bại. Vui lòng thử lại.",
  );

  // English
  expect(getChannelErrorMessage(t("en"), null)).toBeNull();
  expect(getChannelErrorMessage(t("en"), "cancelled")).toBe("Facebook login was cancelled.");
  expect(getChannelErrorMessage(t("en"), "no_role")).toContain("role (Admin, Developer, Tester)");
  expect(getChannelErrorMessage(t("en"), "no_pages")).toBe(
    "This Facebook account does not manage any Facebook Pages.",
  );
  expect(getChannelErrorMessage(t("en"), "invalid_selection")).toBe(
    "Page selection has expired or is invalid. Please try connecting again.",
  );
  expect(getChannelErrorMessage(t("en"), "oauth_failed")).toBe(
    "Facebook connection failed. Please try again.",
  );
});
