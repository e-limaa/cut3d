import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import type { FreeCut } from '../freeCut';
import { splitFreeGeometry } from './client';
import { processGeometryRequest } from './requests';
import { demoModel } from '../model';
import { SurfaceProjector, attachStrokeToSurface } from '../surfaceAnchors';

const curved: FreeCut = {
  origin: [0, 0, 0], u: [1, 0, 0], v: [0, 1, 0], w: [0, 0, 1],
  points: [[-12, 0], [-5, 4], [0, -4], [5, 2], [12, 0]],
  depthMin: -11, depthMax: 11, kerf: .2,
};
function volume(geometry: THREE.BufferGeometry) {
  const positions = geometry.getAttribute('position'), indices = geometry.getIndex()!;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  let volume = 0;
  for (let i = 0; i < indices.count; i += 3) {
    a.fromBufferAttribute(positions, indices.getX(i)); b.fromBufferAttribute(positions, indices.getX(i + 1)); c.fromBufferAttribute(positions, indices.getX(i + 2));
    volume += a.dot(b.cross(c)) / 6;
  }
  return volume;
}
function closed(geometry: THREE.BufferGeometry) {
  const index = geometry.getIndex()!, edges = new Map<string, number>();
  for (let i = 0; i < index.count; i += 3) for (let j = 0; j < 3; j++) {
    const a = index.getX(i + j), b = index.getX(i + (j + 1) % 3);
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    edges.set(key, (edges.get(key) ?? 0) + 1);
  }
  expect([...edges.values()].every(value => value === 2)).toBe(true);
  expect(volume(geometry)).toBeGreaterThan(0);
}
function cleanup(...geometries: THREE.BufferGeometry[]) { geometries.forEach(g => g.dispose()); }
describe('freehand local cut', () => {
  it('builds a pin across a curved anchored seam', async () => {
    const source = new THREE.SphereGeometry(10, 64, 48);
    const projector = new SurfaceProjector(source);
    const cut = attachStrokeToSurface(projector, {...curved, points:[[-14,0],[-5,2],[0,-2],[5,2],[14,0]]});
    cut.connector = {enabled:true,shape:'cylinder',diameter:2.2,length:2.7,clearance:.25,side:1,along:.53,across:.5};
    const outputs = await splitFreeGeometry(source,cut);
    expect(outputs).toHaveLength(2); outputs.forEach(closed);
    projector.dispose(); cleanup(source,...outputs);
  });
  it.each(['sphere','bust'])('builds closed parts from actual %s shell anchors',async kind=>{
    const source=kind==='sphere'?new THREE.SphereGeometry(10,48,32):demoModel().geometry;
    const projector=new SurfaceProjector(source);
    const cut=attachStrokeToSurface(projector,{...curved,u:[1,0,0],v:[0,0,1],w:[0,-1,0],points:kind==='sphere'?[[-14,1],[-5,3],[0,1],[5,3],[14,1]]:[[-20,-5],[-7,-4],[0,-7],[7,-4],[20,-5]]});
    const outputs=await splitFreeGeometry(source,cut);
    expect(outputs).toHaveLength(2);outputs.forEach(closed);projector.dispose();cleanup(source,...outputs);
  });
  it('supports nonmonotonic paired rails and rejects an inverted patch',async()=>{
    const source=new THREE.BoxGeometry(20,20,20);
    const points:[number,number][]=[[-10,-3],[4,-3],[4,0],[-4,0],[-4,3],[10,3]];
    const cut:FreeCut={...curved,points,rails:{front:points.map(([x,y])=>[x,y,10]),back:points.map(([x,y])=>[x,y,-10])}};
    const outputs=await splitFreeGeometry(source,cut);expect(outputs).toHaveLength(2);outputs.forEach(closed);
    await expect(splitFreeGeometry(source,{...curved,rails:{front:[[-10,0,10],[10,0,10]],back:[[10,0,-10],[-10,0,-10]]}})).rejects.toThrow('degeneradas');
    cleanup(source,...outputs);
  });
  it('uses independently edited world rails on a sphere and preserves the original', async () => {
    const source=new THREE.SphereGeometry(10,64,32);
    const before=source.getAttribute('position').array.slice();
    const front: [number,number,number][]=[],back: [number,number,number][]=[];
    for(let i=0;i<=32;i++) {const t=Math.PI*i/32,x=-10*Math.cos(t),z=10*Math.sin(t);front.push([x,0,z]);back.push([x,0,-z]);}
    const cut:FreeCut={...curved,points:[[-10,0],[10,0]],rails:{front,back}};
    const a=await splitFreeGeometry(source,cut);
    const edited=back.map(([x,,z])=>{const y=.8*(1-x*x/100);return [x,y,-Math.sqrt(Math.max(0,100-x*x-y*y))] as [number,number,number];});
    const b=await splitFreeGeometry(source,{...cut,rails:{front,back:edited}});
    expect(a).toHaveLength(2);expect(b).toHaveLength(2);[...a,...b].forEach(closed);
    expect(a.map(volume).sort((a,b)=>a-b)[0]).not.toBeCloseTo(b.map(volume).sort((a,b)=>a-b)[0],1);
    expect(source.getAttribute('position').array).toEqual(before);cleanup(source,...a,...b);
  });
  it.each(['cylinder','square','hexagon','rectangle'] as const)('adds a connected %s pin and matching closed socket',async shape=>{
    const source=new THREE.BoxGeometry(20,20,20);
    const cut:FreeCut={...curved,points:[[-10,0],[10,0]],rails:{front:[[-10,0,10],[10,0,10]],back:[[-10,0,-10],[10,0,-10]]},connector:{enabled:true,shape,thickness:1.2,diameter:3,length:4,clearance:.2,side:1,along:.5,across:.5}};
    const baseline=await splitFreeGeometry(source,{...cut,connector:undefined});
    const a=await splitFreeGeometry(source,cut),b=await splitFreeGeometry(source,{...cut,connector:{...cut.connector!,side:-1,clearance:.4}});
    expect(a).toHaveLength(2);expect(b).toHaveLength(2);[...a,...b].forEach(closed);
    expect(Math.max(...a.map(volume))).toBeGreaterThan(Math.max(...baseline.map(volume)));
    expect(b.reduce((s,g)=>s+volume(g),0)).toBeLessThan(a.reduce((s,g)=>s+volume(g),0));
    await expect(splitFreeGeometry(source,{...cut,connector:{...cut.connector!,diameter:30}})).rejects.toThrow('encaixe');
    cleanup(source,...baseline,...a,...b);
  });
  it('constructs genuinely nonplanar cut faces, closed pieces and bounded material loss', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const positionsBefore = source.getAttribute('position').array.slice();
    const outputs = await splitFreeGeometry(source, curved);
    expect(outputs).toHaveLength(2); outputs.forEach(closed);
    const remaining = outputs.reduce((sum, g) => sum + volume(g), 0);
    expect(remaining).toBeGreaterThan(7500); expect(remaining).toBeLessThan(8000);
    const internalY = outputs.flatMap(g => {
      const p = g.getAttribute('position'), values: number[] = [];
      for (let i = 0; i < p.count; i++) if (Math.abs(p.getX(i)) < 9 && Math.abs(p.getY(i)) < 9) values.push(p.getY(i));
      return values;
    });
    expect(Math.min(...internalY)).toBeLessThan(-3.8); expect(Math.max(...internalY)).toBeGreaterThan(3.8);
    expect(source.getAttribute('position').array).toEqual(positionsBefore);
    cleanup(source, ...outputs);
  });
  it('leaves an occluded rear solid unchanged when depth is restricted to the front', async () => {
    const front = new THREE.BoxGeometry(20, 20, 8), rear = new THREE.BoxGeometry(20, 20, 8).translate(0, 0, -20);
    const source = mergeGeometries([front, rear]);
    const outputs = await splitFreeGeometry(source, { ...curved, depthMin: -5, depthMax: 5 });
    expect(outputs).toHaveLength(3); outputs.forEach(closed);
    const untouched = outputs.find(g => g.boundingBox!.max.z < -10)!;
    expect(untouched).toBeDefined(); expect(volume(untouched)).toBeCloseTo(3200, 3);
    expect(untouched.boundingBox!.min.toArray()).toEqual([-10, -10, -24]);
    expect(untouched.boundingBox!.max.toArray()).toEqual([10, 10, -16]);
    cleanup(front, rear, source, ...outputs);
  });
  it('rejects a shallow groove instead of publishing an unseparated part', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    await expect(splitFreeGeometry(source, { ...curved, depthMin: 0 })).rejects.toMatchObject({ code: 'insufficient-depth' });
    cleanup(source);
  });
  it('supports a path that doubles back in X without flattening it', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    const outputs = await splitFreeGeometry(source, { ...curved, points: [[-12, -3], [4, -3], [4, 0], [-4, 0], [-4, 3], [12, 3]] });
    expect(outputs).toHaveLength(2); outputs.forEach(closed); cleanup(source, ...outputs);
  });
  it('handles arbitrary camera frames and offsets', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20).translate(31, 12, -7);
    const outputs = await splitFreeGeometry(source, { ...curved, origin: [31, 12, -7], u: [1, 0, 0], v: [0, 0, 1], w: [0, -1, 0] });
    expect(outputs).toHaveLength(2); outputs.forEach(closed); cleanup(source, ...outputs);
  });
  it('cuts the study bust through a curved neck seam', async () => {
    const model = demoModel();
    const outputs = await splitFreeGeometry(model.geometry, { ...curved, u: [1, 0, 0], v: [0, 0, 1], w: [0, -1, 0], points: [[-20, -5], [-7, -4], [0, -7], [7, -4], [20, -5]], depthMin: -12, depthMax: 12 });
    expect(outputs).toHaveLength(2); outputs.forEach(closed); cleanup(model.geometry, ...outputs);
  });
  it.each([{ kerf: 0 }, { depthMax: -20 }, { u: [2, 0, 0] }, { points: [[0, 0], [NaN, 2]] }])('rejects invalid parameters %j', async patch => {
    const source = new THREE.BoxGeometry(20, 20, 20);
    await expect(splitFreeGeometry(source, { ...curved, ...patch } as FreeCut)).rejects.toMatchObject({ code: 'invalid-free-cut' }); cleanup(source);
  });
  it('routes the free-cut worker message to the freehand engine', async () => {
    const source = new THREE.BoxGeometry(20, 20, 20).toNonIndexed();
    const positions = new Float32Array(source.getAttribute('position').array);
    const response = await processGeometryRequest({ type: 'free-cut', input: { positions, indices: Uint32Array.from({ length: positions.length / 3 }, (_, i) => i), weld: true }, cut: curved });
    expect(response.type).toBe('success');
    if (response.type === 'success') expect(response.outputs).toHaveLength(2);
    cleanup(source);
  });
});
