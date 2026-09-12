import * as THREE from 'three';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FreeCut } from '../freeCut';
import { buildCutPlan, type PlannedCut } from './multiCut';

const plane = (offset: number, turn = 0): PlannedCut => ({ id: `plane-${offset}`, mode: 'PLANE', freeCut: null, offset, tilt: 0, turn });
const stroke = (y: number): FreeCut => ({
  origin: [0, 0, 0], u: [1, 0, 0], v: [0, 1, 0], w: [0, 0, 1],
  points: [[-12, y], [12, y]], depthMin: -11, depthMax: 11, kerf: .2,
});
const free = (cut: FreeCut): PlannedCut => ({ ...plane(0), mode: 'FREE', freeCut: cut });
const joint: NonNullable<FreeCut['connector']> = { enabled: true, shape: 'cylinder', diameter: 1.5, length: 2, clearance: .2, side: 1, along: .75, across: .5 };

function volume(geometry: THREE.BufferGeometry) {
  const p = geometry.getAttribute('position'), index = geometry.getIndex()!;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  let sum = 0;
  for (let i = 0; i < index.count; i += 3) {
    a.fromBufferAttribute(p, index.getX(i)); b.fromBufferAttribute(p, index.getX(i + 1)); c.fromBufferAttribute(p, index.getX(i + 2));
    sum += a.dot(b.cross(c)) / 6;
  }
  return sum;
}
function closed(geometry: THREE.BufferGeometry) {
  const index = geometry.getIndex()!, edges = new Map<string, number>();
  for (let i = 0; i < index.count; i += 3) for (let j = 0; j < 3; j++) {
    const a = index.getX(i + j), b = index.getX(i + (j + 1) % 3);
    const edge = a < b ? `${a}:${b}` : `${b}:${a}`;
    edges.set(edge, (edges.get(edge) ?? 0) + 1);
  }
  expect([...edges.values()].every(count => count === 2)).toBe(true);
  expect(volume(geometry)).toBeGreaterThan(0);
}
const cleanup = (...parts: THREE.BufferGeometry[]) => parts.forEach(part => part.dispose());
afterEach(() => vi.restoreAllMocks());

describe('sequential cut plans using the real geometry engine', () => {
  it('makes three closed pieces with two planes and preserves the source', async () => {
    expect(typeof Worker).toBe('undefined');
    const source = new THREE.BoxGeometry(20, 20, 20), before = source.getAttribute('position').array.slice();
    const progress = vi.fn(), dispose = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose');
    const outputs = await buildCutPlan(source, [plane(-3), plane(3)], progress);
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    expect(outputs.reduce((sum, part) => sum + volume(part), 0)).toBeCloseTo(8000, 3);
    expect(source.getAttribute('position').array).toEqual(before);
    expect(dispose.mock.contexts).not.toContain(source);
    expect(dispose.mock.contexts.length).toBeGreaterThan(0);
    outputs.forEach(output => expect(dispose.mock.contexts).not.toContain(output));
    expect(progress.mock.calls).toEqual([[1, 2], [2, 2]]);
    cleanup(source, ...outputs);
  });

  it('applies two free cuts while carrying the non-intersecting piece forward', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const outputs = await buildCutPlan(source, [free(stroke(-3)), free(stroke(3))]);
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    expect(outputs.reduce((sum, part) => sum + volume(part), 0)).toBeCloseTo(7840, 2);
    cleanup(source, ...outputs);
  });

  it('preserves a component that the finite blade only grooves when another component separates', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const outputs = await buildCutPlan(source, [plane(0), free({ ...stroke(0), depthMin: -1 })]);
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    const lower = outputs.find(part => part.boundingBox!.max.z < .001)!;
    expect(lower).toBeDefined(); expect(volume(lower)).toBeCloseTo(4000, 3);
    cleanup(source, ...outputs);
  });

  it('reports the numbered cut that misses every component and releases intermediates', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20), dispose = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose');
    await expect(buildCutPlan(source, [plane(0), plane(30)])).rejects.toMatchObject({ code: 'plane-miss', message: expect.stringContaining('Corte 2:') });
    expect(dispose.mock.contexts).toHaveLength(3);
    expect(new Set(dispose.mock.contexts).size).toBe(3);
    expect(dispose.mock.contexts).not.toContain(source);
    cleanup(source);
  });

  it('does not swallow invalid cuts after an earlier successful cut', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    await expect(buildCutPlan(source, [plane(0), free({ ...stroke(0), kerf: 0 })])).rejects.toMatchObject({ code: 'invalid-free-cut', message: expect.stringContaining('Corte 2:') });
    await expect(buildCutPlan(source, [plane(NaN)])).rejects.toMatchObject({ code: 'invalid-plane' });
    cleanup(source);
  });

  it('does not hide invalid source geometry behind a non-intersecting cut', async () => {
    const source = new THREE.BufferGeometry();
    source.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
    await expect(buildCutPlan(source, [plane(30)])).rejects.toMatchObject({ code: 'non-manifold', message: expect.stringContaining('Corte 1:') });
    cleanup(source);
  });

  it('applies a connector only to its containing piece when a stroke cuts both prior pieces', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const outputs = await buildCutPlan(source, [plane(0, 90), free({ ...stroke(0), connector: joint })]);
    expect(outputs).toHaveLength(4); outputs.forEach(closed);
    const untouched = outputs.filter(part => part.boundingBox!.max.x < .001);
    const joined = outputs.filter(part => part.boundingBox!.min.x > -.001);
    expect(untouched).toHaveLength(2); untouched.forEach(part => expect(volume(part)).toBeCloseTo(1980, 2));
    expect(joined).toHaveLength(2);
    expect(Math.max(...joined.map(volume))).toBeGreaterThan(1980);
    expect(Math.min(...joined.map(volume))).toBeLessThan(1980);
    cleanup(source, ...outputs);
  });

  it('preserves an existing pin and socket through a later non-overlapping cut', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const first = free({ ...stroke(0), connector: joint });
    const baseline = await buildCutPlan(source, [first]);
    const outputs = await buildCutPlan(source, [first, free(stroke(6))]);
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    expect(baseline.reduce((sum, part) => sum + volume(part), 0) - outputs.reduce((sum, part) => sum + volume(part), 0)).toBeCloseTo(80, 2);
    cleanup(source, ...baseline, ...outputs);
  });

  it('builds two separate free cuts when each one has its own fitting connector', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const outputs = await buildCutPlan(source, [free({ ...stroke(-3), connector: joint }), free({ ...stroke(3), connector: { ...joint, along: .25 } })]);
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    cleanup(source, ...outputs);
  });

  it('rejects a connector that does not fit instead of silently dropping it', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    await expect(buildCutPlan(source, [plane(0, 90), free({ ...stroke(0), connector: { ...joint, diameter: 30 } })])).rejects.toMatchObject({ code: 'invalid-free-cut', message: expect.stringMatching(/Corte 2:.*encaixe/) });
    cleanup(source);
  });
});
