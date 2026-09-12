import { useEffect, useMemo } from 'react';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import type { PlannedCut } from './geometry/multiCut';
import { freeCutPoint } from './strokeMath';
import ConnectorPreview from './ConnectorPreview';

/** Passive previews never register drawing handlers or change camera controls. */
export default function PlannedCutPreview({ cut, size }: { cut: PlannedCut; size: number }) {
  const free = cut.freeCut;
  const { front, back, surface } = useMemo(() => {
    const front = free?.rails?.front ?? free?.points.map(point => freeCutPoint(free, point, free.depthMax)) ?? [];
    const back = free?.rails?.back ?? free?.points.map(point => freeCutPoint(free, point, free.depthMin)) ?? [];
    const vertices: number[] = [];
    for (let i = 0; i < front.length - 1; i++) {
      for (const point of [front[i], back[i], front[i + 1], front[i + 1], back[i], back[i + 1]]) vertices.push(...point);
    }
    const surface = new THREE.BufferGeometry();
    surface.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    return { front, back, surface };
  }, [free]);
  useEffect(() => () => surface.dispose(), [surface]);
  if (cut.mode === 'PLANE') {
    const normal = new THREE.Vector3(0, 0, 1).applyEuler(new THREE.Euler(cut.tilt * Math.PI / 180, cut.turn * Math.PI / 180, 0));
    return <mesh position={normal.clone().multiplyScalar(cut.offset)} quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal)} renderOrder={3}>
      <planeGeometry args={[size * 1.26, size * 1.26]}/><meshBasicMaterial color="#7fba9d" transparent opacity={.18} depthTest={false} depthWrite={false} side={THREE.DoubleSide}/>
    </mesh>;
  }
  if (!free || front.length < 2) return null;
  return <group>
    <mesh geometry={surface} renderOrder={3}><meshBasicMaterial color="#7fba9d" transparent opacity={.22} depthTest={false} depthWrite={false} side={THREE.DoubleSide}/></mesh>
    <Line points={front} color="#658e78" lineWidth={1.5} depthTest={false} renderOrder={4}/>
    <Line points={back} color="#658e78" lineWidth={1.5} dashed dashSize={size * .015} gapSize={size * .01} depthTest={false} renderOrder={4}/>
    <ConnectorPreview cut={free}/>
  </group>;
}
