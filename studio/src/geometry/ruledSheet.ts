import type { FreeCut, Vec3 } from '../freeCut';
import { add, sub, scale, cross, dot, unit, mix } from './connectorFrame';
import { GeometrySplitError } from './types';

const invalid = () => new GeometrySplitError('invalid-free-cut','As curvas do corte estão degeneradas, invertidas ou se cruzam. Afaste os controles e mantenha a correspondência entre frente e verso.');

/** Closed offset of a sampled bilinear sheet. Extensions exist only in this boolean tool. */
export function ruledSheet(cut: FreeCut, extent: number): {positions: Float32Array; indices: Uint32Array; weld: boolean} {
  const rails=cut.rails!;
  if (!rails || rails.front.length<2 || rails.front.length!==rails.back.length || rails.front.length>2048) throw invalid();
  for(const p of [...rails.front,...rails.back]) if(p.length!==3 || !p.every(Number.isFinite)) throw invalid();
  const margin=Math.max(cut.kerf*2,extent*.015), eps=extent*1e-9;
  const front=rails.front.map(p=>[...p] as Vec3), back=rails.back.map(p=>[...p] as Vec3);
  for(let i=0;i<front.length;i++) {
    let across=sub(back[i],front[i]);
    if(Math.hypot(...across)<eps) {
      if(i!==0 && i!==front.length-1) throw invalid();
      across=sub(back[i===0?1:i-1],front[i===0?1:i-1]);
    }
    if(Math.hypot(...across)<eps) throw invalid();
    const neighbour=Math.min(front.length-1,i+1); const previous=Math.max(0,i-1);
    const chord=Math.max(Math.hypot(...sub(rails.front[neighbour],rails.front[i])),Math.hypot(...sub(rails.front[i],rails.front[previous])),Math.hypot(...sub(rails.back[neighbour],rails.back[i])),Math.hypot(...sub(rails.back[i],rails.back[previous])));
    const d=scale(unit(across),Math.max(margin,Math.min(extent*.06,chord*.4)));
    front[i]=sub(front[i],d); back[i]=add(back[i],d);
  }
  // Keep paired endpoints together: independent rail extensions can invert
  // a thin silhouette span even when the user's original controls are valid.
  for(const endpoint of [0,front.length-1]) {
    const neighbour=endpoint===0?1:endpoint-1;
    const across=unit(sub(back[endpoint],front[endpoint]));
    const tangent=sub(mix(front[endpoint],back[endpoint],.5),mix(front[neighbour],back[neighbour],.5));
    const extension=scale(unit(sub(tangent,scale(across,dot(tangent,across)))),margin);
    front[endpoint]=add(front[endpoint],extension);
    back[endpoint]=add(back[endpoint],extension);
  }
  const centers: Vec3[]=[], normals: Vec3[]=[], faces: number[]=[];
  // A denser grid produces smoother offset faces around curved rails while
  // keeping the editable anchors themselves at a practical count.
  const acrossSteps=24, alongSteps=4, rows=(front.length-1)*alongSteps+1, cols=acrossSteps+1;
  for(let row=0;row<rows;row++) {
    const t=row/alongSteps,i=Math.min(front.length-2,Math.floor(t)), f=t-i;
    const a=mix(front[i],front[i+1],f),b=mix(back[i],back[i+1],f);
    for(let col=0;col<cols;col++) {
      const s=col/acrossSteps;
      const tangent=mix(sub(front[i+1],front[i]),sub(back[i+1],back[i]),s);
      const n=cross(tangent,sub(b,a));
      if(Math.hypot(...n)<eps) throw invalid();
      centers.push(mix(a,b,s));normals.push(unit(n));
      if(col>0 && dot(normals.at(-1)!,normals.at(-2)!)<0) throw invalid();
    }
  }
  for(let r=0;r<rows-1;r++) for(let c=0;c<cols-1;c++) {
    const a=r*cols+c,b=a+cols;
    faces.push(a,b,b+1,a,b+1,a+1);
  }
  // Test non-neighbouring surface triangles for actual crossings (not an X-monotonicity rule).
  const intersects=(p:Vec3,q:Vec3,a:Vec3,b:Vec3,c:Vec3) => {
    const d=sub(q,p),e1=sub(b,a),e2=sub(c,a),h=cross(d,e2),det=dot(e1,h);
    if(Math.abs(det)<eps) return false;
    const s=sub(p,a),u=dot(s,h)/det,v=dot(d,cross(s,e1))/det,t=dot(e2,cross(s,e1))/det;
    return u>1e-7 && v>1e-7 && u+v<1-1e-7 && t>1e-7 && t<1-1e-7;
  };
  const crossingEdges=(a:Vec3,b:Vec3,c:Vec3,d:Vec3) => {
    const u=sub(b,a),v=sub(d,c),w=sub(a,c),aa=dot(u,u),bb=dot(u,v),cc=dot(v,v),dd=dot(u,w),ee=dot(v,w),den=aa*cc-bb*bb;
    if(Math.abs(den)<eps*eps) return false;
    const s=(bb*ee-cc*dd)/den,t=(aa*ee-bb*dd)/den;
    return s>1e-7 && s<1-1e-7 && t>1e-7 && t<1-1e-7 && Math.hypot(...sub(add(a,scale(u,s)),add(c,scale(v,t))))<Math.max(eps,cut.kerf*1e-5);
  };
  // Coarse rail patches are sufficient for detecting control-curve crossings; avoid quadratic tessellation work.
  for(let i=0;i<front.length-1;i++) for(let j=i+2;j<front.length-1;j++) {
    const a=[front[i],front[i+1],back[i+1],back[i]], b=[front[j],front[j+1],back[j+1],back[j]];
    for(let k=0;k<4;k++) for(let l=0;l<4;l++) if(crossingEdges(a[k],a[(k+1)%4],b[l],b[(l+1)%4])) throw invalid();
    for(let k=0;k<4;k++) if(intersects(a[k],a[(k+1)%4],b[0],b[1],b[2]) || intersects(a[k],a[(k+1)%4],b[0],b[2],b[3]) || intersects(b[k],b[(k+1)%4],a[0],a[1],a[2]) || intersects(b[k],b[(k+1)%4],a[0],a[2],a[3])) throw invalid();
  }
  const positions:number[]=[],indices:number[]=[],count=centers.length;
  for(const sign of [1,-1]) centers.forEach((p,i)=>positions.push(...add(p,scale(normals[i],sign*cut.kerf/2))));
  for(let i=0;i<faces.length;i+=3) {
    const [a,b,c]=faces.slice(i,i+3); indices.push(a,b,c,c+count,b+count,a+count);
  }
  const boundary:number[]=[];
  for(let r=0;r<rows;r++) boundary.push(r*cols);
  for(let c=1;c<cols;c++) boundary.push((rows-1)*cols+c);
  for(let r=rows-2;r>=0;r--) boundary.push(r*cols+cols-1);
  for(let c=cols-2;c>0;c--) boundary.push(c);
  for(let i=0;i<boundary.length;i++) { const a=boundary[i],b=boundary[(i+1)%boundary.length];indices.push(b,a,a+count,b,a+count,b+count); }
  return {positions:new Float32Array(positions),indices:new Uint32Array(indices),weld:true};
}

