import { expect, test } from "vitest";

import { acceptError } from "./messages";

test("every spoiled invitation reads the same; other failures have their own message", () => {
  expect(acceptError(200)).toBeNull();
  expect(acceptError(400)).toBe(
    "Lời mời không hợp lệ hoặc đã hết hạn. Hãy nhờ Company Admin mời lại.",
  );
  expect(acceptError(422)).toBe("Kiểm tra lại họ tên và mật khẩu.");
  expect(acceptError(0)).toBe("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
  expect(acceptError(500)).toBe("Không tạo được tài khoản. Vui lòng thử lại.");
});
