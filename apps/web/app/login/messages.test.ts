import { expect, test } from "vitest";

import { loginError } from "./messages";

test("each failure has its own message; only 401 means a wrong password", () => {
  expect(loginError(200)).toBeNull();
  expect(loginError(401)).toBe("Email hoặc mật khẩu không đúng.");
  expect(loginError(429)).toBe("Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau.");
  expect(loginError(0)).toBe("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
  expect(loginError(500)).toBe("Đăng nhập không thành công. Vui lòng thử lại.");
});
