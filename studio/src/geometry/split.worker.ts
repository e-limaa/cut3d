import { processGeometryRequest } from './requests';
import type { GeometryWorkerRequest, SplitWorkerResponse } from './types';

const workerScope = globalThis as unknown as {
  onmessage: ((event: MessageEvent<GeometryWorkerRequest>) => void) | null;
  postMessage: (message: SplitWorkerResponse, transfer?: Transferable[]) => void;
};

workerScope.onmessage = async event => {
  const response = await processGeometryRequest(event.data);
  const transfer: Transferable[] = [];
  if (response.type === 'success') for (const output of response.outputs) transfer.push(output.positions.buffer, output.indices.buffer);
  workerScope.postMessage(response, transfer);
};
