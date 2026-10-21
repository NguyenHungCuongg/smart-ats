import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../../i18n/locale";
import { CATALOGS } from "../../../i18n/messages";
import { changeError, inviteError } from "./members";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "members" });

test("inviting an existing Member and a malformed email each have their message", () => {
  expect(inviteError(t("vi"), 409)).toBe("Email này đã là thành viên của Workspace.");
  expect(inviteError(t("vi"), 422)).toBe("Email không hợp lệ.");
  expect(inviteError(t("vi"), 500)).toBe("Không gửi được lời mời. Vui lòng thử lại.");
  expect(inviteError(t("en"), 409)).toBe("This email is already a Member of the Workspace.");
  expect(inviteError(t("en"), 422)).toBe("Invalid email.");
  expect(inviteError(t("en"), 500)).toBe("Couldn't send the invitation. Please try again.");
});

test("a change refused to keep a Company Admin says why", () => {
  expect(changeError(t("vi"), 409)).toBe(
    "Workspace cần ít nhất một Company Admin, và bạn không thể tự thu hồi chính mình.",
  );
  expect(changeError(t("vi"), 404)).toBe("Không tìm thấy thành viên hoặc lời mời này.");
  expect(changeError(t("vi"), 500)).toBe("Không lưu được thay đổi. Vui lòng thử lại.");
  expect(changeError(t("en"), 409)).toBe(
    "The Workspace needs at least one Company Admin, and you can't revoke yourself.",
  );
  expect(changeError(t("en"), 404)).toBe("This Member or invitation wasn't found.");
  expect(changeError(t("en"), 500)).toBe("Couldn't save the change. Please try again.");
});
