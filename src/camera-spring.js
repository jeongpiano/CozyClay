// 목적: 기존 레일/팔로우의 결정적 스프링 계산을 공유한다.
// 실행: camera-follow가 프레임별 고정 간격으로 호출한다.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 구역 겨냥 확장 시 파일 크기 래칫 준수.
// 연결: src/camera-follow.js; 설정·외부 데이터 없음.
// 이력·되돌리기: 수식은 기존 함수 그대로이며 호출부로 인라인 가능.
/** critically damped response: reaches ~98% of a step in `response` seconds */
export function omegaFor(response) {
	return 4.6 / Math.max(response, 0.05);
}

/** one semi-implicit Euler step of a critically damped spring (scalar) */
export function springStep(pos, vel, target, omega, dt) {
	const acc = omega * omega * (target - pos) - 2 * omega * vel;
	const nextVel = vel + acc * dt;
	return [pos + nextVel * dt, nextVel];
}

/** scalar forward spring whose speed limit is applied before position integration */
export function cappedSpringStep(pos, vel, target, omega, dt, maxSpeed) {
	const acc = omega * omega * (target - pos) - 2 * omega * vel;
	const cap = Math.max(0, Number.isFinite(maxSpeed) ? maxSpeed : 0);
	// Rail targets never move backward; incompatible velocity would reverse the dolly.
	const nextVel = Math.max(0, Math.min(vel + acc * dt, cap));
	return [pos + nextVel * dt, nextVel];
}
