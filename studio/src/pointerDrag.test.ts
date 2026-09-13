import { it, expect, vi } from 'vitest';
import { listenForPointerDrag } from './pointerDrag';

function pointer(type: string, id = 7) { return Object.assign(new Event(type), { pointerId: id }); }
it.each(['Escape', 'pointercancel', 'blur'])('rolls back the active gesture on %s, and ignores a later pointer-up', reason => {
  const canvas=new EventTarget(), host=new EventTarget();
  const original={position:1}, moved={position:2};
  let current=original, orbitEnabled=false;
  const commit=vi.fn();
  const cancel=vi.fn(() => { current=original; orbitEnabled=true; });
  const cleanup=listenForPointerDrag(canvas,host,7,{move:()=>{current=moved;},commit,cancel});
  canvas.dispatchEvent(pointer('pointermove'));
  expect(current).toBe(moved);
  host.dispatchEvent(reason==='Escape' ? Object.assign(new Event('keydown'),{key:'Escape'}) : pointer(reason));
  host.dispatchEvent(pointer('pointerup'));
  canvas.dispatchEvent(pointer('pointermove'));
  expect(current).toBe(original);
  expect(orbitEnabled).toBe(true);
  expect(commit).not.toHaveBeenCalled();
  expect(cancel).toHaveBeenCalledTimes(1);
  cleanup();
});
it('ignores unrelated pointers, commits once, and removes listeners on cleanup', () => {
  const canvas=new EventTarget(),host=new EventTarget(),move=vi.fn(),commit=vi.fn(),cancel=vi.fn();
  const cleanup=listenForPointerDrag(canvas,host,7,{move,commit,cancel});
  canvas.dispatchEvent(pointer('pointermove',8));
  host.dispatchEvent(pointer('pointercancel',8));
  host.dispatchEvent(pointer('pointerup',8));
  expect(move).not.toHaveBeenCalled();expect(cancel).not.toHaveBeenCalled();expect(commit).not.toHaveBeenCalled();
  canvas.dispatchEvent(pointer('pointermove'));
  host.dispatchEvent(pointer('pointerup'));
  host.dispatchEvent(pointer('pointerup'));
  expect(move).toHaveBeenCalledTimes(1);expect(commit).toHaveBeenCalledTimes(1);
  cleanup();host.dispatchEvent(new Event('blur'));expect(cancel).not.toHaveBeenCalled();
});
