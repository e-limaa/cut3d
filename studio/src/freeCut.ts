/** View-aligned local coordinates. u × v = w; w points toward the camera. */
export type Vec3 = [number, number, number];
export interface ConnectorOptions {
  enabled: boolean;
  shape: 'cylinder' | 'square' | 'hexagon' | 'rectangle';
  thickness?: number;
  /** Hexagonal pin width at its free end. Defaults to 70% of diameter. */
  tipDiameter?: number;
  diameter: number;
  length: number;
  clearance: number;
  side: 1 | -1;
  /** Location on the cut surface, along the stroke and from front to back. */
  along: number;
  across: number;
  preset?: string;
}
export interface FreeCut {
  points: [number, number][];
  origin: Vec3;
  u: Vec3;
  v: Vec3;
  w: Vec3;
  depthMin: number;
  depthMax: number;
  kerf: number;
  /** Paired world-space samples of one unified cut contour on the actual mesh. */
  rails?: { front: Vec3[]; back: Vec3[] };
  /** Optional Bezier handles for Pen-style editing, stored in the cut's 2D frame. */
  penCurves?: Record<number, { in: [number, number]; out: [number, number] }>;
  connector?: ConnectorOptions;
}
