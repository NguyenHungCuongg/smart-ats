import { expect, test } from "vitest";

import { uploadError } from "./uploads";

test("a rejected batch names each file at fault and why", () => {
  const detail = {
    message: "Each CV must be a PDF or DOCX of at most 10 MB",
    files: [
      { file_name: "big.pdf", reason: "TOO_LARGE" },
      { file_name: "notes.txt", reason: "UNSUPPORTED_TYPE" },
    ],
  };

  expect(uploadError(413, detail)).toBe(
    "Không tải lên được: big.pdf (vượt quá 10 MB), notes.txt (không phải PDF hoặc DOCX)." +
      " Bỏ hoặc sửa các file này rồi tải lên lại.",
  );
});

test("a batch over the limits with no file named gets the limits", () => {
  const limits = "Mỗi lần tải lên tối đa 50 CV, mỗi file tối đa 10 MB.";
  // Too many files, from the API; a body Caddy cut off has no JSON detail.
  expect(uploadError(413, { message: "At most 50 CVs per upload", files: [] })).toBe(limits);
  expect(uploadError(413, undefined)).toBe(limits);
});

test("other failures fall back to a message per status", () => {
  expect(uploadError(422, [{ msg: "Field required" }])).toBe(
    "Cần xác nhận cơ sở xử lý dữ liệu và chọn ít nhất một file CV.",
  );
  expect(uploadError(500, undefined)).toBe("Không tải lên được CV. Thử lại.");
});
