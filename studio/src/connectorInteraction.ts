import * as THREE from 'three';
import type {FreeCut} from './freeCut';
import {cutRails, railParameters} from './geometry/connectorFrame';

/** Pick the visible ruled surface and return connector coordinates on it. */
export function pickConnectorPosition(cut:FreeCut, ray:THREE.Ray): {along:number;across:number}|null {
  const {front,back}=cutRails(cut);
  const parameters=railParameters(cut);
  let distance=Infinity, result:{along:number;across:number}|null=null;
  for(let i=0;i<front.length-1;i++) {
    const vertices=[front[i],front[i+1],back[i],back[i+1]].map(p=>new THREE.Vector3(...p));
    const uv=[[parameters[i],0],[parameters[i+1],0],[parameters[i],1],[parameters[i+1],1]];
    for(const ids of [[0,1,2],[1,3,2]]) {
      const [a,b,c]=ids.map(j=>vertices[j]);
      const hit=ray.intersectTriangle(a,b,c,false,new THREE.Vector3());
      if(!hit || hit.distanceToSquared(ray.origin)>=distance) continue;
      const weights=new THREE.Triangle(a,b,c).getBarycoord(hit,new THREE.Vector3());
      if(!weights) continue;
      distance=hit.distanceToSquared(ray.origin);
      const w=weights.toArray();
      result={along:ids.reduce((s,j,k)=>s+uv[j][0]*w[k],0),across:ids.reduce((s,j,k)=>s+uv[j][1]*w[k],0)};
    }
  }
  return result;
}
