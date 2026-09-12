import type { FreeCut } from './freeCut';
type Point = [number, number];

/** RDP preserves both endpoints and all turns exceeding the screen-space tolerance. */
export function simplifyStroke(points: Point[], tolerance: number): Point[] {
  if (points.length < 3) return points.map(p => [...p]);
  const keep = new Set([0, points.length - 1]), stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop()!;
    const a = points[first], b = points[last], dx = b[0] - a[0], dy = b[1] - a[1], lengthSq = dx * dx + dy * dy;
    let largest = tolerance * tolerance, index = -1;
    for (let i = first + 1; i < last; i++) {
      const p = points[i], t = lengthSq ? Math.min(1, Math.max(0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSq)) : 0;
      const distanceSq = (p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2;
      if (distanceSq > largest) { largest = distanceSq; index = i; }
    }
    if (index >= 0) { keep.add(index); stack.push([first, index], [index, last]); }
  }
  return [...keep].sort((a, b) => a - b).map(index => [...points[index]]);
}

export function freeCutPoint(cut: FreeCut, point: Point, depth: number): [number, number, number] {
  return [0, 1, 2].map(axis => cut.origin[axis] + cut.u[axis] * point[0] + cut.v[axis] * point[1] + cut.w[axis] * depth) as [number, number, number];
}
