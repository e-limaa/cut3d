import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { splitGeometry, GeometrySplitError } from './client';

function triangleVolume(positions: Float32Array, indices: Uint32Array): number {
  let volume = 0;
  for (let triangle = 0; triangle < indices.length; triangle += 3) {
    const a = indices[triangle] * 3;
    const b = indices[triangle + 1] * 3;
    const c = indices[triangle + 2] * 3;
    volume +=
      positions[a] * (positions[b + 1] * positions[c + 2] - positions[b + 2] * positions[c + 1]) -
      positions[a + 1] * (positions[b] * positions[c + 2] - positions[b + 2] * positions[c]) +
      positions[a + 2] * (positions[b] * positions[c + 1] - positions[b + 1] * positions[c]);
  }
  return Math.abs(volume) / 6;
}

function geometryVolume(geometry: THREE.BufferGeometry): number {
  const position = geometry.getAttribute('position');
  const index = geometry.getIndex();
  if (!index) throw new Error('test geometry must be indexed');
  const positions = new Float32Array(position.count * 3);
  for (let vertex = 0; vertex < position.count; vertex += 1) {
    positions[vertex * 3] = position.getX(vertex);
    positions[vertex * 3 + 1] = position.getY(vertex);
    positions[vertex * 3 + 2] = position.getZ(vertex);
  }
  const indices = new Uint32Array(index.count);
  for (let item = 0; item < index.count; item += 1) indices[item] = index.getX(item);
  return triangleVolume(positions, indices);
}

describe('planar manifold split', () => {
  it('conserves volume when a closed cube is split through its centre', async () => {
    const source = new THREE.BoxGeometry(2, 2, 2);
    const outputs = await splitGeometry(source, [0, 0, 2], 0);

    expect(outputs).toHaveLength(2);
    expect(outputs.every((geometry) => geometry.getIndex() && geometry.getAttribute('position'))).toBe(true);
    const volumes = outputs.map(geometryVolume);
    expect(volumes[0]).toBeCloseTo(4, 4);
    expect(volumes[1]).toBeCloseTo(4, 4);
    expect(volumes[0] + volumes[1]).toBeCloseTo(geometryVolume(source), 4);

    source.dispose();
    outputs.forEach((geometry) => geometry.dispose());
  });

  it('welds a non-indexed STL-style cube before cutting', async () => {
    const source = new THREE.BoxGeometry(2, 2, 2).toNonIndexed();
    const outputs = await splitGeometry(source, [1, 0, 0], 0);

    expect(outputs).toHaveLength(2);
    expect(outputs.map(geometryVolume).reduce((sum, value) => sum + value, 0)).toBeCloseTo(8, 4);
    source.dispose();
    outputs.forEach((geometry) => geometry.dispose());
  });

  it('rejects a plane that misses the solid', async () => {
    const source = new THREE.BoxGeometry(2, 2, 2);

    await expect(splitGeometry(source, [0, 0, 1], 2)).rejects.toMatchObject({
      code: 'plane-miss',
    });
    source.dispose();
  });

  it('rejects an open, non-manifold input mesh', async () => {
    const source = new THREE.BufferGeometry();
    source.setAttribute(
      'position',
      new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3),
    );

    await expect(splitGeometry(source, [0, 0, 1], 0)).rejects.toMatchObject({
      code: 'non-manifold',
    });
    source.dispose();
  });
});
