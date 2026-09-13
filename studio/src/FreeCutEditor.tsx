import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import type { FreeCut, Vec3 } from './freeCut';
import { freeCutPoint, simplifyStroke } from './strokeMath';
import { SurfaceProjector, attachStrokeToSurface, dragPenControl, penAnchorIndices, rebuildSurfaceCurve, surfaceCurve } from './surfaceAnchors';
import ConnectorPreview from './ConnectorPreview';
import ConnectorGizmo from './ConnectorGizmo';

type Props = {
  geometry: THREE.BufferGeometry;
  size: number;
  drawing: boolean;
  cut: FreeCut | null;
  visible: boolean;
  editing: boolean;
  selectedPoint: number | null;
  onSelectPoint: (index: number | null) => void;
  editingConnector:boolean;
  onDraw: (cut: FreeCut) => void;
  onCancel: () => void;
  onError: (message: string) => void;
};
function worldPoint(cut: FreeCut, point: [number, number], depth: number) {
  return new THREE.Vector3(...freeCutPoint(cut, point, depth));
}
function SurfaceHandle({ point, color, selected, overlay = false }: {point: THREE.Vector3; color: string; selected: boolean; overlay?: boolean; onPointerDown: (event: ThreeEvent<PointerEvent>) => void}) {
  const group = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  useFrame(({camera, size: viewport}) => {
    if (!group.current) return;
    const worldPerPixel = camera instanceof THREE.OrthographicCamera
      ? (camera.top-camera.bottom)/(camera.zoom*viewport.height)
      : 2*camera.position.distanceTo(point)*Math.tan(THREE.MathUtils.degToRad((camera as THREE.PerspectiveCamera).fov/2))/viewport.height;
    group.current.scale.setScalar(worldPerPixel * 5);
  });
  return <group ref={group} position={point}>
    <mesh scale={selected || hovered ? 1.35 : 1} renderOrder={12}><sphereGeometry args={[1,16,10]}/><meshBasicMaterial color={selected ? '#ffe098' : hovered ? '#ffffff' : color} depthTest={!overlay}/></mesh>
    <mesh onPointerOver={event => { event.stopPropagation(); setHovered(true); document.body.style.cursor='grab'; }} onPointerOut={event => { event.stopPropagation(); setHovered(false); document.body.style.cursor=''; }}>
      <sphereGeometry args={[3.6,12,8]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/>
    </mesh>
  </group>;
}
/** Keep hand-drawn geometry faithful; downsample by screen-space distance only. */
export default function FreeCutEditor({ geometry, size, drawing, cut, visible, editing, selectedPoint, onSelectPoint, editingConnector, onDraw, onCancel, onError }: Props) {
  const { camera, gl, invalidate, controls } = useThree();
  const [live, setLive] = useState<THREE.Vector3[]>([]);
  const [dragged, setDragged] = useState<{ kind: 'anchor' | 'in' | 'out'; index: number; side?: 'front' | 'back' } | null>(null);
  const dragStart = useRef<FreeCut | null>(null);
  const [selectedSide,setSelectedSide] = useState<'front'|'back'>('front');
  const [connectorDragging, setConnectorDragging] = useState(false);
  const receiveConnectorDrag = useCallback((value:boolean)=>setConnectorDragging(value),[]);
  const projector = useMemo(() => new SurfaceProjector(geometry), [geometry]);
  const curveKeys = Object.keys(cut?.penCurves ?? {}).sort((a, b) => Number(a) - Number(b)).join(',');
  const previousCurveKeys = useRef(curveKeys);
  useEffect(() => () => projector.dispose(), [projector]);
  useEffect(() => {
    if (!cut?.rails || previousCurveKeys.current === curveKeys) return;
    const before = new Set(previousCurveKeys.current.split(',').filter(Boolean));
    const after = new Set(curveKeys.split(',').filter(Boolean));
    const changed = [...new Set([...before, ...after])].filter(key => before.has(key) !== after.has(key)).map(Number);
    previousCurveKeys.current = curveKeys;
    let updated=cut;
    for (const index of changed) updated=rebuildSurfaceCurve(projector,updated,selectedSide,index);
    onDraw(updated);
  }, [curveKeys, cut, projector, onDraw, selectedSide]);
  useEffect(() => { if (!editing) { setDragged(null); onSelectPoint(null); } }, [editing, onSelectPoint]);
  useEffect(() => {
    if (!drawing) { setLive([]); return; }
    const canvas = gl.domElement;
    let points: [number, number][] = [];
    let samples: THREE.Vector2[] = [];
    let frame: FreeCut | null = null;
    let pointer: number | null = null;
    let tooLong = false;
    let lastPixel = new THREE.Vector2(Infinity, Infinity);
    const raycaster = new THREE.Raycaster();
    const coords = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      return new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2);
    };
    const append = (event: PointerEvent, force = false) => {
      if (!frame) return;
      const pixel = new THREE.Vector2(event.clientX, event.clientY);
      if (!force && pixel.distanceTo(lastPixel) < 3) return;
      if (points.length >= 2048) { tooLong = true; return; }
      lastPixel = pixel;
      const ndc = coords(event);
      raycaster.setFromCamera(ndc, camera);
      const hit = raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(...frame.w), 0), new THREE.Vector3());
      if (!hit) return;
      points.push([hit.dot(new THREE.Vector3(...frame.u)), hit.dot(new THREE.Vector3(...frame.v))]);
      samples.push(ndc);
      setLive(points.map(point => worldPoint(frame!, point, 0))); invalidate();
    };
    const down = (event: PointerEvent) => {
      if (event.button !== 0) return;
      event.preventDefault();
      pointer = event.pointerId; canvas.setPointerCapture(pointer);
      camera.updateMatrixWorld();
      const u = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).normalize();
      const v = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion).normalize();
      const w = u.clone().cross(v).normalize();
      frame = { points: [], origin: [0, 0, 0], u: u.toArray() as Vec3, v: v.toArray() as Vec3, w: w.toArray() as Vec3, depthMin: -size / 2, depthMax: size / 2, kerf: Math.max(.1, size * .0015) };
      points = []; samples = []; tooLong = false; append(event, true);
    };
    const move = (event: PointerEvent) => { if (pointer === event.pointerId) append(event); };
    const up = (event: PointerEvent) => {
      if (pointer !== event.pointerId || !frame) return;
      append(event, true);
      canvas.releasePointerCapture(pointer); pointer = null;
      if (tooLong) { onError('Este traço ficou longo demais. Desenhe a região em um gesto mais curto.'); return; }
      if (points.length < 3) { onError('Desenhe um traço mais longo sobre a região que deseja cortar.'); return; }
      const filtered = simplifyStroke(points, camera instanceof THREE.OrthographicCamera ? 1 / camera.zoom : size * .001);
      try { onDraw(attachStrokeToSurface(projector, { ...frame, points: filtered })); }
      catch (error) { onError(error instanceof Error ? error.message : 'Não foi possível apoiar o corte na superfície.'); }
      setLive([]); invalidate();
    };
    const cancel = () => { pointer = null; setLive([]); onCancel(); };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') cancel(); };
    canvas.style.cursor = 'crosshair';
    canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', cancel); window.addEventListener('keydown', key);
    return () => { canvas.style.cursor = ''; canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', cancel); window.removeEventListener('keydown', key); };
  }, [drawing, projector, size, camera, gl, invalidate, onDraw, onCancel, onError]);

  const front = useMemo(() => cut?.rails?.front.map(point => new THREE.Vector3(...point)) ?? cut?.points.map(point => worldPoint(cut, point, cut.depthMax)) ?? [], [cut]);
  const back = useMemo(() => cut?.rails?.back.map(point => new THREE.Vector3(...point)) ?? cut?.points.map(point => worldPoint(cut, point, cut.depthMin)) ?? [], [cut]);
  const editableHandleIndices = useMemo(() => penAnchorIndices(front.length), [front.length]);
  // Resolve the closest visible control in screen space before OrbitControls
  // receives the gesture. Large overlapping 3D hit spheres picked neighbours.
  useEffect(() => {
    if (!editing || !visible || drawing || !cut?.rails) return;
    const canvas = gl.domElement;
    const down = (event: PointerEvent) => {
      if (event.button !== 0) return;
      const rect = canvas.getBoundingClientRect();
      const candidates: {index:number; kind:'anchor'|'in'|'out'; side:'front'|'back'; distance:number}[] = [];
      const consider = (point: THREE.Vector3, index:number, kind:'anchor'|'in'|'out', side:'front'|'back') => {
        if (kind === 'anchor') {
          const ndc=point.clone().project(camera);
          const visibilityRay=new THREE.Raycaster();
          visibilityRay.setFromCamera(new THREE.Vector2(ndc.x,ndc.y),camera);
          const hit=projector.hit(visibilityRay.ray);
          if(hit && hit.distanceTo(visibilityRay.ray.origin)+size*1e-5 < point.distanceTo(visibilityRay.ray.origin)) return;
        }
        const projected = point.clone().project(camera);
        if (projected.z < -1 || projected.z > 1) return;
        const distance = Math.hypot(rect.left + (projected.x+1)*rect.width/2-event.clientX, rect.top+(1-projected.y)*rect.height/2-event.clientY);
        if (distance <= 9) candidates.push({index,kind,side,distance});
      };
      for (const index of editableHandleIndices) {
        consider(front[index], index, 'anchor', 'front');
        if (index !== 0 && index !== front.length-1) consider(back[index], index, 'anchor', 'back');
      }
      if (selectedPoint !== null && cut.penCurves?.[selectedPoint]) {
        for (const kind of ['in','out'] as const) {
          const handles=surfaceCurve(cut,selectedSide,selectedPoint);
          if(handles) consider(new THREE.Vector3(...handles[kind]),selectedPoint,kind,selectedSide);
        }
      }
      candidates.sort((a,b)=>a.distance-b.distance);
      const closest = candidates[0];
      if (!closest) return;
      event.preventDefault(); event.stopImmediatePropagation();
      const orbit=controls as unknown as {enabled:boolean}|null;
      if (orbit) orbit.enabled=false;
      canvas.setPointerCapture(event.pointerId);
      onSelectPoint(closest.index); setSelectedSide(closest.side); dragStart.current=cut;
      setDragged({kind:closest.kind,index:closest.index,side:closest.side});
      document.body.style.cursor='grabbing';
    };
    canvas.addEventListener('pointerdown',down,true);
    return ()=>canvas.removeEventListener('pointerdown',down,true);
  }, [editing, visible, drawing, cut, gl, camera, projector, controls, editableHandleIndices, front, back, selectedPoint, onSelectPoint, selectedSide, size]);
  const surface = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    if (front.length < 2) return geometry;
    const vertices: number[] = [];
    for (let i = 0; i < front.length - 1; i++) for (const point of [front[i], back[i], front[i + 1], front[i + 1], back[i], back[i + 1]]) vertices.push(...point.toArray());
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)); geometry.computeVertexNormals(); return geometry;
  }, [front, back]);
  useEffect(() => () => surface.dispose(), [surface]);
  useEffect(() => {
    if (dragged === null || !cut) return;
    const canvas = gl.domElement;
    const raycaster = new THREE.Raycaster();
    const move = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), camera);
      const baseline = dragStart.current ?? cut;
      const next = dragPenControl(projector, baseline, dragged.index, dragged.kind, raycaster.ray, dragged.side);
      if (next !== baseline) { onDraw(next); invalidate(); }
    };
    const up = (event?: PointerEvent) => { if (event && canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); setDragged(null); dragStart.current = null; document.body.style.cursor = ''; const orbit=controls as unknown as {enabled:boolean}|null; if(orbit) orbit.enabled=true; };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape' && dragStart.current) { onDraw(dragStart.current); up(); } };
    canvas.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
    window.addEventListener('keydown', key);
    return () => { canvas.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); window.removeEventListener('keydown', key); };
  }, [dragged, cut, projector, gl, camera, controls, onDraw, invalidate]);
  useEffect(() => {
    const orbit = controls as unknown as { enabled: boolean } | null;
    if (orbit) orbit.enabled = !drawing && dragged === null && !connectorDragging && !editingConnector;
    return () => { if (orbit) orbit.enabled = true; };
  }, [controls, drawing, dragged, connectorDragging, editingConnector]);
  return <group>
    {live.length > 1 ? <Line points={live} color="#2d8862" lineWidth={3} depthTest={false} renderOrder={10}/> : null}
    {cut && visible && !drawing && front.length > 1 ? <>
      <ConnectorPreview cut={cut}/>
      {cut.connector?.enabled && editingConnector && !editing ? <ConnectorGizmo cut={cut} onCut={onDraw} onDrag={receiveConnectorDrag}/> : null}
      <mesh geometry={surface} renderOrder={5}><meshBasicMaterial color="#54e66c" transparent opacity={.42} side={THREE.DoubleSide} depthTest={false} depthWrite={false}/></mesh>
      <Line points={front} color="#236445" lineWidth={2.5} depthTest={false} renderOrder={7}/><Line points={back} color="#387f56" lineWidth={2} dashed dashSize={size * .015} gapSize={size * .01} depthTest={false} renderOrder={7}/>
      {[0, front.length - 1].map(i => <Line key={i} points={[front[i], back[i]]} color="#387f56" lineWidth={1.5} depthTest={false} renderOrder={7}/>)}
      {editing ? editableHandleIndices.flatMap(index => (['front', 'back'] as const).map(side => {
        if (side === 'back' && (index === 0 || index === front.length-1)) return null;
        const point = side === 'front' ? front[index] : back[index];
        return <SurfaceHandle key={`${side}-${index}`} point={point} selected={selectedPoint === index && selectedSide === side} color="#2f7f55" onPointerDown={event => {
          if (!projector.isVisible(point, camera.position)) return;
          event.stopPropagation(); const orbit=controls as unknown as {enabled:boolean}|null; if(orbit) orbit.enabled=false;
          onSelectPoint(index); dragStart.current = cut; document.body.style.cursor = 'grabbing'; setDragged({ kind: 'anchor', index, side });
        }}/>;
      })) : null}
      {editing && selectedPoint !== null && cut.penCurves?.[selectedPoint] ? [selectedSide].flatMap(side => {
        const anchor = side === 'front' ? front[selectedPoint] : back[selectedPoint];
        return (['in', 'out'] as const).map(kind => {
          const handles=surfaceCurve(cut,side,selectedPoint);
          if (!handles) return null;
          const handle = new THREE.Vector3(...handles[kind]);
          return <group key={`${side}-${selectedPoint}-${kind}`}><Line points={[anchor, handle]} color="#d89a3b" lineWidth={1.5} depthTest={false} renderOrder={11}/><SurfaceHandle point={handle} selected={dragged?.kind === kind && dragged.index === selectedPoint} color="#d89a3b" overlay onPointerDown={event => {
            if (!projector.isVisible(handle, camera.position)) return;
            event.stopPropagation(); const orbit=controls as unknown as {enabled:boolean}|null; if(orbit) orbit.enabled=false;
            dragStart.current = cut; document.body.style.cursor = 'grabbing'; setDragged({ kind, index: selectedPoint, side });
          }}/></group>;
        });
      }) : null}
    </> : null}
  </group>;
}




