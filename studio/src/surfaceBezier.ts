import * as THREE from 'three';
import type { FreeCut, Vec3 } from './freeCut';
import type { SurfaceProjector } from './surfaceAnchors';

export type Side = 'front' | 'back';
type Handles = { in: Vec3; out: Vec3 };
/** Indices identify original controls, never tessellation samples. No insertion/deletion. */
export interface SurfaceBezier {
  version: 1;
  anchors: { front: Vec3[]; back: Vec3[] };
  handles: Partial<Record<Side, Record<number, Handles>>>;
  segments: { front: Vec3[][]; back: Vec3[][] };
}
const vector = (p: Vec3) => new THREE.Vector3(...p);
export const editableRails = (cut: FreeCut) => cut.bezier?.anchors ?? cut.rails;
export const bezierHandles = (cut: FreeCut, side: Side, index: number) => cut.bezier?.handles[side]?.[index];
function model(cut: FreeCut): SurfaceBezier {
  if (cut.bezier) return cut.bezier;
  const anchors = cut.rails!;
  return { version: 1, anchors, handles: {}, segments: {
    front: anchors.front.slice(0, -1).map(p => [p]),
    back: anchors.back.slice(0, -1).map(p => [p]),
  } };
}

/** Only touched intervals are evaluated. Uncurved intervals keep the original straight edge. */
function rebuild(projector: SurfaceProjector, cut: FreeCut, draft: SurfaceBezier, index: number): FreeCut {
  const segments = { front: draft.segments.front.slice(), back: draft.segments.back.slice() };
  for (const i of [index - 1, index]) {
    if (i < 0 || i >= draft.anchors.front.length - 1) continue;
    const steps = (['front', 'back'] as const).some(side => draft.handles[side]?.[i] || draft.handles[side]?.[i + 1]) ? 8 : 1;
    for (const side of ['front', 'back'] as const) {
      const a = vector(draft.anchors[side][i]), d = vector(draft.anchors[side][i + 1]);
      const left = draft.handles[side]?.[i], right = draft.handles[side]?.[i + 1];
      const b = left ? vector(left.out) : a.clone().lerp(d, 1 / 3);
      const c = right ? vector(right.in) : a.clone().lerp(d, 2 / 3);
      const chord = d.clone().sub(a), length = chord.length();
      if (length < projector.size * 1e-8) return cut;
      // Handles must advance through their own interval; disallow loops locally.
      const progress = (p: THREE.Vector3) => p.clone().sub(a).dot(chord) / (length * length);
      if (progress(b) < -1e-6 || progress(c) > 1 + 1e-6 || progress(b) > progress(c) + 1e-6) return cut;
      const samples: Vec3[] = [draft.anchors[side][i]];
      let previous = 0;
      for (let j = 1; j < steps; j++) {
        const t = j / steps, s = 1 - t;
        const desired = a.clone().multiplyScalar(s*s*s).addScaledVector(b, 3*s*s*t).addScaledVector(c, 3*s*t*t).addScaledVector(d, t*t*t);
        // Straight opposite edges are subdivided exactly, never reprojected.
        const point = left || right ? projector.nearest(desired) : desired;
        if (!point || point.distanceTo(desired) > length * .25) return cut;
        const advance = progress(point);
        if (advance <= previous + 1e-7 || advance >= 1 - 1e-7) return cut;
        previous = advance;
        samples.push(point.toArray() as Vec3);
      }
      segments[side][i] = samples;
    }
  }
  const rails = {
    front: [...segments.front.flat(), draft.anchors.front.at(-1)!],
    back: [...segments.back.flat(), draft.anchors.back.at(-1)!],
  };
  if (rails.front.length > 2048) return cut;
  return { ...cut, bezier: { ...draft, segments }, rails };
}

export function toggleBezier(projector: SurfaceProjector, cut: FreeCut, side: Side, index: number): FreeCut {
  if (!cut.rails) return cut;
  const current = model(cut), handles = { ...current.handles[side] }, rail = current.anchors[side];
  if (!rail[index]) return cut;
  if (handles[index]) delete handles[index];
  else {
    const anchor = vector(rail[index]);
    // Initial handles follow each adjacent edge, so enabling a curve does not smooth other anchors.
    handles[index] = {
      in: anchor.clone().lerp(vector(rail[Math.max(0, index - 1)]), 1 / 3).toArray() as Vec3,
      out: anchor.clone().lerp(vector(rail[Math.min(rail.length - 1, index + 1)]), 1 / 3).toArray() as Vec3,
    };
  }
  return rebuild(projector, cut, { ...current, handles: { ...current.handles, [side]: handles } }, index);
}

/** The target comes from the mesh for anchors, a fixed pointer-down plane for handles. */
export function moveBezier(projector: SurfaceProjector, cut: FreeCut, side: Side, index: number, kind: 'anchor' | 'in' | 'out', target: THREE.Vector3): FreeCut {
  if (!cut.rails || !target.toArray().every(Number.isFinite)) return cut;
  const current = model(cut), rail = current.anchors[side];
  if (!rail[index]) return cut;
  const handles = { ...current.handles[side] }, anchors = { ...current.anchors };
  if (kind === 'anchor') {
    const delta = target.clone().sub(vector(rail[index]));
    anchors[side] = rail.slice(); anchors[side][index] = target.toArray() as Vec3;
    if (handles[index]) handles[index] = {
      in: vector(handles[index].in).add(delta).toArray() as Vec3,
      out: vector(handles[index].out).add(delta).toArray() as Vec3,
    };
  } else {
    if (!handles[index]) return cut;
    // Independent handles give explicit corner/tangent control, without moving the other interval.
    handles[index] = { ...handles[index], [kind]: target.toArray() as Vec3 };
  }
  return rebuild(projector, cut, { ...current, anchors, handles: { ...current.handles, [side]: handles } }, index);
}
