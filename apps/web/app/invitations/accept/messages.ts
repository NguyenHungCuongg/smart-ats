/** What the accept page says for the status acceptInvitation() returned; null on success. */
export function acceptError(status: number): string | null {
  switch (status) {
    case 200:
      return null;
    case 400:
      return "Lời mời không hợp lệ hoặc đã hết hạn. Hãy nhờ Company Admin mời lại.";
    case 422:
      return "Kiểm tra lại họ tên và mật khẩu.";
    case 0:
      return "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
    default:
      return "Không tạo được tài khoản. Vui lòng thử lại.";
  }
}
