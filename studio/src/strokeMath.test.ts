import { describe, expect, it } from 'vitest';
import { freeCutPoint, simplifyStroke } from './strokeMath';

describe('stroke editor geometry', () => {
  it('reduces jitter without losing endpoints or a returning section', () => {
    expect(simplifyStroke([[0, 0], [1, .01], [2, 0], [2, 2], [1, 2], [0, 2]], .1)).toEqual([[0, 0], [2, 0], [2, 2], [0, 2]]);
  });
  it('maps the preview to the same right-handed frame used by the cutter', () => {
    const frame = { points: [[0, 0] as [number, number]], origin: [10, 20, 30] as [number, number, number], u: [1, 0, 0] as [number, number, number], v: [0, 0, 1] as [number, number, number], w: [0, -1, 0] as [number, number, number], depthMin: -4, depthMax: 5, kerf: .2 };
    expect(freeCutPoint(frame, [2, 3], 5)).toEqual([12, 15, 33]);
    expect(freeCutPoint(frame, [2, 3], -4)).toEqual([12, 24, 33]);
  });
});
