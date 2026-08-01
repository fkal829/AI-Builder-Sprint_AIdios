import { redirect } from "next/navigation";

/** 공개 회원가입은 열지 않는다. 운영 사용자는 사전에 등록된 이메일로 로그인한다. */
export default function SignupPage() {
  redirect("/login");
}
