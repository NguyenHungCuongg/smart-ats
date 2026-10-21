import { createTranslator } from "next-intl";
import { expect, test } from "vitest";

import type { Locale } from "../../i18n/locale";
import { CATALOGS } from "../../i18n/messages";
import { uploadError } from "./uploads";

const t = (locale: Locale) =>
  createTranslator({ locale, messages: CATALOGS[locale], namespace: "uploads" });

test("a rejected batch names each file at fault and why", () => {
  const detail = {
    message: "Each CV must be a PDF or DOCX of at most 10 MB",
    files: [
      { file_name: "big.pdf", reason: "TOO_LARGE" },
      { file_name: "notes.txt", reason: "UNSUPPORTED_TYPE" },
    ],
  };

  expect(uploadError(t("vi"), 413, detail)).toBe(
    "Không tải lên được: big.pdf (vượt quá 10 MB), notes.txt (không phải PDF hoặc DOCX)." +
      " Bỏ hoặc sửa các file này rồi tải lên lại.",
  );
  expect(uploadError(t("en"), 413, detail)).toBe(
    "Couldn't upload: big.pdf (over 10 MB), notes.txt (not a PDF or DOCX)." +
      " Remove or fix these files, then upload again.",
  );
});

test("a batch over the limits with no file named gets the limits", () => {
  const limits = "Mỗi lần tải lên tối đa 50 CV, mỗi file tối đa 10 MB.";
  // Too many files, from the API; a body Caddy cut off has no JSON detail.
  expect(uploadError(t("vi"), 413, { message: "At most 50 CVs per upload", files: [] })).toBe(
    limits,
  );
  expect(uploadError(t("vi"), 413, undefined)).toBe(limits);
  expect(uploadError(t("en"), 413, undefined)).toBe(
    "Each upload takes at most 50 CVs, of at most 10 MB each.",
  );
});

test("other failures fall back to a message per status", () => {
  expect(uploadError(t("vi"), 422, [{ msg: "Field required" }])).toBe(
    "Cần xác nhận cơ sở xử lý dữ liệu và chọn ít nhất một file CV.",
  );
  expect(uploadError(t("vi"), 500, undefined)).toBe("Không tải lên được CV. Thử lại.");
  expect(uploadError(t("en"), 500, undefined)).toBe("Couldn't upload the CVs. Try again.");
});
