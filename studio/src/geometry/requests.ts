import { splitErrorFromUnknown, splitFreeGeometryData, splitGeometryData } from './engine';
import type { GeometryWorkerRequest, SplitWorkerResponse } from './types';

/** Shared worker dispatch, exercised directly by the integration tests. */
export async function processGeometryRequest(request: GeometryWorkerRequest): Promise<SplitWorkerResponse> {
  try {
    const outputs = request.type === 'free-cut'
      ? await splitFreeGeometryData(request.input, request.cut)
      : await splitGeometryData(request.input, request.normal, request.offset);
    return { type: 'success', outputs };
  } catch (error) {
    const failure = splitErrorFromUnknown(error);
    return { type: 'error', code: failure.code, message: failure.message };
  }
}
