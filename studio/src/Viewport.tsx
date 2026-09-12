import { Suspense, useEffect, useMemo, type ReactNode } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Grid, GizmoHelper, GizmoViewport, Line } from '@react-three/drei';
import * as THREE from 'three';
import type { Model } from './model';

const colors = ['#96baa5', '#d5b690', '#8da9bb', '#cba2a3', '#b7b18c', '#a8a0c6'];
function CameraFit({ size, reset }: { size: number; reset: number }) {
  const { camera, controls, invalidate, size: canvasSize } = useThree();
  useEffect(() => {
    camera.up.set(0, 0, 1);
    camera.position.set(size * 1.25, -size * 1.8, size * 1.05);
    camera.near = Math.max(size / 1000, 0.0001); camera.far = size * 100;
    if (camera instanceof THREE.PerspectiveCamera) camera.updateProjectionMatrix();
    if (camera instanceof THREE.OrthographicCamera) { camera.zoom = Math.min(canvasSize.width, canvasSize.height) / (size * 2.1); camera.updateProjectionMatrix(); }
    camera.lookAt(0, 0, 0);
    const orbit = controls as unknown as { target: THREE.Vector3; update: () => void } | null;
    orbit?.target.set(0, 0, 0); orbit?.update(); invalidate();
  }, [camera, controls, size, reset, invalidate, canvasSize.width, canvasSize.height]);
  return null;
}
function CutPlane({ normal, offset, size }: { normal: THREE.Vector3; offset: number; size: number }) {
  const quaternion = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal), [normal]);
  const half = size * 0.63;
  return <group position={normal.clone().multiplyScalar(offset)} quaternion={quaternion}>
    <mesh renderOrder={2}><planeGeometry args={[half * 2, half * 2]} /><meshBasicMaterial color="#a6e7c0" opacity={0.2} transparent side={THREE.DoubleSide} depthWrite={false} /></mesh>
    <Line points={[[-half, -half, 0], [half, -half, 0], [half, half, 0], [-half, half, 0], [-half, -half, 0]]} color="#61b789" lineWidth={1.5} />
    <Line points={[[0, 0, 0], [0, 0, size * 0.19]]} color="#448a62" lineWidth={2} />
    <mesh position={[0, 0, size * 0.19]} rotation={[Math.PI / 2, 0, 0]}><coneGeometry args={[size * 0.014, size * 0.05, 12]} /><meshBasicMaterial color="#448a62" /></mesh>
  </group>;
}
export default function Viewport({ model, normal, offset, parts, exploded, showPlane, reset, wireframe, selected, children }: { model: Model; normal: THREE.Vector3; offset: number; parts: THREE.BufferGeometry[]; exploded: number; showPlane: boolean; reset: number; wireframe: boolean; selected: number | null; children?: ReactNode }) {
  const size = Math.max(model.dimensions.x, model.dimensions.y, model.dimensions.z);
  const offsets = useMemo(() => parts.map((geometry, index) => {
    geometry.computeBoundingBox();
    const center = geometry.boundingBox!.getCenter(new THREE.Vector3());
    const sign = center.dot(normal) >= offset ? 1 : -1;
    if (center.length() < size * .001) center.copy(normal).multiplyScalar(sign);
    return center.normalize().multiplyScalar(size * exploded * .45);
  }), [parts, normal, offset, size, exploded]);
  return <Canvas orthographic frameloop="demand" dpr={[1, 1.75]} camera={{ up: [0, 0, 1] }} gl={{ antialias: true, preserveDrawingBuffer: true }}>
    <color attach="background" args={['#eeefeb']} />
    <ambientLight intensity={1.35} />
    <directionalLight position={[size, -size, size * 2]} intensity={3.2} />
    <directionalLight position={[-size, size, size]} intensity={1.3} color="#e0eadf" />
    <Suspense fallback={null}>
      {parts.length ? parts.map((geometry, index) => <mesh key={geometry.uuid} geometry={geometry} position={offsets[index]}>
        <meshStandardMaterial color={colors[index % colors.length]} roughness={0.65} metalness={0.08} wireframe={wireframe} transparent={selected !== null && selected !== index} opacity={selected !== null && selected !== index ? .16 : 1} />
      </mesh>) : <mesh geometry={model.geometry}><meshStandardMaterial color="#cfcec2" roughness={.57} metalness={.1} wireframe={wireframe} /></mesh>}
      {showPlane && !parts.length ? <CutPlane normal={normal} offset={offset} size={size} /> : null}
      <Grid position={[0, 0, -model.dimensions.z / 2 - size * .035]} rotation={[Math.PI / 2, 0, 0]} args={[size * 8, size * 8]} cellSize={size / 10} sectionSize={size / 2} cellColor="#bac2b8" sectionColor="#9ca999" cellThickness={.5} sectionThickness={.8} fadeDistance={size * 6} infiniteGrid />
      <OrbitControls makeDefault enableDamping={false} minDistance={size * .12} maxDistance={size * 12} />
      {children}
      <CameraFit size={size} reset={reset} />
      <GizmoHelper alignment="bottom-right" margin={[58, 65]}><GizmoViewport axisColors={['#bd766a', '#789e78', '#7e9caf']} labelColor="#fff" hideNegativeAxes /></GizmoHelper>
    </Suspense>
  </Canvas>;
}
