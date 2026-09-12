import ManifoldModule from 'manifold-3d';

import {
  GeometrySplitError,
  type PlaneNormal,
  type SplitInputData,
  type SplitOutputData,
} from './types';
import type { FreeCut } from '../freeCut';
import { ruledSheet } from './ruledSheet';
import { getConnectorFrame, add, scale, cross } from './connectorFrame';

type Vec3 = [number, number, number];
type Vec2 = [number, number];
type Mat4 = [
  number, number, number, number,
  number, number, number, number,
  number, number, number, number,
  number, number, number, number,
];

interface ManifoldMeshLike {
  numProp: number;
  numVert: number;
  triVerts: Uint32Array;
  vertProperties: Float32Array;
  runIndex: Uint32Array;
  runOriginalID: Uint32Array;
  merge(): boolean;
}

interface ManifoldLike {
  getMesh(): ManifoldMeshLike;
  splitByPlane(normal: PlaneNormal, offset: number): [ManifoldLike, ManifoldLike];
  subtract(other: ManifoldLike): ManifoldLike;
  add(other: ManifoldLike): ManifoldLike;
  intersect(other: ManifoldLike): ManifoldLike;
  translate(v: Readonly<Vec3>): ManifoldLike;
  transform(matrix: Mat4): ManifoldLike;
  decompose(): ManifoldLike[];
  status(): unknown;
  isEmpty(): boolean;
  numTri(): number;
  volume(): number;
  delete(): void;
}

interface WasmLike {
  setup(): void;
  Mesh: new (options: {
    numProp: number;
    triVerts: Uint32Array;
    vertProperties: Float32Array;
    runIndex: Uint32Array;
    runOriginalID: Uint32Array;
  }) => ManifoldMeshLike;
  Manifold: {
    new (mesh: ManifoldMeshLike): ManifoldLike;
    extrude(
      section: CrossSectionLike,
      height: number,
      nDivisions?: number,
      twistDegrees?: number,
      scaleTop?: Readonly<Vec2> | number,
      center?: boolean,
    ): ManifoldLike;
  };
  CrossSection: {
    square(size?: Readonly<Vec2> | number, center?: boolean): CrossSectionLike;
    circle(radius: number, circularSegments?: number): CrossSectionLike;
    union(sections: readonly CrossSectionLike[]): CrossSectionLike;
  };
}

interface CrossSectionLike {
  rotate(degrees: number): CrossSectionLike;
  translate(v: Readonly<Vec2>): CrossSectionLike;
  translate(x: number, y?: number): CrossSectionLike;
  numVert(): number;
  delete(): void;
}

let wasmPromise: Promise<WasmLike> | undefined;

/**
 * Initializes Manifold exactly once per worker/global runtime.
 * Manifold objects are WASM allocations, so callers below explicitly delete them.
 */
async function getWasm(): Promise<WasmLike> {
  wasmPromise ??= (async () => {
    const wasm = (await ManifoldModule()) as unknown as WasmLike;
    wasm.setup();
    return wasm;
  })();
  return wasmPromise;
}

function statusName(status: unknown): string {
  if (typeof status === 'string') return status;
  if (status && typeof status === 'object' && 'value' in status) {
    return String((status as { value: unknown }).value);
  }
  return String(status);
}

function errorCodeForStatus(status: string): 'non-manifold' | 'invalid-input' {
  if (/notmanifold|nonfinite|vertexoutofbounds|properties|missingposition|merge|invalid/i.test(status)) {
    return /notmanifold/i.test(status) ? 'non-manifold' : 'invalid-input';
  }
  return 'invalid-input';
}

function readableManifoldError(error: unknown): GeometrySplitError {
  const code =
    error && typeof error === 'object' && 'code' in error
      ? String((error as { code: unknown }).code)
      : '';
  const message = error instanceof Error ? error.message : String(error);
  if (/notmanifold/i.test(code) || /not manifold/i.test(message)) {
    return new GeometrySplitError(
      'non-manifold',
      'A malha não é um sólido fechado (2-manifold). Verifique bordas abertas, faces duplicadas e normais.',
    );
  }
  if (/nonfinite|outofbounds|properties|invalid/i.test(code)) {
    return new GeometrySplitError(
      'invalid-input',
      'A malha contém dados inválidos para o corte (vértices, índices ou propriedades).',
    );
  }
  return new GeometrySplitError(
    'engine',
    `Não foi possível processar a malha: ${message || 'erro desconhecido do motor geométrico.'}`,
  );
}

function validateInput(input: SplitInputData): void {
  if (!(input.positions instanceof Float32Array) || input.positions.length === 0 || input.positions.length % 3 !== 0) {
    throw new GeometrySplitError('invalid-input', 'A malha precisa de uma posição XYZ válida.');
  }
  if (!(input.indices instanceof Uint32Array) || input.indices.length === 0 || input.indices.length % 3 !== 0) {
    throw new GeometrySplitError('invalid-input', 'A malha precisa conter triângulos válidos.');
  }

  for (const value of input.positions) {
    if (!Number.isFinite(value)) {
      throw new GeometrySplitError('invalid-input', 'A malha contém um vértice não finito.');
    }
  }
  const vertexCount = input.positions.length / 3;
  for (const index of input.indices) {
    if (index >= vertexCount) {
      throw new GeometrySplitError('invalid-input', 'A malha contém um índice de triângulo fora dos limites.');
    }
  }

  let maxExtent = 0;
  for (let axis = 0; axis < 3; axis += 1) {
    let min = Infinity;
    let max = -Infinity;
    for (let vertex = 0; vertex < vertexCount; vertex += 1) {
      const value = input.positions[vertex * 3 + axis];
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    maxExtent = Math.max(maxExtent, max - min);
  }
  const areaTolerance = Math.max(maxExtent * maxExtent * 1e-24, 1e-30);
  for (let triangle = 0; triangle < input.indices.length; triangle += 3) {
    const a = input.indices[triangle] * 3;
    const b = input.indices[triangle + 1] * 3;
    const c = input.indices[triangle + 2] * 3;
    const abx = input.positions[b] - input.positions[a];
    const aby = input.positions[b + 1] - input.positions[a + 1];
    const abz = input.positions[b + 2] - input.positions[a + 2];
    const acx = input.positions[c] - input.positions[a];
    const acy = input.positions[c + 1] - input.positions[a + 1];
    const acz = input.positions[c + 2] - input.positions[a + 2];
    const crossX = aby * acz - abz * acy;
    const crossY = abz * acx - abx * acz;
    const crossZ = abx * acy - aby * acx;
    if (crossX * crossX + crossY * crossY + crossZ * crossZ <= areaTolerance) {
      throw new GeometrySplitError('invalid-input', 'A malha contém um triângulo degenerado.');
    }
  }
}

function normalizePlane(normal: PlaneNormal, offset: number): { normal: PlaneNormal; offset: number } {
  const [x, y, z] = normal;
  const length = Math.hypot(x, y, z);
  if (![x, y, z, offset].every(Number.isFinite) || length <= Number.EPSILON) {
    throw new GeometrySplitError('invalid-plane', 'O plano precisa de uma normal finita e não nula e de um deslocamento finito.');
  }
  return { normal: [x / length, y / length, z / length], offset: offset / length };
}

interface InputBounds {
  min: Vec3;
  max: Vec3;
  maxExtent: number;
}

function inputBounds(input: SplitInputData): InputBounds {
  const vertexCount = input.positions.length / 3;
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = input.positions[vertex * 3 + axis];
      min[axis] = Math.min(min[axis], value);
      max[axis] = Math.max(max[axis], value);
    }
  }
  return {
    min,
    max,
    maxExtent: Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]),
  };
}

const MAX_FREE_CUT_POINTS = 2048;

interface ValidatedFreeCut {
  points: Vec2[];
  origin: Vec3;
  u: Vec3;
  v: Vec3;
  w: Vec3;
  depthMin: number;
  depthMax: number;
  kerf: number;
  safeEpsilon: number;
}

function finiteVector(values: readonly number[], name: string): void {
  if (!Array.isArray(values) || values.length !== 3 || values.some((value) => !Number.isFinite(value))) {
    throw new GeometrySplitError('invalid-free-cut', `A base ${name} precisa ter três valores finitos.`);
  }
}

function validatedFreeCut(input: SplitInputData, cut: FreeCut): ValidatedFreeCut {
  if (!cut || !Array.isArray(cut.points)) {
    throw new GeometrySplitError('invalid-free-cut', 'O corte livre precisa conter uma trajetória 2D.');
  }
  if (cut.points.length < 2 || cut.points.length > MAX_FREE_CUT_POINTS) {
    throw new GeometrySplitError(
      'invalid-free-cut',
      `A trajetória precisa ter entre 2 e ${MAX_FREE_CUT_POINTS} pontos.`,
    );
  }

  const bounds = inputBounds(input);
  // Manifold's geometric tolerance is scale-dependent. Keep the minimum kerf
  // above that tolerance so the swept volume cannot collapse into a surface.
  const safeEpsilon = Math.max(bounds.maxExtent * 1e-9, 1e-8);
  const basis = { origin: cut.origin, u: cut.u, v: cut.v, w: cut.w };
  finiteVector(basis.origin, 'origem');
  finiteVector(basis.u, 'u');
  finiteVector(basis.v, 'v');
  finiteVector(basis.w, 'w');
  for (const point of cut.points) {
    if (!Array.isArray(point) || point.length !== 2 || point.some((value) => !Number.isFinite(value))) {
      throw new GeometrySplitError('invalid-free-cut', 'A trajetória contém um ponto 2D inválido.');
    }
  }
  const [ux, uy, uz] = cut.u;
  const [vx, vy, vz] = cut.v;
  const [wx, wy, wz] = cut.w;
  const uLength = Math.hypot(ux, uy, uz);
  const vLength = Math.hypot(vx, vy, vz);
  const wLength = Math.hypot(wx, wy, wz);
  const basisTolerance = 2e-4;
  const dotUV = ux * vx + uy * vy + uz * vz;
  const dotUW = ux * wx + uy * wy + uz * wz;
  const dotVW = vx * wx + vy * wy + vz * wz;
  const cross: Vec3 = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
  const crossLength = Math.hypot(cross[0], cross[1], cross[2]);
  const crossError = Math.hypot(cross[0] - wx, cross[1] - wy, cross[2] - wz);
  if (
    Math.abs(uLength - 1) > basisTolerance ||
    Math.abs(vLength - 1) > basisTolerance ||
    Math.abs(wLength - 1) > basisTolerance ||
    Math.abs(dotUV) > basisTolerance ||
    Math.abs(dotUW) > basisTolerance ||
    Math.abs(dotVW) > basisTolerance ||
    Math.abs(crossLength - 1) > basisTolerance ||
    crossError > basisTolerance
  ) {
    throw new GeometrySplitError(
      'invalid-free-cut',
      'A base do corte precisa ser ortonormal e obedecer u × v = w.',
    );
  }

  if (![cut.depthMin, cut.depthMax, cut.kerf].every(Number.isFinite)) {
    throw new GeometrySplitError('invalid-free-cut', 'Profundidade e espessura precisam ser finitas.');
  }
  if (cut.depthMax - cut.depthMin <= safeEpsilon) {
    throw new GeometrySplitError('invalid-free-cut', 'A profundidade do corte precisa ser positiva.');
  }
  if (cut.kerf < safeEpsilon) {
    throw new GeometrySplitError('invalid-free-cut', 'A espessura do corte é pequena demais para esta escala.');
  }

  const pointTolerance = Math.max(safeEpsilon, cut.kerf * 1e-6);
  const points: Vec2[] = [];
  for (const point of cut.points) {
    const next: Vec2 = [point[0], point[1]];
    const previous = points[points.length - 1];
    if (!previous || Math.hypot(next[0] - previous[0], next[1] - previous[1]) > pointTolerance) {
      points.push(next);
    }
  }
  if (points.length < 2) {
    throw new GeometrySplitError('invalid-free-cut', 'A trajetória precisa avançar por uma distância positiva.');
  }
  const first = points[0];
  const last = points[points.length - 1];
  if (Math.hypot(last[0] - first[0], last[1] - first[1]) <= pointTolerance) {
    throw new GeometrySplitError('invalid-free-cut', 'A trajetória deve ser aberta, com início e fim distintos.');
  }

  // Use a clean orthonormal frame for the transform after validating the
  // caller's frame. This avoids accumulating tiny basis errors in the WASM
  // transform while still rejecting a genuinely skewed frame above.
  const normalized = (vector: readonly number[], length: number): Vec3 => [
    vector[0] / length,
    vector[1] / length,
    vector[2] / length,
  ];
  return {
    points,
    origin: [cut.origin[0], cut.origin[1], cut.origin[2]],
    u: normalized(cut.u, uLength),
    v: normalized(cut.v, vLength),
    w: normalized(cut.w, wLength),
    depthMin: cut.depthMin,
    depthMax: cut.depthMax,
    kerf: cut.kerf,
    safeEpsilon,
  };
}

function toOutput(mesh: ManifoldMeshLike): SplitOutputData {
  const numProp = mesh.numProp || 3;
  const positions = new Float32Array(mesh.numVert * 3);
  for (let vertex = 0; vertex < mesh.numVert; vertex += 1) {
    positions[vertex * 3] = mesh.vertProperties[vertex * numProp];
    positions[vertex * 3 + 1] = mesh.vertProperties[vertex * numProp + 1];
    positions[vertex * 3 + 2] = mesh.vertProperties[vertex * numProp + 2];
  }
  return {
    positions,
    indices: new Uint32Array(mesh.triVerts),
  };
}

function dispose(manifold: ManifoldLike | undefined): void {
  if (!manifold) return;
  try {
    manifold.delete();
  } catch {
    // A failed constructor may not own WASM memory. Cleanup must not hide the useful error.
  }
}

function buildSource(wasm: WasmLike, input: SplitInputData): ManifoldLike {
  const mesh = new wasm.Mesh({
    numProp: 3,
    triVerts: new Uint32Array(input.indices),
    vertProperties: new Float32Array(input.positions),
    runIndex: new Uint32Array([0, input.indices.length]),
    runOriginalID: new Uint32Array([0]),
  });
  // Three.js indexed imports can still duplicate positions at normal/UV seams,
  // while STL imports duplicate every corner. With position-only properties,
  // welding these copies is safe; any resulting invalid connectivity is still
  // rejected by Manifold rather than repaired heuristically.
  mesh.merge();
  try {
    return new wasm.Manifold(mesh);
  } catch (error) {
    throw readableManifoldError(error);
  }
}

function validateSource(source: ManifoldLike): void {
  const inputStatus = statusName(source.status());
  if (inputStatus !== 'NoError' || source.isEmpty() || source.numTri() === 0) {
    throw new GeometrySplitError(
      errorCodeForStatus(inputStatus),
      inputStatus.toLowerCase().includes('manifold')
        ? 'A malha não é um sólido fechado (2-manifold). Verifique bordas abertas, faces duplicadas e normais.'
        : 'A malha não pôde ser reconhecida como um sólido válido.',
    );
  }
}

/**
 * Pure mesh-data planar split. The browser worker and Node tests both use this function.
 * The first side is in the direction of the normalized plane normal.
 */
export async function splitGeometryData(
  input: SplitInputData,
  normal: PlaneNormal,
  offset: number,
): Promise<SplitOutputData[]> {
  validateInput(input);
  const plane = normalizePlane(normal, offset);
  const wasm = await getWasm();
  let source: ManifoldLike | undefined;
  const owned: ManifoldLike[] = [];

  try {
    source = buildSource(wasm, input);
    owned.push(source);
    validateSource(source);

    let sides: [ManifoldLike, ManifoldLike];
    try {
      sides = source.splitByPlane(plane.normal, plane.offset);
    } catch (error) {
      throw readableManifoldError(error);
    }
    owned.push(...sides);

    if (sides.some((side) => side.isEmpty() || side.numTri() === 0 || !Number.isFinite(side.volume()) || side.volume() <= 0)) {
      throw new GeometrySplitError('plane-miss', 'O plano não atravessa o sólido. Ajuste a posição do corte.');
    }

    const originalComponents = source.decompose();
    owned.push(...originalComponents);
    const outputs: SplitOutputData[] = [];
    for (const side of sides) {
      let components: ManifoldLike[];
      try {
        components = side.decompose();
      } catch (error) {
        throw readableManifoldError(error);
      }
      owned.push(...components);
      for (const component of components) {
        if (component.isEmpty() || component.numTri() === 0 || component.volume() <= 0) continue;
        const outputMesh = component.getMesh();
        outputs.push(toOutput(outputMesh));
      }
    }

    if (outputs.length <= originalComponents.length) {
      throw new GeometrySplitError('plane-miss', 'O plano não atravessa o sólido. Ajuste a posição do corte.');
    }
    return outputs;
  } finally {
    for (let index = owned.length - 1; index >= 0; index -= 1) dispose(owned[index]);
  }
}

function buildFreeBlade(
  wasm: WasmLike,
  cut: ValidatedFreeCut,
  ownedCrossSections: CrossSectionLike[],
  ownedManifolds: ManifoldLike[],
): ManifoldLike {
  const sections: CrossSectionLike[] = [];
  const rememberSection = (section: CrossSectionLike): CrossSectionLike => {
    ownedCrossSections.push(section);
    return section;
  };

  // A rectangle for every stroke segment gives the exact swept width. Circles
  // at every sample point provide round caps and round joints, including when
  // the stroke reverses direction or doubles back in X.
  for (let index = 1; index < cut.points.length; index += 1) {
    const start = cut.points[index - 1];
    const end = cut.points[index];
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const length = Math.hypot(dx, dy);
    if (length <= cut.safeEpsilon) continue;
    const midpoint: Vec2 = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    let rectangle = rememberSection(wasm.CrossSection.square([length, cut.kerf], true));
    rectangle = rememberSection(rectangle.rotate(angle));
    rectangle = rememberSection(rectangle.translate(midpoint));
    sections.push(rectangle);
  }
  for (const point of cut.points) {
    const circle = rememberSection(wasm.CrossSection.circle(cut.kerf / 2, 24));
    sections.push(rememberSection(circle.translate(point)));
  }
  if (!sections.length) {
    throw new GeometrySplitError('invalid-free-cut', 'A trajetória não contém segmentos utilizáveis.');
  }

  const union = rememberSection(wasm.CrossSection.union(sections));
  if (union.numVert?.() === 0) {
    throw new GeometrySplitError('invalid-free-cut', 'Não foi possível construir a lâmina do traço.');
  }

  const rawBlade = wasm.Manifold.extrude(union, cut.depthMax - cut.depthMin);
  ownedManifolds.push(rawBlade);
  const depthTranslated = rawBlade.translate([0, 0, cut.depthMin]);
  ownedManifolds.push(depthTranslated);
  const frame: Mat4 = [
    cut.u[0], cut.u[1], cut.u[2], 0,
    cut.v[0], cut.v[1], cut.v[2], 0,
    cut.w[0], cut.w[1], cut.w[2], 0,
    cut.origin[0], cut.origin[1], cut.origin[2], 1,
  ];
  const blade = depthTranslated.transform(frame);
  ownedManifolds.push(blade);
  return blade;
}

function applyConnector(wasm: WasmLike, source: ManifoldLike, parts: ManifoldLike[], cut: FreeCut, sections: CrossSectionLike[], owned: ManifoldLike[]): ManifoldLike[] {
  const c=cut.connector!;
  const fail=(message:string) => new GeometrySplitError('invalid-free-cut',message);
  const hexTip=c.tipDiameter??c.diameter*.7;
  if (![c.diameter,c.length,c.clearance,c.along,c.across].every(Number.isFinite) || c.diameter<=0 || c.length<=cut.kerf || c.clearance<0 || c.along<0 || c.along>1 || c.across<0 || c.across>1 || ![1,-1].includes(c.side) || !['cylinder','square','hexagon','rectangle'].includes(c.shape) || (c.shape==='rectangle' && (!Number.isFinite(c.thickness??c.diameter/2) || (c.thickness??c.diameter/2)<=0)) || (c.shape==='hexagon' && (!Number.isFinite(hexTip) || hexTip<=0 || hexTip>c.diameter))) throw fail('As medidas deste encaixe são inválidas. Confira diâmetro, comprimento, folga e formato.');
  const {center,normal,tangent}=getConnectorFrame(cut),axis=scale(normal,-c.side), y=cross(axis,tangent);
  if(Math.hypot(...normal)<.99) throw fail('Não foi possível calcular a direção do encaixe nesta região do corte. Mova-o um pouco ao longo da linha.');
  const keep=(m:ManifoldLike) => {owned.push(m);return m;};
  const prism=(radius:number,start:number,end:number,tipRadius=radius):ManifoldLike => {
    const sectionRadius=c.shape==='hexagon'?tipRadius:radius;
    const s=c.shape==='square' || c.shape==='rectangle' ? wasm.CrossSection.square([radius*2,c.shape==='rectangle' ? Math.max(.001,(c.thickness??c.diameter/2)+2*(radius-c.diameter/2)) : radius*2],true) : wasm.CrossSection.circle(sectionRadius,c.shape==='hexagon'?6:48);
    sections.push(s);
    const raw=keep(c.shape==='hexagon' && Math.abs(radius-tipRadius)>1e-9 ? wasm.Manifold.extrude(s,end-start,1,0,[radius/tipRadius,radius/tipRadius]) : wasm.Manifold.extrude(s,end-start));
    const p=add(center,scale(axis,start));
    return keep(raw.transform([tangent[0],tangent[1],tangent[2],0,y[0],y[1],y[2],0,axis[0],axis[1],axis[2],0,p[0],p[1],p[2],1]));
  };
  const radius=c.diameter/2, anchor=Math.max(cut.kerf*2,Math.min(c.length/2,radius));
  const tip=-cut.kerf/2-c.length, tol=Math.max(source.volume()*1e-9,1e-8);
  // A wall allowance around the whole tool proves that the socket has a bottom
  // and neither feature breaks through the original outside shell.
  const wall=Math.max(.05,c.diameter*.025);
  const tipRadius=hexTip/2;
  const envelope=prism(radius+c.clearance+wall,tip-c.clearance-wall,cut.kerf/2+anchor+wall,tipRadius+c.clearance+wall);
  if(keep(envelope.subtract(source)).volume()>tol) throw fail('O espaço completo do encaixe encosta na superfície externa ou em um corte anterior. Mova o pino para uma área mais larga da peça ou reduza seu diâmetro/comprimento.');
  // Identify the receiving solids along the connector axis. A full-width probe
  // straddles curved seams even when the final boolean produces a valid joint.
  const probeRadius=Math.min(radius*.1,.1);
  const base=prism(probeRadius,cut.kerf/2+anchor*.5,cut.kerf/2+anchor);
  const end=prism(probeRadius,tip,tip+c.length*.1);
  const findContaining=(probe:ManifoldLike) => {
    const hits=parts.map((part,i)=>({i,v:keep(probe.intersect(part)).volume()})).filter(h=>h.v>probe.volume()*.98);
    if(hits.length!==1) throw fail('O encaixe não encontrou material suficiente nos dois lados do corte. Mova-o para mais perto do centro da superfície verde.'); return hits[0].i;
  };
  const male=findContaining(base),female=findContaining(end);
  if(male===female) throw fail('O pino e a cavidade ficaram no mesmo lado do corte. Mova o encaixe para uma região em que a superfície verde atravesse completamente a peça.');
  const pin=prism(radius,tip,cut.kerf/2+anchor,tipRadius);
  // Clear the entire pin wherever the curved female face extends past the
  // local tangent plane; clipping is performed by the female solid itself.
  const socket=prism(radius+c.clearance,tip-c.clearance,cut.kerf/2+anchor,tipRadius+c.clearance);
  const next=[...parts];
  next[male]=keep(parts[male].add(pin));next[female]=keep(parts[female].subtract(socket));
  for(const i of [male,female]) {
    if(statusName(next[i].status())!=='NoError' || next[i].isEmpty()) throw fail('A forma do encaixe ficou inválida nesta região. Reduza o tamanho ou afaste-o de bordas e de outros cortes.');
    const chunks=next[i].decompose(); owned.push(...chunks);
    if(chunks.length!==1) throw fail('O encaixe partiria uma das peças em fragmentos. Mova-o para uma região mais espessa.');
  }
  // No unintended interference between the pair after the radial-clearance socket.
  if(keep(next[male].intersect(next[female])).volume()>tol) throw fail('O pino ainda interfere com a cavidade após aplicar a folga. Aumente a folga ou reduza o encaixe.');
  return next;
}

function sourceDepthBounds(input: SplitInputData, cut: ValidatedFreeCut): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  const vertexCount = input.positions.length / 3;
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    const dx = input.positions[vertex * 3] - cut.origin[0];
    const dy = input.positions[vertex * 3 + 1] - cut.origin[1];
    const dz = input.positions[vertex * 3 + 2] - cut.origin[2];
    const depth = dx * cut.w[0] + dy * cut.w[1] + dz * cut.w[2];
    min = Math.min(min, depth);
    max = Math.max(max, depth);
  }
  return { min, max };
}

function freeCutFailure(input: SplitInputData, cut: ValidatedFreeCut): GeometrySplitError {
  const depth = sourceDepthBounds(input, cut);
  const tolerance = Math.max(cut.safeEpsilon * 10, (cut.depthMax - cut.depthMin) * 1e-6);
  if (cut.depthMin > depth.min + tolerance || cut.depthMax < depth.max - tolerance) {
    return new GeometrySplitError(
      'insufficient-depth',
      'O traço ainda não soltou a região. Confira a profundidade, estenda o traço até as bordas e verifique se existe outra ligação física. O original foi preservado.',
    );
  }
  return new GeometrySplitError(
    'insufficient-separation',
    'O traço alcançou a peça, mas ainda existe outra conexão física entre as regiões. Estenda o traço até as bordas.',
  );
}

/**
 * Subtracts a finite-depth swept blade following an arbitrary open 2D stroke.
 * The frame maps local XY to the drawing plane and local Z to camera depth.
 */
export async function splitFreeGeometryData(
  input: SplitInputData,
  cut: FreeCut,
): Promise<SplitOutputData[]> {
  validateInput(input);
  const validated = validatedFreeCut(input, cut);
  const wasm = await getWasm();
  let source: ManifoldLike | undefined;
  const ownedManifolds: ManifoldLike[] = [];
  const ownedCrossSections: CrossSectionLike[] = [];

  try {
    source = buildSource(wasm, input);
    ownedManifolds.push(source);
    validateSource(source);

    let originalComponents: ManifoldLike[];
    try {
      originalComponents = source.decompose();
    } catch (error) {
      throw readableManifoldError(error);
    }
    ownedManifolds.push(...originalComponents);

    const blade = cut.rails
      ? buildSource(wasm, ruledSheet(cut, inputBounds(input).maxExtent))
      : buildFreeBlade(wasm, validated, ownedCrossSections, ownedManifolds);
    if (cut.rails) { ownedManifolds.push(blade); validateSource(blade); }
    let touched: ManifoldLike;
    try {
      touched = source.intersect(blade);
    } catch (error) {
      throw readableManifoldError(error);
    }
    ownedManifolds.push(touched);
    const touchedVolume = touched.isEmpty() ? 0 : touched.volume();
    const volumeTolerance = Math.max(Math.abs(source.volume()) * 1e-10, validated.safeEpsilon ** 3);
    if (!Number.isFinite(touchedVolume) || touchedVolume <= volumeTolerance) {
      throw new GeometrySplitError(
        'free-cut-miss',
        'O traço não atravessa a peça. Ajuste a posição ou a orientação do corte.',
      );
    }

    let result: ManifoldLike;
    try {
      result = source.subtract(blade);
    } catch (error) {
      throw readableManifoldError(error);
    }
    ownedManifolds.push(result);
    const resultStatus = statusName(result.status());
    if (resultStatus !== 'NoError') throw readableManifoldError({ code: resultStatus });

    let components: ManifoldLike[];
    try {
      components = result.decompose();
    } catch (error) {
      throw readableManifoldError(error);
    }
    ownedManifolds.push(...components);
    if (components.length <= originalComponents.length) throw freeCutFailure(input, validated);
    if (cut.connector?.enabled) components = applyConnector(wasm, source, components, cut, ownedCrossSections, ownedManifolds);
    const outputs: SplitOutputData[] = [];
    for (const component of components) {
      if (component.isEmpty() || component.numTri() === 0) continue;
      const volume = component.volume();
      if (!Number.isFinite(volume) || volume <= volumeTolerance) continue;
      outputs.push(toOutput(component.getMesh()));
    }

    if (outputs.length <= originalComponents.length) {
      throw freeCutFailure(input, validated);
    }
    return outputs;
  } finally {
    // CrossSections and every intermediate transformed/boolean Manifold own
    // independent WASM allocations. Delete in reverse dependency order while
    // retaining them all until output meshes have been copied.
    for (let index = ownedManifolds.length - 1; index >= 0; index -= 1) dispose(ownedManifolds[index]);
    for (let index = ownedCrossSections.length - 1; index >= 0; index -= 1) {
      try {
        ownedCrossSections[index].delete();
      } catch {
        // Cleanup must not hide the useful geometry error.
      }
    }
  }
}

export function splitErrorFromUnknown(error: unknown): GeometrySplitError {
  if (error instanceof GeometrySplitError) return error;
  return readableManifoldError(error);
}



