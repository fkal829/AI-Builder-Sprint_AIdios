type AuthFailure = {
  code?: string;
  status?: number;
};

const SIGNUP_ERROR_MESSAGES: Record<string, string> = {
  captcha_failed: "보안 확인에 실패했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
  email_address_invalid: "사용할 수 없는 이메일 형식입니다. 이메일 주소를 확인해 주세요.",
  email_address_not_authorized: "현재 인증 메일을 보낼 수 없는 이메일 주소입니다.",
  email_exists: "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 재설정해 주세요.",
  email_provider_disabled: "현재 이메일 회원가입을 사용할 수 없습니다.",
  identity_already_exists: "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 재설정해 주세요.",
  over_email_send_rate_limit: "확인 메일을 너무 자주 요청했습니다. 잠시 후 다시 시도해 주세요.",
  over_request_rate_limit: "회원가입을 너무 자주 시도했습니다. 잠시 후 다시 시도해 주세요.",
  signup_disabled: "현재 새 계정 가입이 중지되어 있습니다.",
  user_already_exists: "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 재설정해 주세요.",
  weak_password: "보안 기준을 충족하는 더 강한 비밀번호를 사용해 주세요.",
};

export function getSignupErrorMessage(error: AuthFailure | null): string {
  if (error?.code && SIGNUP_ERROR_MESSAGES[error.code]) {
    return SIGNUP_ERROR_MESSAGES[error.code];
  }
  if (error?.status === 429) {
    return "회원가입 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.";
  }
  if (error?.status && error.status >= 500) {
    return "인증 서비스가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요.";
  }
  return "회원가입하지 못했습니다. 이메일과 비밀번호를 확인해 주세요.";
}
