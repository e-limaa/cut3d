import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js';
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { zipSync, unzipSync, strFromU8 } from 'fflate';

export type Model = { name: string; geometry: THREE.BufferGeometry; dimensions: THREE.Vector3; triangles: number; demo: boolean };
export function prepareModel(geometry: THREE.BufferGeometry, name: string, demo = false): Model {
  const position = geometry.getAttribute('position');
  if (!position || position.count < 3) throw new Error('O arquivo não contém uma superfície 3D.');
  for (let i = 0; i < position.array.length; i++) if (!Number.isFinite(position.array[i])) throw new Error('O modelo contém coordenadas inválidas.');
  geometry.computeBoundingBox();
  const center = geometry.boundingBox!.getCenter(new THREE.Vector3());
  const dimensions = geometry.boundingBox!.getSize(new THREE.Vector3());
  if (dimensions.length() < 0.00001) throw new Error('O modelo não tem dimensões utilizáveis.');
  geometry.translate(-center.x, -center.y, -center.z);
  geometry.computeVertexNormals();
  return { name, geometry, dimensions, triangles: (geometry.index?.count ?? position.count) / 3, demo };
}
export function demoModel(): Model {
  // A single closed study bust: one neck cut can actually release the head,
  // unlike a closed knot which needs two cuts to separate a section.
  const profile = new THREE.CatmullRomCurve3([
    [23, 0], [24, 3], [22, 8], [20, 12], [14, 18], [8, 22],
    [7, 27], [11, 31], [14, 36], [15, 43], [13, 51], [8, 57], [2, 60],
  ].map(([r, z]) => new THREE.Vector3(r, 0, z)), false, 'centripetal');
  const rings = profile.getPoints(80), segments = 64;
  const positions: number[] = [], indices: number[] = [];
  rings.forEach(ring => {
    for (let i = 0; i < segments; i++) {
      const theta = i / segments * Math.PI * 2;
      positions.push(ring.x * Math.cos(theta), ring.x * Math.sin(theta), ring.z);
    }
  });
  for (let row = 0; row < rings.length - 1; row++) for (let i = 0; i < segments; i++) {
    const a = row * segments + i, b = row * segments + (i + 1) % segments, c = a + segments, d = b + segments;
    indices.push(a, b, c, b, d, c);
  }
  const bottom = positions.length / 3; positions.push(0, 0, rings[0].z);
  const top = positions.length / 3; positions.push(0, 0, rings.at(-1)!.z);
  for (let i = 0; i < segments; i++) {
    const next = (i + 1) % segments, last = (rings.length - 1) * segments;
    indices.push(bottom, next, i, last + i, last + next, top);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); geometry.setIndex(indices);
  return prepareModel(geometry, 'Busto de estudo', true);
}
export async function loadModel(file: File): Promise<Model> {
  if (file.size > 150 * 1024 * 1024) throw new Error('Este protótipo aceita arquivos de até 150 MB.');
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (!['stl', '3mf'].includes(extension ?? '')) throw new Error('Escolha um arquivo STL ou 3MF.');
  const buffer = await file.arrayBuffer();
  if (extension === 'stl') return prepareModel(new STLLoader().parse(buffer), file.name);
  // ThreeMFLoader reads the unit attribute but does not apply unit conversion.
  // Mixed-unit assemblies need per-resource conversion, so reject them explicitly.
  const archive = unzipSync(new Uint8Array(buffer));
  const units = new Set(Object.entries(archive).filter(([path]) => /\.model$/i.test(path)).map(([, data]) => {
    const doc = new DOMParser().parseFromString(strFromU8(data), 'application/xml');
    return doc.documentElement.getAttribute('unit') || 'millimeter';
  }));
  const mmPerUnit: Record<string, number> = { micron: .001, millimeter: 1, centimeter: 10, inch: 25.4, foot: 304.8, meter: 1000 };
  const unit = [...units][0];
  if (units.size !== 1 || !mmPerUnit[unit]) throw new Error('Este 3MF usa unidades mistas ou desconhecidas. Exporte uma cópia em milímetros.');
  const group = new ThreeMFLoader().parse(buffer);
  group.scale.multiplyScalar(mmPerUnit[unit]);
  group.updateMatrixWorld(true);
  const geometries: THREE.BufferGeometry[] = [];
  group.traverse(object => {
    if (!(object instanceof THREE.Mesh)) return;
    const source = object.geometry.index ? object.geometry.toNonIndexed() : object.geometry.clone();
    source.applyMatrix4(object.matrixWorld);
    for (const key of Object.keys(source.attributes)) if (key !== 'position') source.deleteAttribute(key);
    geometries.push(source);
  });
  if (!geometries.length) throw new Error('Nenhuma malha foi encontrada no 3MF.');
  const geometry = mergeGeometries(geometries);
  geometries.forEach(g => g.dispose());
  group.traverse(object => { if (object instanceof THREE.Mesh) { object.geometry.dispose(); const materials = Array.isArray(object.material) ? object.material : [object.material]; materials.forEach(m => m.dispose()); } });
  if (!geometry) throw new Error('Não foi possível reunir as partes deste 3MF.');
  return prepareModel(geometry, file.name);
}
export function createPartsArchive(parts: THREE.BufferGeometry[], name: string): Uint8Array {
  const exporter = new STLExporter();
  const stem = name.replace(/\.[^.]+$/, '').replace(/[^\p{L}\p{N}_-]/gu, '_');
  const entries: Record<string, Uint8Array> = {};
  parts.forEach((geometry, index) => {
    const result = exporter.parse(new THREE.Mesh(geometry), { binary: true });
    entries[`${stem}_parte_${String(index + 1).padStart(2, '0')}.stl`] = new Uint8Array(result.buffer as ArrayBuffer, result.byteOffset, result.byteLength);
  });
  return zipSync(entries, { level: 1 });
}
export function downloadParts(parts: THREE.BufferGeometry[], name: string) {
  const stem = name.replace(/\.[^.]+$/, '').replace(/[^\p{L}\p{N}_-]/gu, '_');
  const zip = createPartsArchive(parts, name);
  const url = URL.createObjectURL(new Blob([zip as Uint8Array<ArrayBuffer>], { type: 'application/zip' }));
  const link = document.createElement('a');
  link.href = url; link.download = `${stem}_pecas.zip`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
