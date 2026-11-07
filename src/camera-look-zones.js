// 목적: 레일의 구역별 겨냥과 화면 표시용 무게를 순수 계산한다.
// 실행: camera-block, camera-direction과 Node 검증 시험이 호출한다.
// 요청: 2026-11-07 원장, 협업 1107-14ed67 — 특정 구간에서 움직이는 목표를 바라보기.
// 연결: presets/SPEC_look_zones.md; 장면 camera.lookZones, 외부 설정 없음.
// 이력·되돌리기: lookZones를 지우면 기존 레일 겨냥으로 돌아간다.
const clamp = (v, min = 0, max = 1) => Math.max(min, Math.min(max, v));
const smooth = v => { const t = clamp(v); return t * t * (3 - 2 * t); };
const point3 = p => p && [p.x, p.y, p.z].every(Number.isFinite);

/** Repair stored data; scene membership is checked by the command before writing. */
export function cloneLookZones(value) {
	if (!Array.isArray(value)) return [];
	const result = [];
	for (const zone of value) {
		if (!zone || typeof zone.id !== "string" || !zone.id.trim() || result.some(z => z.id === zone.id)) continue;
		const ids = [...new Set(Array.isArray(zone.target?.ids) ? zone.target.ids.filter(id => typeof id === "string" && id.trim()) : [])].slice(0, 4);
		const target = ids.length ? { ids } : point3(zone.target?.point) ? { point: { x: zone.target.point.x, y: zone.target.point.y, z: zone.target.point.z } } : null;
		const range = zone.range && [zone.range.t0, zone.range.t1].every(Number.isFinite)
			? { t0: clamp(zone.range.t0), t1: clamp(zone.range.t1) } : null;
		const near = zone.near && [zone.near.x, zone.near.z, zone.near.radius].every(Number.isFinite) && zone.near.radius > 0
			? { x: zone.near.x, z: zone.near.z, radius: zone.near.radius } : null;
		if (!target || (zone.range && (!range || range.t0 >= range.t1)) || (zone.near && !near) || (!range && !near)) continue;
		result.push({ id: zone.id, target, ...(ids.length && Number.isFinite(zone.height) ? { height: zone.height } : {}),
			...(range ? { range } : {}), ...(near ? { near } : {}),
			...(Number.isFinite(zone.feather) ? { feather: Math.max(0, zone.feather) } : {}),
			strength: Number.isFinite(zone.strength) ? clamp(zone.strength) : 1 });
		if (result.length === 8) break;
	}
	return result;
}

function weightAt(sample, rail, zone) {
	let w = 1;
	if (zone.range) {
		const u = sample.s / rail.length, { t0, t1 } = zone.range, feather = zone.feather ?? 0.05;
		w *= u >= t0 && u <= t1 ? 1 : feather > 0
			? smooth((u - (t0 - feather)) / feather) * smooth((t1 + feather - u) / feather) : 0;
	}
	if (zone.near) {
		const d = Math.hypot(sample.pos.x - zone.near.x, sample.pos.z - zone.near.z), feather = zone.feather ?? 0.25;
		w *= d <= zone.near.radius ? 1 : feather > 0 ? smooth((zone.near.radius + feather - d) / feather) : 0;
	}
	return w * zone.strength;
}

/** Per-frame total influence, including strength, capped at 1; pass [zone] for one zone's overlay. */
export function lookZoneWeights(track, rail, zones) {
	const clean = cloneLookZones(zones);
	return track.map(sample => sample && rail?.length > 0 ? clamp(clean.reduce((sum, zone) => sum + weightAt(sample, rail, zone), 0)) : 0);
}

/** Authored plateaus for the range overlay; near-only zones have no fixed rail span. */
export function lookZoneRailSpans(zones) {
	return cloneLookZones(zones).filter(zone => zone.range).map(zone => ({ id: zone.id, ...zone.range, feather: zone.feather ?? 0.05 }));
}

/** Resolve targets every frame; missing cast silently contributes no influence. */
export function lookZoneAimOverride(track, rail, zones, targetAt) {
	const clean = cloneLookZones(zones);
	return (frame, base) => {
		const sum = { x: 0, y: 0, z: 0 };
		let total = 0;
		for (const zone of clean) {
			const w = weightAt(track[frame], rail, zone);
			if (!w) continue;
			const target = targetAt({ ...zone.target, ...(zone.height === undefined ? {} : { height: zone.height }) }, frame);
			if (!point3(target)) continue;
			total += w;
			for (const axis of ["x", "y", "z"]) sum[axis] += w * target[axis];
		}
		if (!total) return base;
		// A normalized average avoids a winner switch (and a whip-pan) where zones overlap.
		return { ...Object.fromEntries(["x", "y", "z"].map(axis => [axis, base[axis] + (sum[axis] / total - base[axis]) * Math.min(1, total)])), influence: Math.min(1, total) };
	};
}
