import * as THREE from 'three';

import type { FreeCut } from '../freeCut';
import { GeometrySplitError, type PlaneNormal, type FreeCutWorkerRequest, type SplitWorkerRequest, type SplitWorkerResponse } from './types';
export { GeometrySplitError } from './types';
export type { PlaneNormal } from './types';
export type { FreeCut } from '../freeCut';

function geometryToInput(geometry: THREE.BufferGeometry) {
  const position = geometry.getAttribute('position');
  if (!position || position.itemSize < 3) {
    throw new GeometrySplitError('invalid-input', 'A geometria precisa ter um atributo de posição XYZ.');
  }
  if (position.count === 0) {
    throw new GeometrySplitError('invalid-input', 'A geometria não contém triângulos.');
  }

  const positions = new Float32Array(position.count * 3);
  for (let vertex = 0; vertex < position.count; vertex += 1) {
    positions[vertex * 3] = position.getX(vertex);
    positions[vertex * 3 + 1] = position.getY(vertex);
    positions[vertex * 3 + 2] = position.getZ(vertex);
  }

  const index = geometry.getIndex();
  if (index) {
    const indices = new Uint32Array(index.count);
    for (let item = 0; item < index.count; item += 1) indices[item] = index.getX(item);
    return { positions, indices, weld: false as const };
  }

  if (position.count % 3 !== 0) {
    throw new GeometrySplitError('invalid-input', 'A geometria não indexada precisa conter triângulos completos.');
  }
  const indices = new Uint32Array(position.count);
  indices.forEach((_, indexValue) => {
    indices[indexValue] = indexValue;
  });
  return { positions, indices, weld: true as const };
}

function outputToGeometry(output: { positions: Float32Array; indices: Uint32Array }): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(output.positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(output.indices, 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

/**
 * Splits a closed solid by the plane dot(normal, position) = offset.
 * Each disconnected solid produced on either side is returned separately.
 */
export async function splitGeometry(
  geometry: THREE.BufferGeometry,
  normal: PlaneNormal,
  offset: number,
): Promise<THREE.BufferGeometry[]> {
  const input = geometryToInput(geometry);
  if (typeof Worker === 'undefined') {
    const { splitGeometryData } = await import('./engine');
    const outputs = await splitGeometryData(input, normal, offset);
    return outputs.map(outputToGeometry);
  }

  return new Promise<THREE.BufferGeometry[]>((resolve, reject) => {
    const worker = new Worker(new URL('./split.worker.ts', import.meta.url), { type: 'module' });
    let settled = false;
    const cleanup = () => {
      worker.onmessage = null;
      worker.onerror = null;
      worker.terminate();
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error instanceof GeometrySplitError ? error : new GeometrySplitError('engine', 'O processamento geométrico falhou.'));
    };
    worker.onmessage = (event: MessageEvent<SplitWorkerResponse>) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (event.data.type === 'error') {
        reject(new GeometrySplitError(event.data.code, event.data.message));
        return;
      }
      resolve(event.data.outputs.map(outputToGeometry));
    };
    worker.onerror = (event) => {
      event.preventDefault();
      fail(new GeometrySplitError('engine', 'Não foi possível executar o corte geométrico em segundo plano.'));
    };

    const request: SplitWorkerRequest = { type: 'split', input, normal, offset };
    worker.postMessage(request, [input.positions.buffer, input.indices.buffer]);
  });
}

/**
 * Applies a finite-depth swept blade along an arbitrary open 2D stroke.
 * The source geometry is read only and remains untouched if the cut fails.
 */
export async function splitFreeGeometry(
  geometry: THREE.BufferGeometry,
  cut: FreeCut,
): Promise<THREE.BufferGeometry[]> {
  const input = geometryToInput(geometry);
  if (typeof Worker === 'undefined') {
    const { splitFreeGeometryData } = await import('./engine');
    const outputs = await splitFreeGeometryData(input, cut);
    return outputs.map(outputToGeometry);
  }

  return new Promise<THREE.BufferGeometry[]>((resolve, reject) => {
    const worker = new Worker(new URL('./split.worker.ts', import.meta.url), { type: 'module' });
    let settled = false;
    const cleanup = () => {
      worker.onmessage = null;
      worker.onerror = null;
      worker.terminate();
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error instanceof GeometrySplitError ? error : new GeometrySplitError('engine', 'O processamento geométrico falhou.'));
    };
    worker.onmessage = (event: MessageEvent<SplitWorkerResponse>) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (event.data.type === 'error') {
        reject(new GeometrySplitError(event.data.code, event.data.message));
        return;
      }
      resolve(event.data.outputs.map(outputToGeometry));
    };
    worker.onerror = (event) => {
      event.preventDefault();
      fail(new GeometrySplitError('engine', 'Não foi possível executar o corte geométrico em segundo plano.'));
    };

    const request: FreeCutWorkerRequest = { type: 'free-cut', input, cut };
    worker.postMessage(request, [input.positions.buffer, input.indices.buffer]);
  });
}

export default splitGeometry;
