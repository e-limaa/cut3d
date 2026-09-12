export type PlaneNormal = readonly [number, number, number];

import type { FreeCut } from '../freeCut';

/** A compact, transferable representation of a triangle mesh. */
export interface SplitInputData {
  /** XYZ positions, three values per vertex. */
  positions: Float32Array;
  /** Three vertex indices per triangle. */
  indices: Uint32Array;
  /** Non-indexed source data may safely be welded by Manifold's Mesh.merge(). */
  weld: boolean;
}

export interface SplitOutputData {
  positions: Float32Array;
  indices: Uint32Array;
}

export type GeometrySplitErrorCode =
  | 'invalid-input'
  | 'invalid-plane'
  | 'invalid-free-cut'
  | 'non-manifold'
  | 'plane-miss'
  | 'free-cut-miss'
  | 'insufficient-depth'
  | 'insufficient-separation'
  | 'engine';

export class GeometrySplitError extends Error {
  readonly code: GeometrySplitErrorCode;

  constructor(code: GeometrySplitErrorCode, message: string) {
    super(message);
    this.name = 'GeometrySplitError';
    this.code = code;
  }
}

export interface SplitWorkerRequest {
  type: 'split';
  input: SplitInputData;
  normal: PlaneNormal;
  offset: number;
}

export interface FreeCutWorkerRequest {
  type: 'free-cut';
  input: SplitInputData;
  cut: FreeCut;
}

export interface SplitWorkerSuccess {
  type: 'success';
  outputs: SplitOutputData[];
}

export interface SplitWorkerFailure {
  type: 'error';
  code: GeometrySplitErrorCode;
  message: string;
}

export type SplitWorkerResponse = SplitWorkerSuccess | SplitWorkerFailure;

export type GeometryWorkerRequest = SplitWorkerRequest | FreeCutWorkerRequest;
