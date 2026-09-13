import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';
import type { FreeCut, Vec3 } from './freeCut';
import { freeCutPoint, simplifyStroke } from './strokeMath';
import { SurfaceProjector, attachStrokeToSurface, dragSurfacePoint } from './surfaceAnchors';
import ConnectorPreview from './ConnectorPreview';
import ConnectorGizmo from './ConnectorGizmo';
import { listenForPointerDrag } from './pointerDrag';
import { editableRails, bezierHandles, moveBezier, toggleBezier } from './surfaceBezier';

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
function SurfaceHandle({ point, color, selected, overlay = false }: {point: THREE.Vector3; color: string; selected: boolean; overlay?: boolean}) {
  const group = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  useFrame(({camera, size: viewport}) => {
    if (!group.current) return;
    const worldPerPixel = camera instanceof THREE.OrthographicCamera
      ? (camera.top-camera.bottom)/(camera.zoom*viewport.height)
      : 2*camera.position.distanceTo(point)*Math.tan(THREE.MathUtils.degToRad((camera as THREE.PerspectiveCamera).fov/2))/viewport.height;
    group.current.scale.setScalar(worldPerPixel * 3.5);
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
  const pointerOffset = useRef(new THREE.Vector2());
  const handlePlane = useRef(new THREE.Plane());
  const activePointer = useRef<number | null>(null);
  const handleScale = useRef(1);
  const handleOrigin = useRef(new THREE.Vector3());
  const [limited, setLimited] = useState(false);
  const [selectedVisible, setSelectedVisible] = useState(true);
  const [, cameraChanged] = useState(0);
  const lastCamera = useRef('');
  useFrame(() => {
    if (!editing || selectedPoint === null) return;
    const signature = camera.matrixWorld.elements.join(',') + camera.projectionMatrix.elements.join(',') + selectedPoint + selectedSide + (cut ? editableRails(cut)?.[selectedSide][selectedPoint]?.join(',') : '');
    if (signature !== lastCamera.current) { lastCamera.current = signature; cameraChanged(n => n+1);
      const point = cut ? editableRails(cut)?.[selectedSide][selectedPoint] : undefined;
      if (point) {
        const anchor = new THREE.Vector3(...point), ndc = anchor.clone().project(camera), ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2(ndc.x, ndc.y), camera);
        const hit = projector.hit(ray.ray);
        setSelectedVisible(!hit || hit.distanceTo(ray.ray.origin)+size*1e-5 >= anchor.distanceTo(ray.ray.origin));
      } }
  });
  const [selectedSide,setSelectedSide] = useState<'front'|'back'>('front');
  const [connectorDragging, setConnectorDragging] = useState(false);
  const receiveConnectorDrag = useCallback((value:boolean)=>setConnectorDragging(value),[]);
  const projector = useMemo(() => new SurfaceProjector(geometry), [geometry]);
  useEffect(() => () => projector.dispose(), [projector]);
  useEffect(() => { if (!editing || !visible || drawing) { setDragged(null); dragStart.current = null; onSelectPoint(null); const id = activePointer.current; activePointer.current = null; if (id !== null && gl.domElement.hasPointerCapture(id)) gl.domElement.releasePointerCapture(id); document.body.style.cursor = ''; } }, [editing, visible, drawing, onSelectPoint, gl]);
  useEffect(() => () => { const id = activePointer.current; if (id !== null && gl.domElement.hasPointerCapture(id)) gl.domElement.releasePointerCapture(id); document.body.style.cursor = ''; }, [gl]);
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
  const anchors = cut ? editableRails(cut) : undefined;
  const anchorFront = useMemo(() => anchors?.front.map(p => new THREE.Vector3(...p)) ?? [], [anchors]);
  const anchorBack = useMemo(() => anchors?.back.map(p => new THREE.Vector3(...p)) ?? [], [anchors]);
  const editableHandleIndices = useMemo(() => Array.from({length:anchorFront.length},(_,index)=>index), [anchorFront.length]);
  const displayHandle = (point: THREE.Vector3, anchor: THREE.Vector3) => {
    const rect = gl.domElement.getBoundingClientRect();
    const a = anchor.clone().project(camera), b = point.clone().project(camera);
    const pixels = Math.hypot((a.x-b.x)*rect.width/2, (a.y-b.y)*rect.height/2);
    const scale = Math.max(1, 24 / Math.max(pixels, .25));
    return { point: anchor.clone().add(point.clone().sub(anchor).multiplyScalar(scale)), scale };
  };
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
        {
          const anchor = side === 'front' ? anchorFront[index] : anchorBack[index];
          const ndc=anchor.clone().project(camera);
          const visibilityRay=new THREE.Raycaster();
          visibilityRay.setFromCamera(new THREE.Vector2(ndc.x,ndc.y),camera);
          const hit=projector.hit(visibilityRay.ray);
          if(hit && hit.distanceTo(visibilityRay.ray.origin)+size*1e-5 < anchor.distanceTo(visibilityRay.ray.origin)) return;
        }
        const projected = point.clone().project(camera);
        if (projected.z < -1 || projected.z > 1) return;
        const distance = Math.hypot(rect.left + (projected.x+1)*rect.width/2-event.clientX, rect.top+(1-projected.y)*rect.height/2-event.clientY);
        if (distance <= 9) candidates.push({index,kind,side,distance});
      };
      for (const index of editableHandleIndices) {
        consider(anchorFront[index], index, 'anchor', 'front');
        if (anchorFront[index].distanceTo(anchorBack[index]) > size*1e-7) consider(anchorBack[index], index, 'anchor', 'back');
        const handles = index === selectedPoint ? bezierHandles(cut, selectedSide, index) : undefined;
        if (handles) for (const kind of ['in', 'out'] as const) {
          if ((kind === 'in' && index === 0) || (kind === 'out' && index === anchorFront.length - 1)) continue;
          consider(displayHandle(new THREE.Vector3(...handles[kind]), selectedSide === 'front' ? anchorFront[index] : anchorBack[index]).point, index, kind, selectedSide);
        }
      }
      candidates.sort((a,b) => (a.kind !== 'anchor' && a.distance < 7 ? -10 : a.distance) - (b.kind !== 'anchor' && b.distance < 7 ? -10 : b.distance));
      const closest = candidates[0];
      if (!closest) return;
      event.preventDefault(); event.stopImmediatePropagation();
      let control = closest.kind === 'anchor' ? (closest.side === 'front' ? anchorFront[closest.index] : anchorBack[closest.index]) : new THREE.Vector3(...bezierHandles(cut, closest.side, closest.index)![closest.kind]);
      handleOrigin.current.copy(closest.side === 'front' ? anchorFront[closest.index] : anchorBack[closest.index]);
      if (closest.kind !== 'anchor') { const display = displayHandle(control, handleOrigin.current); control = display.point; handleScale.current = display.scale; }
      setLimited(false);
      handlePlane.current.setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), control);
      activePointer.current = event.pointerId;
      const projected=control.clone().project(camera);
      pointerOffset.current.set(projected.x-((event.clientX-rect.left)/rect.width*2-1),projected.y-(1-(event.clientY-rect.top)/rect.height*2));
      const orbit=controls as unknown as {enabled:boolean}|null;
      if (orbit) orbit.enabled=false;
      canvas.setPointerCapture(event.pointerId);
      onSelectPoint(closest.index); setSelectedSide(closest.side); dragStart.current=cut;
      setDragged({kind:closest.kind,index:closest.index,side:closest.side});
      document.body.style.cursor='grabbing';
    };
    canvas.addEventListener('pointerdown',down,true);
    return ()=>canvas.removeEventListener('pointerdown',down,true);
  }, [editing, visible, drawing, cut, gl, camera, projector, controls, editableHandleIndices, anchorFront, anchorBack, selectedPoint, onSelectPoint, selectedSide, size, onError]);
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
      if (event.pointerId !== activePointer.current) return;
      const rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2).add(pointerOffset.current), camera);
      const baseline = dragStart.current ?? cut;
      const target = dragged.kind === 'anchor' ? projector.hit(raycaster.ray) : raycaster.ray.intersectPlane(handlePlane.current, new THREE.Vector3());
      if (!target) return;
      if (dragged.kind !== 'anchor') target.sub(handleOrigin.current).divideScalar(handleScale.current).add(handleOrigin.current);
      const next = !baseline.bezier && dragged.kind === 'anchor'
        ? dragSurfacePoint(projector, baseline, dragged.side ?? 'front', dragged.index, raycaster.ray)
        : moveBezier(projector, baseline, dragged.side ?? 'front', dragged.index, dragged.kind, target);
      setLimited(next === baseline);
      if (next !== baseline) {
        onDraw(next); invalidate();
      }
    };
    const up = (event?: PointerEvent) => { if (event && event.pointerId !== activePointer.current) return; if (activePointer.current !== null && canvas.hasPointerCapture(activePointer.current)) canvas.releasePointerCapture(activePointer.current); activePointer.current = null; setDragged(null); dragStart.current = null; document.body.style.cursor = ''; const orbit=controls as unknown as {enabled:boolean}|null; if(orbit) orbit.enabled=true; };
    const cancelDrag = () => { if (dragStart.current) onDraw(dragStart.current); up(); };
    if (activePointer.current === null) return;
    return listenForPointerDrag(canvas, window, activePointer.current, { move, commit: () => up(), cancel: cancelDrag });
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
        if (side === 'back' && anchorFront[index].distanceTo(anchorBack[index]) <= size*1e-7) return null;
        const point = side === 'front' ? anchorFront[index] : anchorBack[index];
        return <SurfaceHandle key={`${side}-${index}`} point={point} selected={selectedPoint === index && selectedSide === side} color="#2f7f55"/>;
      })) : null}
      {editing && selectedPoint !== null && selectedVisible ? (() => {
        const handles = bezierHandles(cut, selectedSide, selectedPoint);
        const anchor = (selectedSide === 'front' ? anchorFront : anchorBack)[selectedPoint];
        if (!anchor) return null;
        return <group>
          <Html position={anchor} style={{ pointerEvents: 'none' }}><button className="secondary" style={{ whiteSpace: 'nowrap', transform: 'translate(-50%, -75px)', background: '#fffdf4', pointerEvents: 'auto' }} onPointerDown={e => e.stopPropagation()} onClick={() => {
            const next = toggleBezier(projector, cut, selectedSide, selectedPoint);
            if (next === cut) onError('A curva não cabe neste segmento. Afaste os pontos ou reduza as alças.');
            else onDraw(next);
          }}>{handles ? 'Tornar ponto reto' : 'Tornar ponto curvo'}</button>{limited ? <small role="status" style={{display:'block',width:190,background:'#fff8e6',padding:6}}>Limite do segmento: reduza o movimento da alça ou afaste os pontos.</small> : null}</Html>
          {handles ? (['in', 'out'] as const).map(kind => {
            if ((kind === 'in' && selectedPoint === 0) || (kind === 'out' && selectedPoint === anchorFront.length - 1)) return null;
            const point = displayHandle(new THREE.Vector3(...handles[kind]), anchor).point;
            return <group key={kind}><Line points={[anchor, point]} color="#cb853c" lineWidth={1} depthTest={false}/>
              <SurfaceHandle point={point} color="#cb853c" selected={false} overlay/>
            </group>;
          }) : null}
        </group>;
      })() : null}

    </> : null}
  </group>;
}




