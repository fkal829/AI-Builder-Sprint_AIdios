export const PASSWORD_MIN_LENGTH = 8;

export function getPasswordValidationError(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상으로 만들어 주세요.`;
  }
  return null;
}
