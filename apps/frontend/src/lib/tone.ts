/* ===========================================================================
   톤 완충 — 거칠거나 감정적인 문장을 정중한 조정 요청문으로 다듬는다.
   MockAdapter 전용 규칙 기반 예시. live 모드는 FastAPI의 Solar 다듬기
   endpoint를 호출하며, 이 함수를 AI 성공으로 간주하지 않는다.
   =========================================================================== */
export function politen(raw: string): string {
  const core = raw
    .replace(/[ㅠㅜㅋㅎ~!]+/g, "") // 감정 꼬리표 제거
    .replace(/[.。\s]+$/g, "") // 끝 문장부호·공백 정리
    .replace(/\s+/g, " ")
    .trim();
  if (!core) return "";
  // 이미 격식 있는 요청문(기본 제안 문구 등)이면 그대로 둔다
  if (/(드립니다|바랍니다)$/.test(core)) {
    return core.endsWith(".") ? core : `${core}.`;
  }
  return `${core} 조건의 조정을 정중히 요청드립니다.`;
}
