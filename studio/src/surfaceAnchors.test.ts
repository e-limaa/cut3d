import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import type { FreeCut } from './freeCut';
import { SurfaceProjector, attachStrokeToSurface, dragPenControl, dragSurfacePoint, penAnchorIndices, rebuildPenRails, surfaceCurve } from './surfaceAnchors';

const stroke: FreeCut = { origin: [0, 0, 0], u: [1, 0, 0], v: [0, 0, 1], w: [0, -1, 0], points: [[-14, 1], [-5, 3], [0, 1], [5, 3], [14, 1]], depthMin: -10, depthMax: 10, kerf: .2 };
describe('surface anchored editing', () => {
  it('moves 3D Bezier handles with the anchor and edits a tangent without rebuilding the opposite surface', () => {
    const geometry=new THREE.SphereGeometry(10,48,32), projector=new SurfaceProjector(geometry);
    const original=attachStrokeToSurface(projector,stroke);
    const anchors=penAnchorIndices(original.points.length), index=anchors[4];
    const cut:FreeCut={...original,penCurves:{[index]:{in:[-2,1],out:[2,1]}}};
    const handles=surfaceCurve(cut,'front',index)!;
    const ray=new THREE.Ray(new THREE.Vector3(1,-30,3),new THREE.Vector3(0,1,0));
    const moved=dragPenControl(projector,cut,index,'anchor',ray,'front');
    const delta=projector.hit(ray)!.sub(new THREE.Vector3(...cut.rails!.front[index]));
    for (const kind of ['in','out'] as const) {
      expect(surfaceCurve(moved,'front',index)![kind]).toEqual(new THREE.Vector3(...handles[kind]).add(delta).toArray());
    }
    const out=surfaceCurve(moved,'front',index)!.out;
    const tangent=dragPenControl(projector,moved,index,'out',new THREE.Ray(new THREE.Vector3(out[0]+.4,-30,out[2]+.3),new THREE.Vector3(0,1,0)),'front');
    expect(tangent.rails!.back).toBe(cut.rails!.back);
    expect(tangent.rails!.front[index]).toBe(moved.rails!.front[index]);
    expect(surfaceCurve(tangent,'front',index)!.out[0]).toBeCloseTo(out[0]+.4);
    for(let i=0;i<cut.points.length;i++) if(i<=anchors[3] || i>=anchors[5]) expect(tangent.rails!.front[i]).toBe(cut.rails!.front[i]);
    projector.dispose();geometry.dispose();
  });
  it.each([0, -1])('drags a shared endpoint without pulling its two rails apart (%s)', endpoint => {
    const geometry = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(geometry);
    const cut = attachStrokeToSurface(projector, stroke);
    const index = endpoint === 0 ? 0 : cut.points.length - 1;
    const ray = new THREE.Ray(new THREE.Vector3(endpoint === 0 ? -8 : 8, -30, 2), new THREE.Vector3(0, 1, 0));
    const next = dragPenControl(projector, cut, index, 'anchor', ray, 'front');
    expect(next.rails!.front[index]).toEqual(projector.hit(ray)!.toArray());
    expect(next.rails!.back[index]).toEqual(next.rails!.front[index]);
    const middle = Math.floor(cut.points.length/2);
    expect(next.rails!.front[middle]).toBe(cut.rails!.front[middle]);
    expect(next.rails!.back[middle]).toBe(cut.rails!.back[middle]);
    projector.dispose(); geometry.dispose();
  });
  it('UI anchor dragging preserves the opposite surface and distant samples exactly', () => {
    const geometry = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(geometry);
    const cut = attachStrokeToSurface(projector, stroke);
    const anchors = penAnchorIndices(cut.points.length), index = anchors[4];
    const ray = new THREE.Ray(new THREE.Vector3(1, 30, 4), new THREE.Vector3(0, -1, 0));
    const updated = dragPenControl(projector, cut, index, 'anchor', ray, 'back');
    expect(updated.rails!.front).toBe(cut.rails!.front);
    expect(updated.points).not.toBe(cut.points);
    expect(updated.rails!.back[index]).toEqual(projector.hit(ray)!.toArray());
    for (let i=0;i<cut.points.length;i++) {
      if (i <= anchors[3] || i >= anchors[5]) expect(updated.rails!.back[i]).toBe(cut.rails!.back[i]);
    }
    projector.dispose(); geometry.dispose();
  });
  function sampledCut(projector: SurfaceProjector): FreeCut {
    const points: [number, number][] = Array.from({ length: 55 }, (_, i) => [-8 + 16 * i / 54, 1.2 + Math.sin(i * .8)]);
    const pairs = points.map(point => projector.pair(stroke, point)!);
    return { ...stroke, points, rails: { front: pairs.map(pair => pair.front), back: pairs.map(pair => pair.back) } };
  }
  it.each([0, 4, 9])('preserves all remote samples and rails when moving control %i', (control) => {
    const model = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(model);
    const cut = sampledCut(projector), original = structuredClone(cut);
    const anchors = penAnchorIndices(cut.points.length), index = anchors[control];
    const pairSpy = vi.spyOn(projector, 'pair');
    const updated = dragPenControl(projector, cut, index, 'anchor', new THREE.Ray(new THREE.Vector3(cut.points[index][0], -30, 2), new THREE.Vector3(0, 1, 0)));
    expect(updated).not.toBe(cut);
    expect(updated.points).toHaveLength(cut.points.length);
    const from = anchors[Math.max(0, control - 1)], to = anchors[Math.min(anchors.length - 1, control + 1)];
    for (let i = 0; i < cut.points.length; i++) {
      if (i !== index && (i <= from || i >= to)) {
        expect(updated.points[i]).toBe(cut.points[i]);
        expect(updated.rails!.front[i]).toBe(cut.rails!.front[i]);
        expect(updated.rails!.back[i]).toBe(cut.rails!.back[i]);
      }
      for (const point of [updated.rails!.front[i], updated.rails!.back[i]]) {
        expect(projector.nearest(new THREE.Vector3(...point))!.distanceTo(new THREE.Vector3(...point))).toBeLessThan(1e-6);
      }
    }
    expect(pairSpy.mock.calls.length).toBeLessThanOrEqual(to - from + 1);
    expect(cut).toEqual(original);
    projector.dispose(); model.dispose();
  });
  it('spaces straight span samples linearly instead of easing toward anchors', () => {
    const model = new THREE.BoxGeometry(20, 20, 20), projector = new SurfaceProjector(model);
    const cut = sampledCut(projector), anchors = penAnchorIndices(cut.points.length), index = anchors[4];
    const updated = dragPenControl(projector, cut, index, 'anchor', new THREE.Ray(new THREE.Vector3(0, -30, 2), new THREE.Vector3(0, 1, 0)));
    for (const [from, to] of [[anchors[3], index], [index, anchors[5]]]) {
      for (let i = from + 1; i < to; i++) {
        const t = (i - from) / (to - from);
        for (const axis of [0, 1]) expect(updated.points[i][axis]).toBeCloseTo(updated.points[from][axis] * (1 - t) + updated.points[to][axis] * t, 12);
      }
    }
    projector.dispose(); model.dispose();
  });
  it('rebuilds explicit curves locally and evaluates their cubic samples', () => {
    const model = new THREE.BoxGeometry(20, 20, 20), projector = new SurfaceProjector(model);
    const base = sampledCut(projector), anchors = penAnchorIndices(base.points.length), index = anchors[4], to = anchors[5];
    const cut: FreeCut = { ...base, penCurves: { [index]: { in: [base.points[index][0] - 1, -2], out: [base.points[index][0] + 1, 2] } } };
    const updated = rebuildPenRails(projector, cut, [index]);
    const t = 1 / (to - index), s = 1 - t;
    for (const axis of [0, 1]) expect(updated.points[index + 1][axis]).toBeCloseTo(s ** 3 * cut.points[index][axis] + 3 * s ** 2 * t * cut.penCurves![index].out[axis] + (3 * s * t ** 2 + t ** 3) * cut.points[to][axis], 12);
    expect(updated.points[anchors[2] + 1]).toBe(cut.points[anchors[2] + 1]);
    expect(updated.rails!.front[to]).toBe(cut.rails!.front[to]);
    projector.dispose(); model.dispose();
  });
  it('rejects a failed local projection atomically and keeps the baseline reusable', () => {
    const model = new THREE.BoxGeometry(20, 20, 20), projector = new SurfaceProjector(model);
    const cut = sampledCut(projector), original = structuredClone(cut), index = penAnchorIndices(cut.points.length)[4];
    const ray = new THREE.Ray(new THREE.Vector3(0, -30, 2), new THREE.Vector3(0, 1, 0));
    const first = dragPenControl(projector, cut, index, 'anchor', ray);
    dragPenControl(projector, cut, index, 'anchor', new THREE.Ray(new THREE.Vector3(1, -30, 4), new THREE.Vector3(0, 1, 0)));
    expect(dragPenControl(projector, cut, index, 'anchor', ray)).toEqual(first);
    vi.spyOn(projector, 'pair').mockReturnValueOnce({ front: [0, -10, 2], back: [0, 10, 2] }).mockReturnValueOnce(null);
    expect(dragPenControl(projector, cut, index, 'anchor', ray)).toBe(cut);
    expect(cut).toEqual(original);
    projector.dispose(); model.dispose();
  });
  it('keeps the selected shell when another solid lies in front of the drawing direction', () => {
    const first = new THREE.BoxGeometry(20, 4, 20).translate(0, -12, 0);
    const second = new THREE.BoxGeometry(20, 4, 20).translate(0, 12, 0);
    const geometry = mergeGeometries([first, second]);
    const projector = new SurfaceProjector(geometry);
    const pair = projector.pair(stroke, [0, 1], new THREE.Vector3(0, 14, 1))!;
    expect(pair.front[1]).toBeCloseTo(10);
    expect(pair.back[1]).toBeCloseTo(14);
    projector.dispose(); geometry.dispose(); first.dispose(); second.dispose();
  });
  it('checks visibility along the anchor center and rejects hidden rear anchors', () => {
    const geometry = new THREE.BoxGeometry(20, 20, 20), projector = new SurfaceProjector(geometry);
    const camera = new THREE.Vector3(0, -30, 0);
    expect(projector.isVisible(new THREE.Vector3(9.999, -10, 0), camera)).toBe(true);
    expect(projector.isVisible(new THREE.Vector3(0, 10, 0), camera)).toBe(false);
    projector.dispose(); geometry.dispose();
  });
  it('places all front and rear controls on the loaded mesh, including silhouette ends', () => {
    const model = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(model);
    const cut = attachStrokeToSurface(projector, stroke);
    expect(cut.rails!.front.length).toBeGreaterThan(24);
    expect(cut.rails!.front.length).toBe(cut.rails!.back.length);
    for (const p of [...cut.rails!.front, ...cut.rails!.back]) {
      const point = new THREE.Vector3(...p);
      expect(projector.nearest(point)!.distanceTo(point)).toBeLessThan(1e-6);
    }
    expect(cut.rails!.front.every(p => p[1] < .001)).toBe(true);
    expect(cut.rails!.back.every(p => p[1] > -.001)).toBe(true);
    projector.dispose(); model.dispose();
  });
  it('moves a rear point along the visible shell without changing the front rail', () => {
    const model = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(model);
    const cut = attachStrokeToSurface(projector, stroke), original = structuredClone(cut);
    const index = Math.floor(cut.rails!.back.length / 2);
    const updated = dragSurfacePoint(projector, cut, 'back', index, new THREE.Ray(new THREE.Vector3(1, 30, 5), new THREE.Vector3(0, -1, 0)));
    expect(updated.rails!.front).toEqual(cut.rails!.front);
    expect(updated.rails!.back[index]).not.toEqual(cut.rails!.back[index]);
    const point = new THREE.Vector3(...updated.rails!.back[index]);
    expect(projector.nearest(point)!.distanceTo(point)).toBeLessThan(1e-6);
    expect(cut).toEqual(original);
    projector.dispose(); model.dispose();
  });
  it('never moves a point into empty space when the pointer leaves the mesh', () => {
    const model = new THREE.SphereGeometry(10), projector = new SurfaceProjector(model);
    const cut = attachStrokeToSurface(projector, stroke);
    const updated = dragSurfacePoint(projector, cut, 'front', 0, new THREE.Ray(new THREE.Vector3(50, -30, 50), new THREE.Vector3(0, 1, 0)));
    expect(updated).toBe(cut);
    projector.dispose(); model.dispose();
  });
  it('moves one Pen anchor as a unified front-and-back control', () => {
    const model = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(model);
    const cut = attachStrokeToSurface(projector, stroke);
    const index = penAnchorIndices(cut.points.length)[4];
    const updated = dragPenControl(projector, cut, index, 'anchor', new THREE.Ray(new THREE.Vector3(2, -30, 4), new THREE.Vector3(0, 1, 0)));
    expect(updated.points[index]).not.toEqual(cut.points[index]);
    expect(updated.rails!.front[index]).not.toEqual(cut.rails!.front[index]);
    expect(updated.rails!.back[index]).not.toEqual(cut.rails!.back[index]);
    for (const point of [updated.rails!.front[index], updated.rails!.back[index]]) expect(projector.nearest(new THREE.Vector3(...point))!.distanceTo(new THREE.Vector3(...point))).toBeLessThan(1e-6);
    projector.dispose(); model.dispose();
  });
  it('mirrors Pen tangent handles and bends only through explicit curve controls', () => {
    const model = new THREE.SphereGeometry(10, 48, 32), projector = new SurfaceProjector(model);
    const base = attachStrokeToSurface(projector, stroke);
    const index = penAnchorIndices(base.points.length)[4], anchor = base.points[index];
    const cut: FreeCut = { ...base, penCurves: { [index]: { in: [anchor[0] - 1, anchor[1]], out: [anchor[0] + 1, anchor[1]] } } };
    const updated = dragPenControl(projector, cut, index, 'out', new THREE.Ray(new THREE.Vector3(4, -30, 5), new THREE.Vector3(0, 1, 0)));
    const curve = updated.penCurves![index];
    expect(curve.in[0] + curve.out[0]).toBeCloseTo(anchor[0] * 2);
    expect(curve.in[1] + curve.out[1]).toBeCloseTo(anchor[1] * 2);
    expect(updated.points[index - 1]).not.toEqual(cut.points[index - 1]);
    projector.dispose(); model.dispose();
  });
  it('does not change source indices while building the spatial lookup', () => {
    const source = new THREE.BoxGeometry(20, 20, 20), before = source.index!.array.slice();
    const projector = new SurfaceProjector(source);
    attachStrokeToSurface(projector, stroke);
    expect(source.index!.array).toEqual(before); projector.dispose(); source.dispose();
  });
});
