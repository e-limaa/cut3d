# Cut3D — contexto, arquitetura e status

## Objetivo

Construir um add-on do Blender para preparar miniaturas e esculturas para impressão 3D com uma experiência próxima ao CatPin:

- o usuário desenha onde deseja cortar;
- o planejamento permanece leve e não destrutivo;
- vários cortes podem ser revisados antes da construção;
- a geometria só é alterada em **Build Draft**;
- pinos e soquetes usam folgas adequadas ao material;
- o modelo original permanece recuperável.

## Problemas que motivaram a reescrita

As versões iniciais criavam um plano ou aro no centro do objeto e tentavam fazê-lo acompanhar toda a superfície. Isso causava quatro falhas visíveis: controles gigantes, cortes alcançando tronco e membros distantes, preview pesado e diferença grande em relação ao CatPin.

A série 4.x abandona esse modelo. O corte agora nasce exclusivamente de um gesto do usuário e tem largura e profundidade finitas.

## Arquitetura atual — versão 4.3.15

### `draft_engine.py`

- operador modal que registra todo o gesto 2D, inclusive os trechos fora do modelo;
- ray casting somente ao soltar o mouse;
- identificação da primeira casca visível e de sua saída para limitar a profundidade;
- projeção do gesto em um plano estável da vista;
- overlay GPU de largura constante, sem tubos ou booleanos no Draft;
- armazenamento do perfil, profundidade, ponto-semente e matriz de cada corte;
- superfície curva definida por dois perímetros independentes (frente/verso), com migração automática dos cortes 4.1;
- editor modal ponto a ponto com snap na malha, rotação livre da vista, inserção/remoção de pontos, desfazer/refazer e cancelamento seguro;
- ray casting independente para cada controle frontal e traseiro, com fallback na superfície mais próxima nos pontos tangentes da silhueta;
- comando para reajustar toda a superfície à casca do modelo sem executar booleanos;
- recorte do gesto 2D à primeira e à última interseção da região visível atingida;
- overlay translúcido e suavizado que mostra toda a superfície antes de qualquer operação pesada;
- edição, duplicação, reposicionamento e controle independente do pino;
- pino ancorado no centro de área da superfície inteira do corte, com rotação alinhada à superfície, posição/rotação bloqueadas e escala livre no gizmo;
- transformação persistente dos controles usada no Draft e no Build, mesmo depois de reabrir um `.blend` com a coleção técnica oculta ou desligada.

### `cut_math.py`

- simplificação de polilinhas;
- normalização de perfis monotônicos;
- interpolação e distância assinada do perfil;
- reamostragem e suavização Catmull-Rom dos perímetros editáveis;
- avaliação da altura na superfície regrada entre frente e verso;
- expansão segura do alcance do gesto.

### `cutter_engine.py`

- cria um volume de corte finito e estanque a partir da superfície regrada editada;
- prolonga esse volume internamente além da casca somente durante o Build, evitando booleanos tangentes e pontes residuais sem alterar a marca do Draft;
- aplica todos os cortes somente no Build Draft;
- acumula cortes antes de separar componentes, permitindo que dois cortes soltem um membro ligado ao corpo em dois pontos;
- separa as peças pela conectividade real após todos os cortes;
- aplica conectores apenas depois de ambos os lados existirem;
- preserva o modelo original e substitui resultados anteriores ao reconstruir.
- contabiliza as ilhas existentes antes do Build para diferenciar uma nova separação de componentes que já estavam soltos;
- limita a escolha dos dois lados de um conector à vizinhança da própria marca, impedindo pinos entre figuras desconectadas;
- mantém Resultado e Planejamento como estados exclusivos: resultados antigos nunca ficam sobrepostos ao original nem ativos como alvo invisível.
- quando o Boolean exato deixa pontes topológicas em uma malha densa, classifica a superfície pela distância assinada do corte, remove somente as faces residuais da região atingida e extrai os dois componentes principais;
- fecha somente os novos contornos da costura com faces contínuas, sem Voxel Remesh e sem reconstruir a superfície distante;
- limita o fechamento à vizinhança de cada corte, preservando aberturas e defeitos já existentes em outras regiões;
- evita triangulação topológica das tampas para não reutilizar diagonais internas de scans densos como arestas de três faces;
- remove componentes microscópicos fechados depois da aplicação dos conectores.

### `connectors.py`, `properties.py`, `ui_panel.py` e `exporter.py`

- conectores cilíndrico, quadrado, sextavado e rabo de andorinha;
- presets de material e folga;
- Modo Fácil e Modo Rascunho no N-Panel;
- exportação em STL, OBJ e 3MF.

## Comportamento esperado

1. Selecionar a malha.
2. Clicar em **Reto** ou **Curvo**.
3. Arrastar como um golpe, começando fora da silhueta se desejado.
4. Ver apenas uma marca leve sobre a região atravessada.
5. Planejar e editar quantos cortes forem necessários.
6. Em cortes curvos, abrir **Editar superfície ponto a ponto**, ajustar a frente e girar a câmera para ajustar o verso.
7. Clicar em **Build Draft · Construir Peças**.
8. Voltar ao planejamento sem perder as marcas.

Se uma região possuir outra ligação física — mão no quadril, pés na mesma base ou um loop fechado — um único corte não pode produzir duas peças. O Build mantém a fenda aplicada e os cortes seguintes completam a separação.

## Validações concluídas

- compilação de todos os módulos Python;
- fluxo principal com dois cortes e três peças;
- corte curvo com pino e soquete;
- escopo local em braço;
- oclusão: corte da casca frontal sem cortar a geometria traseira;
- dois cortes acumulados em uma malha fechada em loop;
- calibração em metros e em STL/mm;
- instalação e ativação no Blender 5.1.2;
- modelo real com 1.994.126 faces: Build gerou duas peças (cabeça e corpo) e preservou o original.
- superfície curva assimétrica com perímetros independentes: preview, avaliação espacial e Build produziram duas peças válidas.
- instalação da versão 4.3.0 e abertura do editor modal diretamente no modelo real pelo MCP do Blender.
- modelo real: 20/20 controles projetados sobre a casca, com distância máxima medida de aproximadamente 8,6e-8 unidades.
- gesto reto real: 1.395 px desenhados foram aparados aos 160 px ocupados pela peça atravessada.
- gizmo de escala do pino ativado pelo painel e escala relativa preservada após recentralização.
- regressão de Build em superfície curva aderente: o cortador estanque atravessou integralmente uma esfera e produziu duas peças válidas.
- cena real do usuário com 3.112.331 faces e três cortes curvos: Build 4.3.1 finalizou com três peças principais (1.541.818, 947.047 e 624.069 faces), todas visíveis; seis ilhas microscópicas de booleano foram descartadas antes da aplicação dos conectores.
- regressão 4.3.2: sair de Resultado oculta todas as peças geradas, seleciona o original e reabilita o planejamento mesmo quando a lista de cortes está vazia.
- regressão 4.3.2: duas ilhas distantes em lados opostos do plano não formam um par de pino/soquete.
- regressão 4.3.10: cena real de 3.112.331 faces com duas figuras e um corte curvo gerou três peças visíveis; cabeça e corpo ficaram separados, a segunda figura permaneceu intacta e o original continuou recuperável.
- regressão 4.3.10: a cabeça terminou com zero bordas abertas e zero arestas de três ou mais faces; o corpo não ganhou nenhuma abertura ou aresta problemática além das já presentes na fonte.
- regressão 4.3.10: o Build real produziu 945.970 faces no corpo e 621.118 na cabeça, contra mais de 5,2 milhões de faces na tentativa antiga com voxelização.
- regressão 4.3.12: um pino propositalmente deslocado/rotacionado voltou ao centro de área do corte sem perder a escala feita pelo usuário.
- regressão 4.3.12: o Build usa a matriz persistente do corte; um Empty técnico sem `matrix_world` atualizado após reabrir o arquivo não desloca mais corte nem conector para a origem.
- regressão 4.3.12: o centro de área é projetado novamente na superfície curva; no modelo real, a origem do pino coincidiu com o corte dentro de aproximadamente 1,1e-9 unidade.
- regressão 4.3.13: cada Boolean do Build é transacional; perda anormal de faces ou novas bordas inválidas desfaz somente aquele passo e aciona o corte topológico local.
- regressão 4.3.13: o Build recusa resultados com perda anormal da malha original, impedindo resíduos microscópicos de aparecerem como peças.
- regressão 4.3.13: `Felix.blend`, com 358.932 faces e três cortes curvos, deixou de gerar 11 resíduos e passou a produzir três peças reais, todas fechadas, com os três encaixes aplicados.
- regressão 4.3.13: pinos e soquetes também são transacionais; faces opostas duplicadas na união são removidas localmente e qualquer conector que ainda piore a topologia é desfeito.
- regressão 4.3.14: a conclusão topológica é decidida por corte; cortes retos pendentes continuam sendo acumulados mesmo quando um corte curvo já separou outra peça.
- regressão 4.3.14: no `Felix.blend`, um corte curvo e dois retos produziram três peças fechadas e 3/3 encaixes, todos com deslocamento central zero.
- regressão 4.3.15: cada kerf precisa preservar ao menos 85% das faces recebidas e pode criar no máximo uma nova separação; a falha que mantinha exatamente metade de uma malha simétrica agora é desfeita antes do próximo corte.
- regressão 4.3.15: o Build é atômico: se qualquer corte ativado não atravessar o alvo, nenhum resultado parcial é publicado e o modelo original permanece visível.
- regressão 4.3.15: o resultado final não pode conter mais separações que cortes aplicados nem fragmentos abaixo de 32 faces em scans densos.
- toda a suíte de corte reto/curvo, pino/soquete, escopo local, oclusão, múltiplos cortes, estado do resultado, escala e recarga do addon passou no Blender 5.1.2.

## Estado atual

- Versão: **4.3.15**.
- Pacote instalável: **`Cut3D_addon.zip`** na raiz desta pasta.
- Blender validado: **5.1.2**; `bl_info` mantém suporte declarado a 3.6+.
- O processamento pesado é deliberadamente concentrado no Build. No modelo real de quase 2 milhões de faces, a construção levou cerca de 47 segundos; o desenho do Draft permaneceu leve.
- Na cena de 3,1 milhões de faces com três cortes e conectores, a validação completa levou cerca de 169 segundos; o Draft continuou não destrutivo e responsivo.
- O editor curvo segue o comportamento observado no vídeo do CatPin: superfície provisória, controles de perímetro na frente e no verso e confirmação separada da construção geométrica.
- O resultado real verificado está salvo em **`Cut3D_result_verified.blend`**; o Build 4.3.12 levou aproximadamente 90 segundos na malha de 3,1 milhões de faces.
- A cena de regressão com três cortes está salva em **`Felix_Cut3D_verified.blend`**; o Build 4.3.13 levou aproximadamente 30 segundos e terminou com 3 peças e 3/3 encaixes.
- A combinação de um corte curvo com dois retos está salva em **`Felix_Cut3D_straight_verified.blend`**; o Build 4.3.14 levou aproximadamente 34 segundos.
