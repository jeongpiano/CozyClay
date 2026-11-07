// 목적: 두 레일 명령이 같은 바라보기 구역 입력 규격을 제공한다.
// 실행: studio-actions가 명령을 등록하고 에이전트에게 스키마를 노출한다.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 레일을 다시 그리지 않고 구역 편집.
// 연결: camera-look-zones.js 정규화; SPEC_look_zones.md.
// 이력·되돌리기: 명령 선언의 lookZones 참조를 제거하면 비활성화된다.
const number = { type: "number" };
const object = properties => ({ type: "object", properties, required: Object.keys(properties), additionalProperties: false });
const point = object({ x: number, y: number, z: number });
const zone = {
	type: "object", additionalProperties: false, required: ["id", "target"],
	properties: {
		id: { type: "string", minLength: 1, maxLength: 64 },
		target: { oneOf: [object({ ids: { type: "array", minItems: 1, maxItems: 4, items: { type: "string", minLength: 1 } } }), object({ point })] },
		height: number,
		range: object({ t0: { ...number, minimum: 0, maximum: 1 }, t1: { ...number, minimum: 0, maximum: 1 } }),
		near: object({ x: number, z: number, radius: number }),
		feather: { ...number, minimum: 0 },
		strength: { ...number, minimum: 0, maximum: 1 },
		transition: { ...number, minimum: 0, maximum: 5 },
	},
};
export const lookZonesSchema = { oneOf: [{ type: "array", maxItems: 8, items: zone }, { type: "null" }] };
