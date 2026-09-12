import fixture from './silhouette-cut.fixture';
import {expect, it} from 'vitest';
import {ruledSheet} from './ruledSheet';
import type {FreeCut} from '../freeCut';

it('keeps a thin silhouette endpoint valid without changing surface anchors', () => {
  const cut = structuredClone(fixture) as FreeCut;
  const before = structuredClone(cut);
  const sheet = ruledSheet(cut,64.25800322084962);
  expect(cut).toEqual(before);
  expect([...sheet.positions].every(Number.isFinite)).toBe(true);
  const edges = new Map<string,number>();
  for(let i=0;i<sheet.indices.length;i+=3) for(let j=0;j<3;j++) {
    const a=sheet.indices[i+j], b=sheet.indices[i+(j+1)%3];
    const key=a<b ? `${a}:${b}` : `${b}:${a}`;
    edges.set(key,(edges.get(key)??0)+1);
  }
  expect([...edges.values()].every(count=>count===2)).toBe(true);
});
