import { useMemo } from 'react';
import * as THREE from 'three';
import { getConnectorFrame } from './geometry/connectorFrame';
import type { FreeCut } from './freeCut';

export default function ConnectorPreview({ cut }: { cut: FreeCut }) {
  const connector = cut.connector;
  const frame = useMemo(() => getConnectorFrame(cut), [cut]);
  if (!connector?.enabled) return null;
  const axis = new THREE.Vector3(...frame.normal).multiplyScalar(connector.side);
  if (axis.lengthSq() < .1) return null;
  const tangent = new THREE.Vector3(...frame.tangent);
  const orientation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(tangent, new THREE.Vector3().crossVectors(axis, tangent), axis));
  const segments = connector.shape === 'hexagon' ? 6 : 48;
  const length = connector.length + cut.kerf;
  const shape = (diameter: number, height: number) => ['square','rectangle'].includes(connector.shape)
    ? <boxGeometry args={[diameter, connector.shape==='rectangle' ? (connector.thickness??connector.diameter/2)+(diameter-connector.diameter) : diameter, height]}/>
    : <cylinderGeometry args={[connector.shape === 'hexagon' ? Math.min(diameter, connector.tipDiameter ?? diameter * .7) / 2 : diameter / 2, diameter / 2, height, segments]}/>;
  return <group position={frame.center} quaternion={orientation}>
    <mesh position={[0, 0, connector.length / 2]} rotation={['square','rectangle'].includes(connector.shape) ? [0, 0, 0] : [Math.PI / 2, Math.PI / 2, 0]} renderOrder={9}>
      {shape(connector.diameter, length)}<meshBasicMaterial color="#d5aa56" transparent opacity={.8} depthTest={false} depthWrite={false}/>
    </mesh>
  </group>;
}
