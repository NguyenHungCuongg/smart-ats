/** What /login says for the status login() returned; null on success. */
export function loginError(status: number): string | null {
  switch (status) {
    case 200:
      return null;
    case 401:
      return "Email hoặc mật khẩu không đúng.";
    case 429:
      return "Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau.";
    case 0:
      return "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
    default:
      return "Đăng nhập không thành công. Vui lòng thử lại.";
  }
}
