import * as THREE from 'three';
import type { FreeCut } from '../freeCut';
import { GeometrySplitError, splitFreeGeometry, splitGeometry } from './client';
import { getConnectorFrame } from './connectorFrame';

export type PlannedCut = {
  id: string;
  mode: 'FREE' | 'PLANE';
  freeCut: FreeCut | null;
  offset: number;
  tilt: number;
  turn: number;
};

const noSplitCodes = new Set(['plane-miss', 'free-cut-miss', 'insufficient-depth', 'insufficient-separation']);

/** Solid-angle containment works on indexed and triangle-soup closed meshes. */
function containsPoint(geometry: THREE.BufferGeometry, point: THREE.Vector3): boolean {
  const position = geometry.getAttribute('position'), index = geometry.getIndex();
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const cross = new THREE.Vector3();
  let angle = 0;
  for (let i = 0; i < (index?.count ?? position.count); i += 3) {
    a.fromBufferAttribute(position, index ? index.getX(i) : i).sub(point);
    b.fromBufferAttribute(position, index ? index.getX(i + 1) : i + 1).sub(point);
    c.fromBufferAttribute(position, index ? index.getX(i + 2) : i + 2).sub(point);
    const al = a.length(), bl = b.length(), cl = c.length();
    angle += 2 * Math.atan2(a.dot(cross.crossVectors(b, c)), al * bl * cl + a.dot(b) * cl + b.dot(c) * al + c.dot(a) * bl);
  }
  return Math.abs(angle) > Math.PI * 2;
}

/** Applies world-space cuts in order. The caller owns the returned geometries. */
export async function buildCutPlan(
  geometry: THREE.BufferGeometry,
  cuts: PlannedCut[],
  onProgress?: (index: number, total: number) => void,
): Promise<THREE.BufferGeometry[]> {
  let parts = [geometry.clone()];
  const owned = new Set(parts);
  const release = (part: THREE.BufferGeometry) => { owned.delete(part); part.dispose(); };
  try {
    for (let cutIndex = 0; cutIndex < cuts.length; cutIndex += 1) {
      try {
        const cut = cuts[cutIndex];
        if (cut.mode !== 'PLANE' && cut.mode !== 'FREE') throw new GeometrySplitError('invalid-input', 'O tipo de corte é inválido.');
        if (cut.mode === 'FREE' && !cut.freeCut) throw new GeometrySplitError('invalid-free-cut', 'Desenhe o traço antes de construir este corte.');
        const normal = new THREE.Vector3(0, 0, 1).applyEuler(new THREE.Euler(cut.tilt * Math.PI / 180, cut.turn * Math.PI / 180, 0));
        const freeCut = cut.freeCut;
        const needsConnector = cut.mode === 'FREE' && !!freeCut?.connector?.enabled;
        const results: { source: THREE.BufferGeometry; outputs: THREE.BufferGeometry[]; split: boolean }[] = [];
        let lastMiss: GeometrySplitError | undefined;
        for (const part of parts) {
          try {
            const outputs = cut.mode === 'PLANE'
              ? await splitGeometry(part, normal.toArray(), cut.offset)
              : await splitFreeGeometry(part, needsConnector ? { ...freeCut!, connector: undefined } : freeCut!);
            outputs.forEach(output => owned.add(output));
            if (outputs.length < 2) throw new GeometrySplitError('engine', 'O motor não retornou peças separadas.');
            results.push({ source: part, outputs, split: true });
          } catch (error) {
            if (!(error instanceof GeometrySplitError) || !noSplitCodes.has(error.code)) throw error;
            lastMiss = error;
            results.push({ source: part, outputs: [part], split: false });
          }
        }
        if (!results.some(result => result.split)) {
          throw lastMiss ?? new GeometrySplitError('invalid-input', 'Este corte não separou nenhuma peça.');
        }
        if (needsConnector) {
          let center: THREE.Vector3;
          try { center = new THREE.Vector3(...getConnectorFrame(freeCut!).center); }
          catch { throw new GeometrySplitError('invalid-free-cut', 'A posição do encaixe é inválida.'); }
          const candidates = results.filter(result => result.split && containsPoint(result.source, center));
          if (candidates.length !== 1) throw new GeometrySplitError('invalid-free-cut', 'O encaixe precisa ficar dentro de uma única peça atravessada por este corte. Mova-o para longe dos cortes anteriores.');
          const target = candidates[0];
          // Exact fit, connector parameter validation and paired socket creation stay in the engine.
          const connected = await splitFreeGeometry(target.source, freeCut!);
          connected.forEach(output => owned.add(output));
          target.outputs.forEach(release);
          target.outputs = connected;
        }
        const next = results.flatMap(result => result.outputs);
        const retained = new Set(next);
        parts.forEach(part => { if (!retained.has(part)) release(part); });
        parts = next;
        onProgress?.(cutIndex + 1, cuts.length);
      } catch (error) {
        const code = error instanceof GeometrySplitError ? error.code : 'engine';
        const message = error instanceof Error ? error.message : 'Falha no processamento geométrico.';
        throw new GeometrySplitError(code, `Corte ${cutIndex + 1}: ${message}`);
      }
    }
    return parts;
  } catch (error) {
    owned.forEach(part => part.dispose());
    throw error;
  }
}
