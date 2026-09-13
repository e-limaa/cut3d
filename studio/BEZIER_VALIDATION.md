# Reconstrução da edição Bézier — Cut3D

Implementação em `fix/surface-bezier`, baseada no commit `e24f7dc`, em worktree isolado. Sem merge na main, push ou publicação na Vercel.

## Comportamento implementado

- Todos os controles originais continuam sendo âncoras. Seus índices são estáveis; amostras extras da curva não se tornam controles.
- Dados novos em `FreeCut.bezier` guardam âncoras 3D, alças independentes por lado e segmentos. A interface não usa `penCurves` 2D nem a reconstrução Pen legada.
- Curva é opcional por ponto. Uma alça altera seu segmento; uma âncora leva suas duas alças e altera somente os segmentos adjacentes. O lado oposto mantém as mesmas âncoras e a mesma geometria, com subdivisão linear quando necessária para a correspondência.
- A prévia e o construtor consomem as mesmas rails avaliadas. A posição do pino permanece parametrizada pelas âncoras originais, inclusive na seleção pelo gizmo.
- Seleção verifica a primeira superfície ao longo do raio da câmera. Alças de âncoras ocultas são escondidas. Alças pequenas são ampliadas na tela, com conversão inversa no arraste.
- Arraste conserva a diferença entre o cursor e o centro do marcador e usa uma base imutável. Alças usam um plano fixo definido no início do gesto.
- Escape, pointercancel e perda de foco revertem o gesto. Pointer-up confirma. Ponteiros diferentes são ignorados e a captura é liberada ao sair da edição.
- A área invisível do botão flutuante não intercepta os controles.

## Verificação executada

- `npm.cmd run build`: passou. Permanecem os avisos existentes de tamanho do bundle e externalização de `node:module` no Manifold.
- `studio/node_modules/.bin/vitest.cmd run studio/src --reporter=dot`: 72 testes passaram em 10 arquivos, incluindo 11 novas regressões de Bézier, persistência, pino e ciclo de cancelamento.
- Modelo real: 1.972.436 triângulos, binários locais de diagnóstico e `cut3d-plano (5).json`. Foram ativadas curvas e movidas alças em 37 âncoras de cada lado: 74/74 operações aceitas, 74/74 superfícies construíveis. Âncoras, segmentos distantes e lado oposto foram comparados; amostras curvas permaneceram na superfície dentro da tolerância do teste.
- Construção Manifold desse modelo após deslocar uma alça em 0,03 mm: duas peças. Sem pino: 1.212.524 e 777.290 triângulos. Com pino hexagonal (1,9 mm × 2,6 mm, folga 0,25 mm): 1.212.476 e 776.878 triângulos. Todas as arestas das saídas tinham exatamente duas incidências.
- Navegador: modelo real importado, corte próximo ao pescoço, seleção/curva e inspeção por rotação. No busto de demonstração: arraste de ambas as alças, transporte das alças com a âncora, curva/reto, extremidade, restauração e alternância entre dois cortes.
- Os JSONs efetivamente baixados pela interface confirmaram alça direita alterada e esquerda intacta. Depois do arraste da âncora 19, apenas essa âncora mudou na frente; nenhuma mudou no verso. Erro de translação das alças: 0 e 8,88e-16.
- No build de produção servido localmente, o plano com dois cortes e Bézier foi restaurado e construído pela interface: três peças, com resultado visual inspecionado.

## Limites e pendências explícitas

Curvas são avaliadas em oito subdivisões por segmento, com projeção local na malha e verificações de avanço ao longo do segmento, degeneração e distância de projeção. Movimentos que criam laços locais ou projeção excessiva são recusados mantendo o último resultado válido. Isso não é uma garantia geométrica universal para qualquer malha fina, côncava ou autointersectante. A validação completa do sólido continua na construção, nunca a cada pointermove.

Não há inserção/remoção de âncoras nesta mudança, nem suavização global. Planos antigos preservam suas rails como base; alças legadas não são reaplicadas automaticamente. O teste real usa perturbações pequenas e um plano específico; não comprova todos os gestos arbitrários.

Cancelamento foi validado automaticamente pelo mesmo controlador de eventos usado no editor; não houve validação manual completa de Escape no meio de um gesto físico no navegador. A seleção traseira tem cobertura geométrica automatizada e inspeção de ocultação pela câmera; a matriz completa de arrastes traseiros no modelo real ainda merece uma rodada manual.

O servidor Vite de desenvolvimento deste worktree com dependências compartilhadas entregou conteúdo incorreto para o WASM durante a construção. A prévia do bundle de produção funcionou e construiu três peças. Nenhuma configuração de deploy foi modificada para contornar esse problema.

## Reproduzir teste real

Na raiz do worktree, em PowerShell:

```powershell
$env:CUT3D_REAL_DIAGNOSTICS='C:/Users/dulim/Downloads/Cut3D/studio/diagnostics'
$env:CUT3D_REAL_PLAN='C:/Users/dulim/Downloads/cut3d-plano (5).json'
$env:CUT3D_REAL_BUILD='1'
$env:CUT3D_REAL_PIN='1'
.\studio\node_modules\.bin\vitest.cmd run studio/validation/surface-bezier.real.test.ts --reporter=dot
```

O teste real é opt-in. O modelo e os planos privados não estão incluídos no commit.
