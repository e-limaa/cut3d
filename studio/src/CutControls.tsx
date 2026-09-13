import { Check, Pencil, RotateCcw, Scissors } from 'lucide-react';
import type { FreeCut } from './freeCut';
import ConnectorControls from './ConnectorControls';
export function Slider({ label, value, min, max, unit = '°', onChange, disabled = false }: { label: string; value: number; min: number; max: number; unit?: string; onChange: (value: number) => void; disabled?: boolean }) {
  return <label className="slider-field"><span>{label}<span className="number">{value.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}<small>{unit}</small></span></span><input type="range" min={min} max={max} step={(max - min) / 400} value={value} onChange={event => onChange(Number(event.target.value))} disabled={disabled}/></label>;
}
type Props = {
  mode: 'FREE' | 'PLANE'; onMode: (mode: 'FREE' | 'PLANE') => void;
  cut: FreeCut | null; onCut: (cut: FreeCut) => void;
  drawing: boolean; startDraw: () => void; cancelDraw: () => void;
  editing: boolean; toggleEditing: () => void;
  selectedPoint: number | null; togglePointCurve: () => void;
  editingConnector:boolean; toggleConnectorEditing:()=>void;
  busy: boolean; radius: number;
  offset: number; tilt: number; turn: number;
  setOffset: (value: number) => void; setTilt: (value: number) => void; setTurn: (value: number) => void; reset: () => void;
};
export default function CutControls(props: Props) {
  const { mode, onMode, cut, onCut, drawing, startDraw, cancelDraw, editing, toggleEditing, selectedPoint, togglePointCurve, busy, radius, offset, tilt, turn, setOffset, setTilt, setTurn, reset } = props;
  return <>
    <div className="mode-tabs" aria-label="Tipo de corte"><button className={mode === 'FREE' ? 'selected' : ''} disabled={busy} onClick={() => onMode('FREE')}><Pencil size={15}/>Livre</button><button className={mode === 'PLANE' ? 'selected' : ''} disabled={busy} onClick={() => onMode('PLANE')}><Scissors size={15}/>Plano</button></div>
    {mode === 'FREE' ? <>
      <div className="type-selection"><Pencil size={18}/><div><strong>Corte livre na superfície</strong><span>Contorno único sobre a peça</span></div><Check size={15}/></div>
      <button className={drawing ? 'secondary full drawing-button' : 'primary full draw-button'} disabled={busy} onClick={drawing ? cancelDraw : startDraw}><Pencil size={16}/>{drawing ? 'Cancelar desenho · Esc' : cut ? 'Redesenhar traço' : 'Desenhar sobre o modelo'}</button>
      <p className="free-instruction">{drawing ? 'Arraste com o botão esquerdo. Comece e termine fora da região que quer separar. A câmera fica parada durante o desenho.' : cut ? 'Arraste cada ponto diretamente sobre o modelo. Os outros pontos permanecem no lugar.' : 'Enquadre a região, ative o desenho e atravesse a peça com uma curva.'}</p>
      {cut?.rails ? <button className="secondary full" disabled={busy || drawing} onClick={toggleEditing}><Pencil size={15}/>{editing ? 'Concluir edição dos pontos' : 'Editar pontos na superfície'}</button> : null}
      {editing ? <div className="surface-edit-panel"><p>{selectedPoint === null ? 'Clique em um ponto para selecioná-lo' : `Ponto ${selectedPoint + 1} selecionado`}</p><small>Arraste o ponto para posicionar. Arraste fora dos pontos para girar.</small></div> : null}
      {cut ? <fieldset disabled={busy || drawing} className="free-fields"><div className="control-header">{cut.rails ? 'SUPERFÍCIE DO CORTE' : 'ALCANCE DO CORTE'}</div>
        {!cut.rails ? <>
        <Slider label="Frente da faixa" value={cut.depthMax} min={-radius} max={radius} unit="mm" onChange={value => { const depth = cut.depthMax - cut.depthMin; onCut({ ...cut, depthMax: value, depthMin: value - depth }); }}/>
        <Slider label="Profundidade" value={cut.depthMax - cut.depthMin} min={Math.max(.01, radius * .0001)} max={radius * 2.1} unit="mm" onChange={value => onCut({ ...cut, depthMin: cut.depthMax - value })}/>
        </> : <p className="surface-lock-note">Pontos presos à malha · ao arrastar fora do modelo, o ponto permanece no último local válido.</p>}
        <Slider label="Espessura removida" value={cut.kerf} min={Math.max(.01, radius * .0001)} max={Math.max(1, radius * .03)} unit="mm" onChange={value => onCut({ ...cut, kerf: value })}/>
        <div className="depth-legend"><span><i/>Contorno</span><span>{cut.rails ? `${cut.rails.front.length} controles` : `${cut.points.length} pontos`}</span></div>
      </fieldset> : null}
      {cut ? <ConnectorControls cut={cut} onCut={onCut} disabled={busy || drawing || editing} editing={props.editingConnector} toggleEditing={props.toggleConnectorEditing}/> : null}
      <div className="tip"><p>Use um traço aberto. A faixa remove material na espessura indicada e deve atravessar a região para soltar uma peça. Confira o fundo para evitar atingir outra parte atrás.</p></div>
    </> : <>
      <div className="type-selection"><Scissors size={18}/><div><strong>Corte plano</strong><span>Atravessa todo o modelo</span></div><Check size={15}/></div>
      <div className="control-header">ORIENTAÇÃO INICIAL</div><div className="axis-buttons">{[['Horizontal', 0, 0], ['Frontal', 90, 0], ['Lateral', 0, 90]].map(([label, x, y]) => <button key={label} disabled={busy} className={tilt === x && turn === y ? 'selected' : ''} onClick={() => { setTilt(Number(x)); setTurn(Number(y)); }}>{label}</button>)}</div>
      <Slider label="Posição" value={offset} min={-radius} max={radius} unit="mm" onChange={setOffset} disabled={busy}/><Slider label="Inclinação" value={tilt} min={-180} max={180} onChange={setTilt} disabled={busy}/><Slider label="Rotação" value={turn} min={-180} max={180} onChange={setTurn} disabled={busy}/><button className="text-button reset-cut" disabled={busy} onClick={reset}><RotateCcw size={13}/>Restaurar ajustes</button>
    </>}
  </>;
}
