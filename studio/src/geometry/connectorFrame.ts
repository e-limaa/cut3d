import type { FreeCut, Vec3 } from '../freeCut';

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0]+b[0],a[1]+b[1],a[2]+b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0]-b[0],a[1]-b[1],a[2]-b[2]];
export const scale = (a: Vec3, n: number): Vec3 => [a[0]*n,a[1]*n,a[2]*n];
export const dot = (a: Vec3,b: Vec3): number => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
export const cross = (a: Vec3,b: Vec3): Vec3 => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export const unit = (a: Vec3): Vec3 => scale(a,1/(Math.hypot(...a)||1));
export const mix = (a: Vec3,b: Vec3,t: number): Vec3 => add(a,scale(sub(b,a),t));

export function cutRails(cut: FreeCut): {front: Vec3[]; back: Vec3[]} {
  if (cut.rails) return cut.rails;
  const at = (p: [number,number],d: number) => add(cut.origin,add(add(scale(cut.u,p[0]),scale(cut.v,p[1])),scale(cut.w,d)));
  return {front:cut.points.map(p=>at(p,cut.depthMax)),back:cut.points.map(p=>at(p,cut.depthMin))};
}

/** Same bilinear ruled surface used by the cutter, in world coordinates. */
export function getConnectorFrame(cut: FreeCut): {center: Vec3; normal: Vec3; tangent: Vec3} {
  const {front,back}=cutRails(cut);
  const t=Math.max(0,Math.min(1,cut.connector?.along??.5))*(front.length-1);
  const i=Math.min(front.length-2,Math.floor(t)), f=t-i;
  const a=Math.max(0,Math.min(1,cut.connector?.across??.5));
  const start=mix(front[i],front[i+1],f), end=mix(back[i],back[i+1],f);
  const tangent=unit(mix(sub(front[i+1],front[i]),sub(back[i+1],back[i]),a));
  return {center:mix(start,end,a),normal:unit(cross(tangent,sub(end,start))),tangent};
}
