// 목적: 레일과 바라보기 구역의 공개 명령 선언을 함께 유지한다.
// 실행: studio-actions가 UI·에이전트 공통 명령 목록에 삽입한다.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 구역 명령을 노출하고 250줄 래칫 준수.
// 연결: camera-look-zone-schema.js, commands/shot-rail.js.
// 이력·되돌리기: studio-actions의 railActions 참조를 기존 레일 선언으로 복원한다.
import { StudioSchemas } from './studio-agent-protocol.js';
import { lookZonesSchema } from './camera-look-zone-schema.js';
const num = { type: "number" };
const input = (required = {}, optional = {}) => ({ type: "object", properties: { ...required, ...optional }, required: Object.keys(required), additionalProperties: false });
const idSchema = StudioSchemas.TargetGuard.properties.targetId;
const shotId = { shotId: idSchema };
const floorPoint = input({ x: num, z: num });
export const railActions = [
	{ id: "shot.setCameraRail", label: "Set camera rail", kind: "mutation", undoDomain: "shot",
		input: input({ ...shotId, points: { type: "array", items: floorPoint, minItems: 2, maxItems: 512 } }, { lookZones: lookZonesSchema, height: { oneOf: [{ type: "number", minimum: 0.1, maximum: 30 }, { type: "array", items: input({ t: { type: "number", minimum: 0, maximum: 1 }, height: { type: "number", minimum: 0.1, maximum: 30 } }), minItems: 2, maxItems: 8 }] }, aim: { oneOf: [{ type: "array", items: idSchema, minItems: 1, maxItems: 4 }, input({ x: num, y: num, z: num }), { type: "null" }] }, aimHeight: { type: "number", minimum: 0, maximum: 30 }, focalMm: { oneOf: [{ type: "number", minimum: 10, maximum: 300 }, { type: "null" }] } }),
		description: "Lay a shot's dolly rail through points (world floor x/z metres, in travel order) and put the shot's camera on it, like drawing the rail in the Top-View: the camera runs the rail at an even speed over the whole shot (or its authored rail-follow range), so a push-in, pull-out, orbit, track or crane is one call with 2-6 points (a line, or an arc through a few points; the rail is a smooth curve through them). height is the lens height in metres, one number or crane marks [{ t: 0..1 along the rail, height }] (default the follow height, 1.6). aim is what the camera holds: up to 4 character or object ids (their middle, frame by frame: a character's chest, an object's middle) or a world point { x, y, z }; without an aim it follows the scene's first character. aimHeight puts a cast aim at that world height instead of the chest, e.g. 0.9 to hold a whole standing body, 1.6 for faces. focalMm is the shot's lens (default the scene lens). It replaces any rail the shot had and keeps any height, aim or lens you leave out (null clears aim and lens), and it removes the camera keys the rail covers. Answers the rail's length, speed, height, aim and lens; check the framing with verify_result { targets, checks: [\"framing\"], range: the shot's frames } and a contact sheet. lookZones temporarily pulls aim toward cast ids or a world point inside a rail range (t0/t1, 0..1) and/or a floor radius (near); feather eases the boundary, transition (seconds, default 0.8) sets how long the aim takes to swing in and out, and strength scales influence. Omit to keep zones, null clears them. Read rails with inspect_studio { scope: \"shot\" }." },
	{ id: "shot.setLookZones", label: "Set look zones", kind: "mutation", undoDomain: "shot",
		input: input({ ...shotId, lookZones: lookZonesSchema }),
		description: "Replace a shot's look zones without redrawing its rail (rail required). Up to 8 zones { id, target: { ids } or { point: { x, y, z } }, height?, range: { t0, t1 } and/or near: { x, z, radius }, feather?, strength?, transition? (seconds 0..5, default 0.8: time for the aim to swing to the target and back) }. Cast targets follow their animated chest/object centre; height overrides cast aim height. Range and near weights multiply; overlapping zones blend by weight. Default feather is 0.05 rail fraction / 0.25 m, strength 1. null or [] clears zones; outside them the default rail aim returns." },
];
