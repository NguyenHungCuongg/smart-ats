import { expect, test } from "vitest";

import { changeError, inviteError } from "./members";

test("inviting an existing Member and a malformed email each have their message", () => {
  expect(inviteError(409)).toBe("Email này đã là thành viên của Workspace.");
  expect(inviteError(422)).toBe("Email không hợp lệ.");
  expect(inviteError(500)).toBe("Không gửi được lời mời. Vui lòng thử lại.");
});

test("a change refused to keep a Company Admin says why", () => {
  expect(changeError(409)).toBe(
    "Workspace cần ít nhất một Company Admin, và bạn không thể tự thu hồi chính mình.",
  );
  expect(changeError(404)).toBe("Không tìm thấy thành viên hoặc lời mời này.");
  expect(changeError(500)).toBe("Không lưu được thay đổi. Vui lòng thử lại.");
});
