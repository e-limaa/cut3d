import * as THREE from 'three';
import { MeshBVH } from 'three-mesh-bvh';
import type { FreeCut, Vec3 } from './freeCut';
import { freeCutPoint, simplifyStroke } from './strokeMath';

export class SurfaceProjector {
  readonly bvh: MeshBVH;
  readonly size: number;
  private geometry: THREE.BufferGeometry;
  constructor(source: THREE.BufferGeometry) {
    // BVH may add an index; use a shallow attribute view so the original is never changed.
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute('position', source.getAttribute('position'));
    if (source.index) this.geometry.setIndex(source.index);
    this.geometry.computeBoundingBox();
    this.size = this.geometry.boundingBox!.getSize(new THREE.Vector3()).length();
    // This installed release supports indirect mode but omits it from its legacy typings.
    const options = { indirect: true, maxLeafTris: 10 };
    this.bvh = new MeshBVH(this.geometry, options);
  }
  dispose() { this.geometry.dispose(); }
  nearest(point: THREE.Vector3): THREE.Vector3 | null {
    return this.bvh.closestPointToPoint(point)?.point.clone() ?? null;
  }
  hit(ray: THREE.Ray): THREE.Vector3 | null {
    return this.bvh.raycastFirst(ray, THREE.DoubleSide)?.point.clone() ?? null;
  }
  /** Entry/exit of the first visible shell along the original drawing direction. */
  pair(cut: FreeCut, point: [number, number], reference?: THREE.Vector3): { front: Vec3; back: Vec3 } | null {
    const w = new THREE.Vector3(...cut.w);
    const origin = new THREE.Vector3(...freeCutPoint(cut, point, this.size * 2));
    const hits = this.bvh.raycast(new THREE.Ray(origin, w.negate()), THREE.DoubleSide).sort((a, b) => a.distance - b.distance);
    const unique = hits.filter((hit, i) => i === 0 || hit.distance - hits[i - 1].distance > this.size * 1e-7);
    if (unique.length < 2) return null;
    let selected = 0;
    if (reference) {
      let distance = Infinity;
      for (let i = 0; i + 1 < unique.length; i += 2) {
        const candidate = Math.min(unique[i].point.distanceToSquared(reference), unique[i + 1].point.distanceToSquared(reference));
        if (candidate < distance) { distance = candidate; selected = i; }
      }
    }
    return { front: unique[selected].point.toArray() as Vec3, back: unique[selected + 1].point.toArray() as Vec3 };
  }

  isVisible(point: THREE.Vector3, cameraPosition: THREE.Vector3): boolean {
    const direction = point.clone().sub(cameraPosition);
    const distance = direction.length();
    const hit = this.hit(new THREE.Ray(cameraPosition, direction.normalize()));
    return !hit || cameraPosition.distanceTo(hit) >= distance - this.size * 1e-5;
  }
}

function between(a: [number, number], b: [number, number], t: number): [number, number] { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }
/** Build paired rails from the actual intersections of the drawn path and mesh. */
export function attachStrokeToSurface(projector: SurfaceProjector, cut: FreeCut): FreeCut {
  if (cut.points.length < 2) throw new Error('Desenhe um traço atravessando a superfície do modelo.');
  // Densify before looking for intersections, including a perfectly straight gesture.
  const path: [number, number][] = [];
  for (let i = 1; i < cut.points.length; i++) {
    const a = cut.points[i - 1], b = cut.points[i];
    const steps = Math.max(1, Math.min(320, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (projector.size / 160))));
    for (let j = 0; j < steps; j++) path.push(between(a, b, j / steps));
  }
  path.push(cut.points.at(-1)!);
  const pairs = path.map(p => projector.pair(cut, p));
  // A stroke crossing several silhouettes targets the longest continuous visible span.
  let first = -1, last = -1, start = -1;
  for (let i = 0; i <= pairs.length; i++) {
    if (i < pairs.length && pairs[i]) { if (start < 0) start = i; }
    else if (start >= 0) { if (first < 0 || i - start > last - first + 1) { first = start; last = i - 1; } start = -1; }
  }
  if (first < 0 || last <= first) throw new Error('Não encontrei uma região fechada sob o traço. Desenhe atravessando a malha.');
  const boundary = (inside: [number, number], outside: [number, number]) => {
    let hit = inside, miss = outside;
    for (let i = 0; i < 12; i++) { const mid = between(hit, miss, .5); if (projector.pair(cut, mid)) hit = mid; else miss = mid; }
    return hit;
  };
  const trimmed = path.slice(first, last + 1);
  if (first > 0) trimmed[0] = boundary(path[first], path[first - 1]);
  if (last < path.length - 1) trimmed[trimmed.length - 1] = boundary(path[last], path[last + 1]);
  // Preserve small bends before resampling. These points become the real
  // surface anchors and determine the printed edge, not only the preview.
  const simplified = simplifyStroke(trimmed, projector.size * .0005);
  const length = simplified.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - simplified[i][0], p[1] - simplified[i][1]), 0);
  const controls: [number, number][] = [];
  for (let i = 1; i < simplified.length; i++) {
    const a = simplified[i - 1], b = simplified[i];
    const steps = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / Math.max(length / 36, projector.size * .001)));
    for (let j = 0; j < steps; j++) controls.push(between(a, b, j / steps));
  }
  controls.push(simplified.at(-1)!);
  const front: Vec3[] = [], back: Vec3[] = [];
  for (const point of controls) {
    const pair = projector.pair(cut, point);
    if (pair) { front.push(pair.front); back.push(pair.back); }
    else {
      // Near silhouette concavities, closest points remain ON the real surface.
      const nearestIndex = path.reduce((best, p, i) => pairs[i] && Math.hypot(p[0] - point[0], p[1] - point[1]) < Math.hypot(path[best][0] - point[0], path[best][1] - point[1]) ? i : best, first);
      const reference = pairs[nearestIndex]!;
      for (const side of ['front', 'back'] as const) {
        const referenceDepth = new THREE.Vector3(...reference[side]).sub(new THREE.Vector3(...cut.origin)).dot(new THREE.Vector3(...cut.w));
        const snapped = projector.nearest(new THREE.Vector3(...freeCutPoint(cut, point, referenceDepth)));
        if (!snapped) throw new Error('Não foi possível apoiar todos os controles na malha.');
        (side === 'front' ? front : back).push(snapped.toArray() as Vec3);
      }
    }
  }
  const depths = [...front, ...back].map(p => new THREE.Vector3(...p).sub(new THREE.Vector3(...cut.origin)).dot(new THREE.Vector3(...cut.w)));
  return { ...cut, points: controls, rails: { front, back }, depthMin: Math.min(...depths), depthMax: Math.max(...depths) };
}

export function dragSurfacePoint(projector: SurfaceProjector, cut: FreeCut, side: 'front' | 'back', index: number, ray: THREE.Ray): FreeCut {
  if (!cut.rails) return cut;
  const point = projector.hit(ray);
  if (!point) return cut; // Missing the mesh never releases a point into empty space.
  const rail = cut.rails[side].map(p => [...p] as Vec3);
  rail[index] = point.toArray() as Vec3;
  return { ...cut, rails: { ...cut.rails, [side]: rail } };
}

export function penAnchorIndices(length: number, maximum = 10): number[] {
  if (length <= maximum) return Array.from({ length }, (_, index) => index);
  return Array.from({ length: maximum }, (_, index) => Math.round(index * (length - 1) / (maximum - 1)));
}

function cubic(a: [number, number], b: [number, number], c: [number, number], d: [number, number], t: number): [number, number] {
  const s = 1 - t;
  return [s*s*s*a[0] + 3*s*s*t*b[0] + 3*s*t*t*c[0] + t*t*t*d[0], s*s*s*a[1] + 3*s*s*t*b[1] + 3*s*t*t*c[1] + t*t*t*d[1]];
}

/** Rebuild only spans touching affected controls; omit them for an explicit full rebuild. */
export function rebuildPenRails(projector: SurfaceProjector, cut: FreeCut, affectedIndices?: readonly number[]): FreeCut {
  if (!cut.rails) return cut;
  const anchors = penAnchorIndices(cut.points.length);
  const affected = affectedIndices ? new Set(affectedIndices) : null;
  const points = cut.points.slice();
  const changed = new Set<number>();
  for (const index of anchors) if (!affected || affected.has(index)) changed.add(index);
  for (let segment = 1; segment < anchors.length; segment++) {
    const from = anchors[segment - 1], to = anchors[segment];
    if (affected && !affected.has(from) && !affected.has(to)) continue;
    const a = points[from], d = points[to];
    const b = cut.penCurves?.[from]?.out ?? a;
    const c = cut.penCurves?.[to]?.in ?? d;
    const curved = !!(cut.penCurves?.[from]?.out || cut.penCurves?.[to]?.in);
    for (let index = from + 1; index < to; index++) {
      const t = (index - from) / (to - from);
      points[index] = curved ? cubic(a, b, c, d, t) : between(a, d, t);
      changed.add(index);
    }
  }
  if (!changed.size) return cut;
  const front = cut.rails.front.slice();
  const back = cut.rails.back.slice();
  const framed = { ...cut, points };
  for (const index of changed) {
    const pair = projector.pair(framed, points[index], new THREE.Vector3(...cut.rails.front[index]));
    if (!pair) return cut;
    front[index] = pair.front; back[index] = pair.back;
  }
  const depths = [...front, ...back].map(point => new THREE.Vector3(...point).sub(new THREE.Vector3(...cut.origin)).dot(new THREE.Vector3(...cut.w)));
  return { ...cut, points, rails: { front, back }, depthMin: Math.min(...depths), depthMax: Math.max(...depths) };
}

/** Move one unified Pen control. Pass the immutable pointer-down cut for every drag update. */
export function dragPenControl(projector: SurfaceProjector, cut: FreeCut, index: number, kind: 'anchor' | 'in' | 'out', ray: THREE.Ray, surfaceSide?: 'front' | 'back'): FreeCut {
  if (!cut.rails || !penAnchorIndices(cut.points.length).includes(index)) return cut;
  const hit = projector.hit(ray);
  if (!hit) return cut;
  if (kind === 'anchor' && surfaceSide) {
    // A single editor does not mean that a front control should move the back.
    // Keep the actual 3D hit, including its depth, and deform only this rail.
    const anchors = penAnchorIndices(cut.points.length);
    const slot = anchors.indexOf(index);
    const from = anchors[Math.max(0, slot - 1)], to = anchors[Math.min(anchors.length - 1, slot + 1)];
    const endpoint = index === 0 || index === cut.points.length - 1;
    const sides: ('front'|'back')[] = endpoint ? ['front','back'] : [surfaceSide];
    const rails = { ...cut.rails };
    for (const side of sides) {
      const original = cut.rails[side];
      const rail = original.slice();
      const delta = hit.clone().sub(new THREE.Vector3(...original[index]));
      for (let i = from; i <= to; i++) {
        if (i === index) { rail[i] = hit.toArray() as Vec3; continue; }
        const weight = i < index ? (i-from)/(index-from) : (to-i)/(to-index);
        if (weight <= 0) continue;
        const desired = new THREE.Vector3(...original[i]).addScaledVector(delta, weight);
        const snapped = projector.nearest(desired);
        if (!snapped) return cut;
        rail[i] = snapped.toArray() as Vec3;
      }
      rails[side] = rail;
    }
    return { ...cut, rails };
  }
  const relative = hit.clone().sub(new THREE.Vector3(...cut.origin));
  const target: [number, number] = [relative.dot(new THREE.Vector3(...cut.u)), relative.dot(new THREE.Vector3(...cut.v))];
  const points = cut.points.slice();
  const penCurves = { ...(cut.penCurves ?? {}) };
  if (kind === 'anchor') {
    const previous = points[index];
    points[index] = target;
    const curve = penCurves[index];
    if (curve) {
      const delta: [number, number] = [target[0] - previous[0], target[1] - previous[1]];
      penCurves[index] = { in: [curve.in[0] + delta[0], curve.in[1] + delta[1]], out: [curve.out[0] + delta[0], curve.out[1] + delta[1]] };
    }
  } else {
    const anchor = points[index];
    const opposite: [number, number] = [anchor[0] * 2 - target[0], anchor[1] * 2 - target[1]];
    penCurves[index] = kind === 'in' ? { in: target, out: opposite } : { in: opposite, out: target };
  }
  const rails = { front: cut.rails.front.slice(), back: cut.rails.back.slice() };
  if (kind === 'anchor') {
    const pair = projector.pair(cut, target, hit);
    if (!pair) return cut;
    rails.front[index] = pair.front; rails.back[index] = pair.back;
  }
  const draft = { ...cut, points, penCurves, rails };
  const rebuilt = rebuildPenRails(projector, draft, [index]);
  return rebuilt === draft ? cut : rebuilt;
}
