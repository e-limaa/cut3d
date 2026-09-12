import { describe, it, expect } from 'vitest';
import * as THREE from 'three';
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { unzipSync } from 'fflate';
import { createPartsArchive, demoModel, loadModel } from './model';
import { splitGeometry } from './geometry/client';

function assertClosed(geometry: THREE.BufferGeometry) {
  const index = geometry.getIndex()!;
  const edges = new Map<string, number>();
  for (let face = 0; face < index.count; face += 3) {
    for (let corner = 0; corner < 3; corner++) {
      const a = index.getX(face + corner), b = index.getX(face + (corner + 1) % 3);
      const key = a < b ? `${a}:${b}` : `${b}:${a}`;
      edges.set(key, (edges.get(key) ?? 0) + 1);
    }
  }
  expect([...edges.values()].every(count => count === 2)).toBe(true);
}
describe('model integration', () => {
  it('cuts the actual studio demonstration, closes outputs and preserves the original', async () => {
    const model = demoModel();
    const before = new Float32Array(model.geometry.getAttribute('position').array);
    const outputs = await splitGeometry(model.geometry, [0, 0, 1], 0);
    expect(outputs.length).toBeGreaterThanOrEqual(2);
    outputs.forEach(assertClosed);
    expect(model.geometry.getAttribute('position').array).toEqual(before);
    model.geometry.dispose(); outputs.forEach(part => part.dispose());
  });
  it('imports binary STL, cuts it and exports STL parts with the same physical dimensions', async () => {
    const source = new THREE.BoxGeometry(20, 30, 40);
    const binary = new STLExporter().parse(new THREE.Mesh(source), { binary: true });
    const file = new File([binary.buffer as ArrayBuffer], 'cube.stl');
    const model = await loadModel(file);
    expect(model.dimensions.toArray()).toEqual([20, 30, 40]);
    const outputs = await splitGeometry(model.geometry, [0, 0, 1], 0);
    const archive = unzipSync(createPartsArchive(outputs, model.name));
    expect(Object.keys(archive)).toEqual(['cube_parte_01.stl', 'cube_parte_02.stl']);
    for (const data of Object.values(archive)) {
      const geometry = new STLLoader().parse(data.slice().buffer as ArrayBuffer);
      geometry.computeBoundingBox();
      expect(geometry.boundingBox!.getSize(new THREE.Vector3()).toArray()).toEqual([20, 30, 20]);
      geometry.dispose();
    }
    source.dispose(); model.geometry.dispose(); outputs.forEach(part => part.dispose());
  });
  it('does not mistake already disconnected parts for a new cut', async () => {
    const left = new THREE.BoxGeometry(2, 2, 2).translate(-4, 0, 0);
    const right = new THREE.BoxGeometry(2, 2, 2).translate(4, 0, 0);
    const source = mergeGeometries([left, right]);
    await expect(splitGeometry(source, [1, 0, 0], 0)).rejects.toMatchObject({ code: 'plane-miss' });
    source.dispose(); left.dispose(); right.dispose();
  });
});
