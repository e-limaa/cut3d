import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import type { FreeCut, Vec3 } from './freeCut';
import { SurfaceProjector } from './surfaceAnchors';
import { toggleBezier, moveBezier, editableRails, bezierHandles } from './surfaceBezier';
import { getConnectorFrame } from './geometry/connectorFrame';
import { pickConnectorPosition } from './connectorInteraction';
import { ruledSheet } from './geometry/ruledSheet';

const geometry = new THREE.BoxGeometry(20, 20, 20);
const projector = new SurfaceProjector(geometry);
function fixture(): FreeCut {
  const points: [number, number][] = [-10, -6, -2, 2, 6, 10].map(x => [x, 0]);
  return { points, origin: [0,0,0], u: [1,0,0], v: [0,0,1], w: [0,-1,0], depthMin: -10, depthMax: 10, kerf: .2,
    rails: { front: points.map(([x,z]) => [x,-10,z]), back: points.map(([x,z]) => [x,10,z]) },
    connector: { enabled: true, shape:'cylinder', diameter:2, length:3, clearance:.2, side:1, along:.8, across:.5 },
  };
}
describe('stable surface Bezier controls', () => {
  it('keeps every original anchor and the pin position when enabling and disabling a curve', () => {
    const cut = fixture(), curved = toggleBezier(projector, cut, 'front', 1);
    expect(editableRails(curved)).toBe(cut.rails);
    expect(curved.points).toBe(cut.points);
    expect(curved.rails!.front.length).toBeGreaterThan(cut.rails!.front.length);
    expect(getConnectorFrame(curved)).toEqual(getConnectorFrame(cut));
    const straight = toggleBezier(projector, curved, 'front', 1);
    expect(straight.rails).toEqual(cut.rails);
    expect(ruledSheet(straight,20)).toEqual(ruledSheet(cut,20));
  });
  it('moves an independent handle without touching any anchor, opposite geometry or remote segment', () => {
    const cut = toggleBezier(projector, fixture(), 'front', 2), original = structuredClone(cut);
    const target = new THREE.Vector3(...bezierHandles(cut,'front',2)!.out).add(new THREE.Vector3(0,0,.6));
    const next = moveBezier(projector,cut,'front',2,'out',target);
    expect(next).not.toBe(cut);
    expect(next.bezier!.anchors).toEqual(cut.bezier!.anchors);
    expect(next.rails!.back).toEqual(cut.rails!.back);
    expect(next.bezier!.segments.front[0]).toBe(cut.bezier!.segments.front[0]);
    expect(next.bezier!.segments.front[4]).toBe(cut.bezier!.segments.front[4]);
    expect(next.bezier!.segments.front[1]).toEqual(cut.bezier!.segments.front[1]);
    expect(next.bezier!.segments.front[2]).not.toEqual(cut.bezier!.segments.front[2]);
    expect(bezierHandles(next,'front',2)!.in).toBe(bezierHandles(cut,'front',2)!.in);
    expect(cut).toEqual(original);
    expect(() => ruledSheet(next,20)).not.toThrow();
  });
  it.each([0,2,5])('translates handles with anchor %i and preserves the opposite endpoint', index => {
    const cut = toggleBezier(projector, fixture(), 'front', index);
    const delta = new THREE.Vector3(0,0,.2), target = new THREE.Vector3(...editableRails(cut)!.front[index]).add(delta);
    const next = moveBezier(projector,cut,'front',index,'anchor',target);
    expect(next).not.toBe(cut);
    expect(editableRails(next)!.back).toBe(editableRails(cut)!.back);
    for (const kind of ['in','out'] as const) expect(bezierHandles(next,'front',index)![kind]).toEqual(new THREE.Vector3(...bezierHandles(cut,'front',index)![kind]).add(delta).toArray());
    editableRails(cut)!.front.forEach((p,i) => { if (i!==index) expect(editableRails(next)!.front[i]).toBe(p); });
  });
  it('rejects loops, duplicate endpoints and failed projection atomically', () => {
    const cut = toggleBezier(projector, fixture(), 'front', 2);
    expect(moveBezier(projector,cut,'front',2,'out',new THREE.Vector3(-5,-10,0))).toBe(cut);
    expect(moveBezier(projector,cut,'front',2,'anchor',new THREE.Vector3(...editableRails(cut)!.front[3]))).toBe(cut);
    const spy=vi.spyOn(projector,'nearest').mockReturnValue(null);
    expect(moveBezier(projector,cut,'front',2,'out',new THREE.Vector3(0,-10,.5))).toBe(cut);
    spy.mockRestore();
  });
  it('round trips multiple cuts and keeps connector picking in anchor coordinates', () => {
    const cut = toggleBezier(projector, fixture(), 'front', 1);
    const saved=JSON.parse(JSON.stringify([cut,fixture()])) as FreeCut[];
    const next=moveBezier(projector,saved[0],'front',1,'out',new THREE.Vector3(-4.5,-10,.4));
    expect(next).not.toBe(saved[0]);
    expect(saved[1]).toEqual(fixture());
    const frame=getConnectorFrame(cut), ray=new THREE.Ray(new THREE.Vector3(...frame.center).add(new THREE.Vector3(0,0,20)),new THREE.Vector3(0,0,-1));
    const position=pickConnectorPosition(cut,ray)!;
    expect(position.along).toBeCloseTo(.8);
    expect(position.across).toBeCloseTo(.5);
    for (const p of next.bezier!.segments.front[1]) expect(projector.nearest(new THREE.Vector3(...p as Vec3))!.distanceTo(new THREE.Vector3(...p))).toBeLessThan(1e-6);
  });
});
