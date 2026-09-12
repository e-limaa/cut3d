import { ArrowLeftRight, Link2 } from 'lucide-react';
import type { ConnectorOptions, FreeCut } from './freeCut';
import { clearancePresets } from './clearancePresets';

const defaults: ConnectorOptions = { enabled: true, shape: 'cylinder', diameter: 3, length: 4, clearance: .25, side: 1, along: .5, across: .5, preset: 'PLA' };
export default function ConnectorControls({ cut, onCut, disabled, editing, toggleEditing }: { cut: FreeCut; onCut: (cut: FreeCut) => void; disabled: boolean; editing:boolean; toggleEditing:()=>void }) {
  const connector = cut.connector ?? { ...defaults, enabled: false };
  const update = (patch: Partial<ConnectorOptions>) => onCut({ ...cut, connector: { ...connector, ...patch } });
  const numeric = (label: string, key: 'diameter' | 'length' | 'clearance', min: number, step: number) => <label className="connector-number">{label}<span><input aria-label={label} type="number" value={connector[key]} min={min} step={step} onChange={event => { if (event.target.value !== '') update({ [key]: Number(event.target.value), ...(key === 'clearance' ? { preset: 'CUSTOM' } : {}) }); }}/><small>mm</small></span></label>;
  return <fieldset className="connector-controls" disabled={disabled}>
    <label className="connector-enable"><Link2 size={16}/><span>Encaixe macho e fêmea</span><input type="checkbox" checked={connector.enabled} onChange={event => update({ enabled: event.target.checked })}/></label>
    {connector.enabled ? <>
      <button className="secondary full" type="button" aria-pressed={editing} onClick={toggleEditing}>{editing ? 'Concluir edição do pino' : 'Editar pino com o mouse'}</button>
      {editing ? <p className="surface-lock-note">Edição do pino ativa · navegação travada. Conclua para voltar a girar o modelo.</p> : null}
      <div className="axis-buttons connector-shapes">{(['cylinder', 'square', 'hexagon', 'rectangle'] as const).map((shape, index) => <button type="button" key={shape} className={connector.shape === shape ? 'selected' : ''} onClick={() => update({ shape, ...(shape === 'rectangle' ? { thickness: connector.thickness ?? connector.diameter / 2 } : {}) })}>{['Cilindro', 'Quadrado', 'Sextavado', 'Retangular'][index]}</button>)}</div>
      {numeric(['square','rectangle'].includes(connector.shape) ? 'Largura do pino' : 'Diâmetro do pino', 'diameter', .1, .1)}
      {connector.shape === 'hexagon' ? <label className="connector-number">Diâmetro da ponta<span><input aria-label="Diâmetro da ponta" type="number" min={.1} max={connector.diameter} step={.1} value={connector.tipDiameter ?? Number((connector.diameter * .7).toFixed(2))} onChange={event => { if (event.target.value !== '') update({ tipDiameter: Math.min(connector.diameter, Math.max(.1, Number(event.target.value))) }); }}/><small>mm</small></span></label> : null}
      {numeric('Comprimento do pino', 'length', .1, .1)}
      {connector.shape==='rectangle' ? <label className="connector-number">Espessura do pino<span><input aria-label="Espessura do pino" type="number" min={.1} step={.1} value={connector.thickness ?? connector.diameter/2} onChange={event=>{if(event.target.value!=='')update({thickness:Math.max(.1,Number(event.target.value))});}}/><small>mm</small></span></label> : null}
      <label className="connector-material">Preset de folga<select value={connector.preset ?? 'CUSTOM'} onChange={event => { const preset = clearancePresets.find(p => p.id === event.target.value); update({ preset: event.target.value, ...(preset ? { clearance: preset.clearance } : {}) }); }}><option value="CUSTOM">Personalizado</option>{clearancePresets.map(preset => <option key={preset.id} value={preset.id}>{preset.label} · {preset.clearance.toLocaleString('pt-BR')} mm</option>)}</select></label>
      {numeric('Folga por lado', 'clearance', 0, .05)}
      <p className="connector-help">O soquete fica {Number((connector.clearance * 2).toFixed(3)).toLocaleString('pt-BR')} mm mais largo que o pino. Presets são valores iniciais: ajuste conforme sua impressora e calibração.</p>
      <p className="connector-help">Pino em dourado. A cavidade com a folga escolhida será criada na outra peça.{connector.shape === 'hexagon' ? ' A ponta mais fina facilita iniciar o encaixe.' : ''}</p>
      <p className="connector-help">Ative a edição e arraste as alças: branca para posição, azul para largura e amarela para comprimento.{connector.shape === 'rectangle' ? ' Rosa para espessura.' : ''} Esc cancela o ajuste. Conclua a edição do pino para voltar a girar o modelo.</p>
      <button className="secondary full" type="button" onClick={() => update({ side: connector.side === 1 ? -1 : 1 })}><ArrowLeftRight size={14}/>Inverter macho e fêmea</button>
      <label className="slider-field"><span>Posição ao longo do corte</span><input type="range" min={.05} max={.95} step={.01} value={connector.along} onChange={event => update({ along: Number(event.target.value) })}/></label>
      <label className="slider-field"><span>Posição entre frente e verso</span><input type="range" min={.05} max={.95} step={.01} value={connector.across} onChange={event => update({ across: Number(event.target.value) })}/></label>
    </> : null}
  </fieldset>;
}
