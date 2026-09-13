/** One pointer owns a gesture. Cancellation rolls back; pointer-up commits. */
export function listenForPointerDrag(canvas: EventTarget, host: EventTarget, pointerId: number, callbacks: {
  move: (event: PointerEvent) => void;
  commit: () => void;
  cancel: () => void;
}): () => void {
  let active = true;
  const finish = (cancel: boolean) => {
    if (!active) return;
    active = false;
    if (cancel) callbacks.cancel(); else callbacks.commit();
  };
  const move = (event: Event) => { if (active && (event as PointerEvent).pointerId === pointerId) callbacks.move(event as PointerEvent); };
  const up = (event: Event) => { if ((event as PointerEvent).pointerId === pointerId) finish(false); };
  const cancel = (event: Event) => { if ((event as PointerEvent).pointerId === pointerId) finish(true); };
  const key = (event: Event) => { if ((event as KeyboardEvent).key === 'Escape') finish(true); };
  const blur = () => finish(true);
  canvas.addEventListener('pointermove', move);
  host.addEventListener('pointerup', up);
  host.addEventListener('pointercancel', cancel);
  host.addEventListener('keydown', key);
  host.addEventListener('blur', blur);
  return () => {
    active = false;
    canvas.removeEventListener('pointermove', move);
    host.removeEventListener('pointerup', up);
    host.removeEventListener('pointercancel', cancel);
    host.removeEventListener('keydown', key);
    host.removeEventListener('blur', blur);
  };
}
