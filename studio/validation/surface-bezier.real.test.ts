import { readFileSync } from 'node:fs';
import { it, expect } from 'vitest';
import * as THREE from 'three';
import { SurfaceProjector } from '../src/surfaceAnchors';
import { toggleBezier, moveBezier, bezierHandles } from '../src/surfaceBezier';
import type { FreeCut } from '../src/freeCut';
import { ruledSheet } from '../src/geometry/ruledSheet';
import { splitFreeGeometryData } from '../src/geometry/engine';

// Opt-in: local private model and plan are deliberately not bundled with the repository.
const directory = process.env.CUT3D_REAL_DIAGNOSTICS;
const planPath = process.env.CUT3D_REAL_PLAN;
it.skipIf(!directory || !planPath)('edits the saved neck contour on the two-million-triangle model without global reconstruction', async () => {
  const p=readFileSync(`${directory}/model.positions.bin`), i=readFileSync(`${directory}/model.indices.bin`);
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(p.buffer.slice(p.byteOffset,p.byteOffset+p.byteLength)),3));
  geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(i.buffer.slice(i.byteOffset,i.byteOffset+i.byteLength)),1));
  geometry.computeBoundingBox(); const center=geometry.boundingBox!.getCenter(new THREE.Vector3()); geometry.translate(-center.x,-center.y,-center.z);
  const projector=new SurfaceProjector(geometry);
  const plan=JSON.parse(readFileSync(planPath!,'utf8'));
  const cut:FreeCut=plan.freeCut ?? plan.cuts.find((entry: {id:string})=>entry.id===plan.activeId).freeCut;
  const original=structuredClone(cut);
  let enabled=0, moved=0, buildable=0;
  let baselineBuildable=true;
  try { ruledSheet(cut, Math.max(...plan.dimensions)); } catch { baselineBuildable=false; }
  const rejected:number[]=[];
  for(const side of ['front','back'] as const) for(let index=0; index<cut.rails![side].length; index++) {
    const curved=toggleBezier(projector,cut,side,index);
    if(curved===cut) { rejected.push(index); continue; }
    enabled++;
    expect(curved.bezier!.anchors).toBe(cut.rails);
    const kind=index===cut.rails![side].length-1 ? 'in' : 'out';
    const target=new THREE.Vector3(...bezierHandles(curved,side,index)![kind]).addScaledVector(new THREE.Vector3(...cut.v),.03);
    const edited=moveBezier(projector,curved,side,index,kind,target);
    if(edited!==curved) moved++;
    expect(edited.bezier!.anchors).toEqual(cut.rails);
    const other=side==='front'?'back':'front';
    expect(edited.rails![other]).toEqual(curved.rails![other]);
    for(let segment=0;segment<edited.bezier!.segments[side].length;segment++) {
      if(segment!==index-1 && segment!==index) expect(edited.bezier!.segments[side][segment]).toBe(curved.bezier!.segments[side][segment]);
      else for(const sample of edited.bezier!.segments[side][segment]) {
        const point=new THREE.Vector3(...sample);
        expect(projector.nearest(point)!.distanceTo(point)).toBeLessThan(.001);
      }
    }
    expect(JSON.parse(JSON.stringify(edited))).toEqual(edited);
    try { ruledSheet(edited, Math.max(...plan.dimensions)); buildable++; } catch { /* Report build limitations independently. */ }
  }
  expect(cut).toEqual(original);
  expect(enabled).toBeGreaterThan(cut.rails!.front.length);
  expect(moved).toBeGreaterThan(0);
  if (baselineBuildable) expect(buildable).toBe(enabled);
  console.log('REAL_BEZIER', {triangles:geometry.index!.count/3, anchors:cut.rails!.front.length, enabled, moved, rejected, baselineBuildable, buildable});
  if(process.env.CUT3D_REAL_BUILD) {
    const index=Math.floor(cut.rails!.front.length/2);
    const curved=toggleBezier(projector,cut,'front',index);
    const target=new THREE.Vector3(...bezierHandles(curved,'front',index)!.out).addScaledVector(new THREE.Vector3(...cut.v),.03);
    const moved=moveBezier(projector,curved,'front',index,'out',target);
    const edited:FreeCut=process.env.CUT3D_REAL_PIN ? {...moved,connector:{enabled:true,shape:'hexagon',diameter:1.9,length:2.6,clearance:.25,side:1,along:.5,across:.5}} : moved;
    const outputs=await splitFreeGeometryData({positions:geometry.getAttribute('position').array as Float32Array,indices:geometry.index!.array as Uint32Array,weld:true},edited);
    expect(outputs.length).toBeGreaterThanOrEqual(2);
    for(const output of outputs) {
      const edges=new Map<string,number>();
      for(let i=0;i<output.indices.length;i+=3) for(let j=0;j<3;j++) {
        const a=output.indices[i+j],b=output.indices[i+(j+1)%3],key=a<b?`${a}:${b}`:`${b}:${a}`;
        edges.set(key,(edges.get(key)??0)+1);
      }
      expect([...edges.values()].every(n=>n===2)).toBe(true);
    }
    console.log('REAL_BEZIER_BUILD', {parts:outputs.length,pinEnabled:!!edited.connector?.enabled,triangles:outputs.map(o=>o.indices.length/3)});
  }
  projector.dispose();geometry.dispose();
},120000);
