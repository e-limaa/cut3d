import { Component, useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, Box, Check, ChevronDown, CircleHelp, Crosshair, Expand, Eye, EyeOff, FileBox, Layers, LoaderCircle, MousePointer2, Move3D, Plus, RotateCcw, Scissors, ShieldCheck, Upload, X } from 'lucide-react';
import * as THREE from 'three';
import Viewport from './Viewport';
import { demoModel, downloadParts, loadModel, type Model } from './model';
import { buildCutPlan, type PlannedCut } from './geometry/multiCut';
import PlannedCutPreview from './PlannedCutPreview';
import FreeCutEditor from './FreeCutEditor';
import CutControls from './CutControls';
import type { FreeCut } from './freeCut';

class ViewerBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <div className="viewer-error">Não foi possível iniciar a visualização 3D. Ative a aceleração gráfica do navegador e recarregue a página.</div> : this.props.children; }
}
function Slider({ label, value, min, max, unit = '°', onChange, disabled = false }: { label: string; value: number; min: number; max: number; unit?: string; onChange: (value: number) => void; disabled?: boolean }) {
  return <label className="slider-field"><span>{label}<span className="number">{value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}<small>{unit}</small></span></span><input type="range" min={min} max={max} step={(max - min) / 400} value={value} onChange={event => onChange(Number(event.target.value))} disabled={disabled} /></label>;
}
export default function App() {
  const [model, setModel] = useState<Model>(demoModel);
  const [cuts, setCuts] = useState<PlannedCut[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeCut = cuts.find(cut => cut.id === activeId);
  const mode = activeCut?.mode ?? 'FREE';
  const freeCut = activeCut?.freeCut ?? null;
  const offset = activeCut?.offset ?? 0;
  const tilt = activeCut?.tilt ?? 0;
  const turn = activeCut?.turn ?? 0;
  const hasCut = cuts.length > 0;
  const updateActive = useCallback((patch: Partial<PlannedCut>) => setCuts(previous => previous.map(cut => cut.id === activeId ? { ...cut, ...patch } : cut)), [activeId]);
  const setMode = (value: 'FREE' | 'PLANE') => updateActive({ mode: value });
  const setOffset = (value: number) => updateActive({ offset: value });
  const setTilt = (value: number) => updateActive({ tilt: value });
  const setTurn = (value: number) => updateActive({ turn: value });
  const [drawing, setDrawing] = useState(false);
  const [editingSurface, setEditingSurface] = useState(false);
  const [selectedSurfacePoint, setSelectedSurfacePoint] = useState<number | null>(null);
  const [editingConnector, setEditingConnector] = useState(false);
  const receiveDraw = useCallback((cut: FreeCut) => { setCuts(previous => previous.map(item => item.id === activeId ? { ...item, freeCut: { ...cut, connector: cut.connector ?? item.freeCut?.connector } } : item)); setDrawing(false); setError(null); }, [activeId]);
  const cancelDraw = useCallback(() => setDrawing(false), []);
  const drawError = useCallback((message: string) => { setDrawing(false); setError(message); }, []);
  const [parts, setParts] = useState<THREE.BufferGeometry[]>([]);
  const [showPlane, setShowPlane] = useState(true);
  const [exploded, setExploded] = useState(.55);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reset, setReset] = useState(0);
  const [wireframe, setWireframe] = useState(false);
  const [help, setHelp] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const job = useRef(false);
  const normal = useMemo(() => new THREE.Vector3(0, 0, 1).applyEuler(new THREE.Euler(tilt * Math.PI / 180, turn * Math.PI / 180, 0)), [tilt, turn]);
  const radius = model.dimensions.length() / 2;
  const result = parts.length > 0;
  const format = (value: number) => value.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
  const connectorEditActive = editingConnector && mode === 'FREE' && !!freeCut?.connector?.enabled;
  const canBuild = hasCut && !drawing && !editingSurface && !connectorEditActive && cuts.every(cut => cut.mode === 'PLANE' || !!cut.freeCut);
  function selectCut(id: string) { setActiveId(id); setDrawing(false); setEditingSurface(false); setSelectedSurfacePoint(null); setEditingConnector(false); setShowPlane(true); setError(null); }
  function removeCut(id: string) {
    const remaining = cuts.filter(cut => cut.id !== id);
    setCuts(remaining);
    if (id === activeId) { setActiveId(remaining[0]?.id ?? null); setDrawing(false); setEditingSurface(false); setSelectedSurfacePoint(null); setEditingConnector(false); }
    setError(null);
  }
  function startCut() {
    const next: PlannedCut = { id: crypto.randomUUID(), mode: 'FREE', freeCut: null, offset: 0, tilt: 0, turn: 0 };
    setCuts(previous => [...previous, next]); setActiveId(next.id); setShowPlane(true); setEditingSurface(false); setEditingConnector(false); setDrawing(true); setError(null);
  }
  function changeMode(next: 'FREE' | 'PLANE') { setMode(next); setDrawing(false); setEditingSurface(false); setEditingConnector(false); setError(null); }
  function restore() { parts.forEach(part => part.dispose()); setParts([]); setSelected(null); setError(null); }
  function resetCut() { setOffset(0); setTilt(0); setTurn(0); setError(null); }
  function savePlan() {
    if (!hasCut) return;
    const data = JSON.stringify({version:2, model:model.name, dimensions:model.dimensions.toArray(), cuts, activeId}, null, 2);
    try {
      localStorage.setItem('cut3d-plan', data);
      const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));
      const link=document.createElement('a'); link.href=url; link.download='cut3d-plano.json'; link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch { setError('Não foi possível salvar o plano neste navegador.'); }
  }
  function restoreSavedPlan() {
    try {
      const plan=JSON.parse(localStorage.getItem('cut3d-plan') || 'null');
      if (!plan || ![1, 2].includes(plan.version)) throw new Error('Nenhum plano salvo neste navegador.');
      if (plan.model!==model.name || plan.dimensions.some((n:number,i:number)=>Math.abs(n-model.dimensions.toArray()[i])>.001)) throw new Error('Importe o mesmo modelo antes de restaurar o plano salvo.');
      const restored: PlannedCut[] = plan.version === 1 ? [{ id: crypto.randomUUID(), mode: plan.mode, freeCut: plan.freeCut, offset: plan.offset, tilt: plan.tilt, turn: plan.turn }] : plan.cuts;
      if (!Array.isArray(restored) || !restored.length || restored.some(cut => !cut.id || !['FREE', 'PLANE'].includes(cut.mode) || ![cut.offset, cut.tilt, cut.turn].every(Number.isFinite))) throw new Error('O plano salvo está incompleto.');
      restore(); setCuts(restored); setActiveId(restored.find(cut => cut.id === plan.activeId)?.id ?? restored[0].id);
      setDrawing(false); setEditingSurface(false); setEditingConnector(false); setShowPlane(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível restaurar o plano.'); }
  }
  async function importFile(file?: File) {
    if (!file || job.current) return;
    job.current = true; setBusy('Abrindo modelo…'); setError(null);
    try {
      const next = await loadModel(file);
      restore(); model.geometry.dispose(); setModel(next); setCuts([]); setActiveId(null); setDrawing(false); setEditingSurface(false); setEditingConnector(false); setReset(value => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível abrir este modelo.'); }
    finally { job.current = false; setBusy(null); if (fileInput.current) fileInput.current.value = ''; }
  }
  async function build() {
    if (job.current || !canBuild) return;
    job.current = true; setBusy('Construindo peças…'); setError(null);
    try { const next = await buildCutPlan(model.geometry, cuts, (index, total) => setBusy(`Construindo corte ${index} de ${total}…`)); setParts(next); setSelected(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível construir este corte. O original está preservado.'); }
    finally { job.current = false; setBusy(null); }
  }
  async function exportResult() {
    if (job.current || !parts.length) return;
    job.current = true; setBusy('Preparando exportação…');
    await new Promise(resolve => setTimeout(resolve, 40));
    try { downloadParts(parts, model.name); } catch { setError('Não foi possível gerar a exportação. Tente novamente.'); }
    finally { job.current = false; setBusy(null); }
  }
  return <div className="app-shell" onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); void importFile(event.dataTransfer.files[0]); }}>
    <header className="topbar"><a className="brand" href="#" aria-label="Cut3D Studio início" onClick={event => event.preventDefault()}><span className="brand-icon"><Scissors size={20}/></span>Cut3D<span className="brand-studio">STUDIO</span></a>
      <div className="project-title"><span className="live-dot"/>Projeto local <ChevronDown size={12}/></div>
      <div className="header-actions"><span className="alpha-badge">PRIMEIRA VERSÃO</span><button className="icon-button dark" aria-label="Ajuda" onClick={() => setHelp(true)}><CircleHelp size={19}/></button><button className="import-button" onClick={() => fileInput.current?.click()} disabled={!!busy}><Upload size={15}/>Importar modelo</button></div>
    </header>
    <input ref={fileInput} type="file" accept=".stl,.3mf" hidden onChange={event => void importFile(event.target.files?.[0])}/>
    <div className="plan-actions"><button className="text-button" disabled={!hasCut || !!busy} onClick={savePlan}>Salvar plano de corte</button><button className="text-button" disabled={!!busy} onClick={restoreSavedPlan}>Restaurar plano salvo</button></div>
    <div className="workspace">
      <aside className="left-panel"><div className="panel-heading"><span>SEU PROJETO</span><span className="mini-tag">01</span></div>
        <section className="model-card"><div className="model-symbol"><FileBox size={27} strokeWidth={1.3}/></div><div className="model-name" title={model.name}>{model.name}</div><div className="model-caption">{model.demo ? 'Modelo de demonstração' : 'Modelo importado'}<span>·</span>mm</div><div className="model-dimensions">{format(model.dimensions.x)} × {format(model.dimensions.y)} × {format(model.dimensions.z)}<span>mm</span></div><div className="model-foot"><span>{Math.round(model.triangles).toLocaleString('pt-BR')} triângulos</span><ShieldCheck size={14}/></div></section>
        <div className="section-title"><span>{result ? 'PEÇAS GERADAS' : 'PLANO DE CORTES'}</span><span>{result ? parts.length : cuts.length}</span></div>
        {result ? <div className="parts-list"><button className={selected === null ? 'part-row active' : 'part-row'} onClick={() => setSelected(null)}><Layers size={16}/> Todas as peças <span>{parts.length}</span></button>{parts.map((part, index) => <button className={selected === index ? 'part-row active' : 'part-row'} key={part.uuid} onClick={() => setSelected(selected === index ? null : index)}><Box size={16}/>Peça {String(index + 1).padStart(2, '0')}<Eye size={14}/></button>)}</div> : hasCut ? <div className="cuts-list">{cuts.map((cut, index) => <div key={cut.id} className={`cut-card ${cut.id === activeId ? 'selected-cut' : 'inactive-cut'}`}><div className="cut-card-top"><button className="cut-select" disabled={!!busy} aria-pressed={cut.id === activeId} onClick={() => selectCut(cut.id)}><Scissors size={16}/><span><strong>Corte {String(index + 1).padStart(2, '0')}</strong><small>{cut.mode === 'FREE' ? 'Traço livre' : 'Plano ajustável'}{cut.freeCut?.connector?.enabled ? ' · com encaixe' : ''}</small></span></button><button className="icon-button" disabled={!!busy} aria-label={`Remover corte ${index + 1}`} onClick={() => removeCut(cut.id)}><X size={15}/></button></div><div className="cut-status"><span/>{cut.mode === 'FREE' && !cut.freeCut ? 'Aguardando traço' : cut.id === activeId ? 'Selecionado para editar' : 'Em planejamento'}</div></div>)}</div> : <div className="empty-cuts"><span className="empty-mark">↗</span><p>O próximo passo<br/>é seu primeiro corte.</p></div>}
        {!result ? <button className="add-cut" disabled={!!busy || drawing} onClick={startCut}><Plus size={16}/>Adicionar corte</button> : null}
        <div className="left-bottom"><div className="local-note"><ShieldCheck size={18}/><div><strong>Seu arquivo fica com você</strong><p>Processamento local no navegador.<br/>O original permanece intacto.</p></div></div><button className="text-button" onClick={() => setHelp(true)}>Como funciona <ArrowRight size={13}/></button></div>
      </aside>
      <main className="viewport-panel" aria-label="Área de edição 3D">
        <div className="viewport-heading"><div className="breadcrumb">ESTÚDIO <span>/</span> {result ? 'INSPECIONAR PEÇAS' : 'PLANEJAR CORTE'}</div><div className="viewport-pill"><span/>{result ? `${parts.length} peças construídas` : 'Original preservado'}</div></div>
        <ViewerBoundary><Viewport model={model} normal={normal} offset={offset} parts={parts} exploded={exploded} showPlane={hasCut && mode === 'PLANE' && showPlane} reset={reset} wireframe={wireframe} selected={selected}>
          {!result && showPlane ? cuts.filter(cut => cut.id !== activeId).map(cut => <PlannedCutPreview key={cut.id} cut={cut} size={Math.max(model.dimensions.x, model.dimensions.y, model.dimensions.z)}/>) : null}
          {!result && hasCut && mode === 'FREE' ? <FreeCutEditor key={activeId} geometry={model.geometry} size={Math.max(model.dimensions.x, model.dimensions.y, model.dimensions.z)} drawing={drawing} cut={freeCut} visible={showPlane} editingConnector={editingConnector && !!freeCut?.connector?.enabled && !drawing && !editingSurface && !busy} editing={editingSurface && !busy} selectedPoint={selectedSurfacePoint} onSelectPoint={setSelectedSurfacePoint} onDraw={receiveDraw} onCancel={cancelDraw} onError={drawError}/> : null}
        </Viewport></ViewerBoundary>
        <div className="canvas-tools" style={drawing ? { pointerEvents: 'none', opacity: .5 } : undefined}><button className="tool active" title="Girar e navegar" aria-label="Navegação ativa"><MousePointer2 size={19}/></button><div className="tool-divider"/><button className="tool" title="Enquadrar modelo" aria-label="Enquadrar modelo" onClick={() => setReset(value => value + 1)}><Expand size={19}/></button><button className={wireframe ? 'tool active' : 'tool'} title="Mostrar malha" aria-label="Mostrar malha" aria-pressed={wireframe} onClick={() => setWireframe(value => !value)}><Box size={19}/></button>{hasCut && !result ? <button className="tool" title="Mostrar ou ocultar corte" aria-label="Mostrar ou ocultar corte" aria-pressed={showPlane} onClick={() => setShowPlane(value => !value)}>{showPlane ? <Eye size={19}/> : <EyeOff size={19}/>}</button> : null}</div>
        {!hasCut && !result ? <div className="intro-overlay"><span className="eyebrow">DO MODELO ÀS PEÇAS</span><h1>Seu modelo.<br/>Novas possibilidades.</h1><p>Desenhe seu próprio corte.<br/>Você escolhe a curva e o alcance.</p></div> : null}
        <div className="viewport-bottom"><span><Move3D size={14}/>{drawing ? 'Arraste para desenhar · Esc cancela' : 'Arraste para girar'}<span className="separator-dot">·</span>Scroll para aproximar<span className="separator-dot">·</span>Botão direito para mover</span><span className="units">Z ↑ <span>Milímetros</span></span></div>
        {busy ? <div className="busy-overlay" role="status"><LoaderCircle className="spin" size={23}/><strong>{busy}</strong><span>O tempo depende do tamanho da malha.</span></div> : null}
        {error ? <div className="error-toast" role="alert"><div><strong>Precisamos ajustar uma coisa</strong><p>{error}</p></div><button className="icon-button" aria-label="Fechar aviso" onClick={() => setError(null)}><X size={16}/></button></div> : null}
      </main>
      <aside className="right-panel"><div className="panel-heading"><span>{result ? 'RESULTADO' : 'FERRAMENTA DE CORTE'}</span><Scissors size={14}/></div>
        <div className="right-content">{result ? <>
          <div className="step-label"><span className="step-dot done"><Check size={13}/></span>CONSTRUÇÃO CONCLUÍDA</div>
          <h2>Veja por dentro.</h2><p className="description">Afaste as peças e confira as superfícies antes de exportar.</p>
          <div className="result-count"><strong>{parts.length.toString().padStart(2, '0')}</strong><div>peças separadas<span>Original preservado</span></div></div>
          <Slider label="Afastar peças" value={exploded} min={0} max={1} unit="" onChange={setExploded}/>
          <button className="secondary full" onClick={() => setExploded(0)}><Layers size={16}/>Ver montado</button>
          <div className="tip"><ShieldCheck size={17}/><p>Exportação STL em milímetros. O afastamento da prévia não altera os arquivos.</p></div>
          <p className="muted-detail">{mode === 'FREE' ? 'Separação construída pelo traço livre, com a profundidade e a espessura escolhidas.' : 'Separação construída por plano.'}</p>
        </> : <>
          <div className="step-label"><span className="step-dot">{hasCut ? '02' : '01'}</span>{hasCut ? 'DESENHAR E CONFERIR' : 'COMEÇAR PELO MODELO'}</div>
          <h2>{hasCut ? `Corte ${String(cuts.findIndex(cut => cut.id === activeId) + 1).padStart(2, '0')}` : 'Siga a forma.'}</h2>
          <p className="description">{hasCut ? 'Desenhe a curva e ajuste os pontos na superfície. Gire o modelo para conferir o verso.' : 'Separe a região que você escolher com um traço personalizado sobre o modelo.'}</p>
          {!hasCut ? <>
            <button className="primary full" disabled={!!busy} onClick={startCut}><Scissors size={17}/>Desenhar corte livre<ArrowRight size={16}/></button>
            <div className="steps-mini"><div><span>01</span><p>Desenhe a separação<small>Um traço que acompanha sua intenção.</small></p></div><div><span>02</span><p>Controle o alcance<small>Confira a frente e o fundo da faixa.</small></p></div><div><span>03</span><p>Construa e confira<small>Inspecione as peças antes de exportar.</small></p></div></div>
            <div className="tip"><p>Você pode começar e terminar o traço fora da silhueta. Para girar a vista, encerre ou cancele o desenho.</p></div>
          </> : <CutControls mode={mode} onMode={changeMode} cut={freeCut} onCut={receiveDraw} drawing={drawing} editing={editingSurface} selectedPoint={selectedSurfacePoint} editingConnector={editingConnector && !!freeCut?.connector?.enabled} toggleConnectorEditing={() => { setEditingConnector(value => !value); setEditingSurface(false); setSelectedSurfacePoint(null); setShowPlane(true); }} toggleEditing={() => { setEditingConnector(false); setEditingSurface(value => !value); setSelectedSurfacePoint(null); setShowPlane(true); }} startDraw={() => { setDrawing(true); setEditingSurface(false); setSelectedSurfacePoint(null); setEditingConnector(false); setShowPlane(true); }} cancelDraw={cancelDraw} busy={!!busy} radius={radius} offset={offset} tilt={tilt} turn={turn} setOffset={setOffset} setTilt={setTilt} setTurn={setTurn} reset={resetCut}/>}
        </>}</div>
        <div className="build-footer">{result ? <><button className="primary full" disabled={!!busy} onClick={() => void exportResult()}><ArrowDownToLine size={17}/>Exportar peças <span>ZIP</span></button><button className="text-button centered" disabled={!!busy} onClick={restore}><ArrowLeft size={14}/>Voltar e ajustar corte</button></> : <><div className="build-caption"><span className={hasCut ? 'ready-dot' : 'idle-dot'}/>{drawing ? 'Desenhe sobre a região desejada' : editingSurface ? 'Conclua a edição dos pontos para construir' : connectorEditActive ? 'Conclua a edição do pino para construir' : canBuild ? 'Confira a prévia antes de construir' : hasCut ? 'Conclua ou remova os cortes sem traço' : 'Desenhe um traço para continuar'}</div><button className="primary full" disabled={!canBuild || !!busy} onClick={() => void build()}><Layers size={17}/>Construir peças<ArrowRight size={16}/></button><p>A geometria só muda nesta etapa.</p></>}</div>
      </aside>
    </div>
    <footer className="statusbar"><span><span className="status-dot"/> {busy ?? 'Estúdio pronto'}<span className="status-divider">/</span>{model.demo ? 'Demonstração' : 'Arquivo local'}</span><span>Sem Blender. Sem upload.<span className="status-divider">/</span>Cut3D Studio · 0.2</span></footer>
    {dragging ? <div className="drop-overlay"><Upload size={44}/><h2>Solte seu modelo aqui</h2><p>STL ou 3MF · até 150 MB</p></div> : null}
    {help ? <div className="modal-backdrop" onClick={() => setHelp(false)}><section className="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={event => event.stopPropagation()}><button autoFocus className="icon-button modal-close" aria-label="Fechar ajuda" onClick={() => setHelp(false)}><X size={20}/></button><span className="eyebrow">UM NOVO COMEÇO</span><h2 id="help-title">Da escultura ao fatiador.</h2><p>Importe um STL ou 3MF, enquadre a região e clique em Desenhar corte livre. Arraste um traço de uma borda à outra, gire a vista para conferir o alcance e ajuste frente, profundidade e espessura. Os pontos verdes permitem corrigir a curva. Clique em Construir peças quando a faixa atravessar a região. Depois, inspecione o resultado e exporte o ZIP com os arquivos STL.</p><p>STL não armazena unidades: este protótipo interpreta seus valores como milímetros. Confira as dimensões no painel esquerdo. Use Salvar plano de corte antes de sair; para restaurar, importe o mesmo modelo e clique em Restaurar plano salvo.</p><p>Malhas abertas ou inválidas podem ser recusadas pelo motor. Nenhuma reparação que altere detalhes é aplicada silenciosamente. O traço livre é prolongado na direção da vista até a profundidade escolhida. Adicione vários cortes e selecione cada um na lista para editar seus pontos e encaixes. Os cortes são construídos na ordem da lista. Se a faixa não soltar uma peça, a construção é recusada e o original permanece intacto.</p><button className="primary full" onClick={() => setHelp(false)}>Voltar ao estúdio <ArrowRight size={16}/></button></section></div> : null}
  </div>;
}
