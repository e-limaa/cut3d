# Cut3D 4.3.15 — corte simples com preservação da malha

O Cut3D permite marcar cortes diretamente no modelo, como um golpe de Fruit Ninja, planejar vários cortes sem alterar a malha e construir as peças somente ao clicar em **Build Draft · Construir Peças**.

## O que mudou na série 4.x

- Nenhum corte surge automaticamente no centro do modelo.
- O gesto pode começar e terminar fora da silhueta.
- A marca do Draft é um overlay leve; não existe tubo, aro ou booleano sendo recalculado enquanto você desenha.
- O primeiro trecho visível atingido pelo mouse define a peça e a profundidade local. Um braço na frente do tronco não transforma o corte em um plano infinito através do corpo.
- **Reto** mantém uma linha reta na vista. **Curvo** preserva o perfil desenhado.
- O corte curvo passa a ser uma superfície fechada, com perímetros independentes na frente e no verso da peça.
- **Editar superfície ponto a ponto** abre o editor leve do Draft: a superfície fica translúcida, os pontos de controle aparecem sobre as duas faces e a malha original continua intacta.
- Cada ponto da frente e do verso é projetado individualmente na casca real do modelo. Pontos de silhueta usam a posição mais próxima da malha para não ficarem flutuando.
- Um gesto reto pode começar e terminar longe do corpo: a marca final é aparada automaticamente entre a entrada e a saída da região atingida.
- **Dimensionar pino** seleciona o encaixe e ativa as alças de escala do Blender; o pino fica ancorado no centro de área e projetado exatamente sobre a superfície de corte. A escala permanece válida ao recentralizar e no Build.
- Todos os cortes são acumulados no Build antes da separação. Assim, dois cortes podem soltar um braço que também encosta no quadril, exatamente como um planejamento por rascunho deve funcionar.
- No Build, a superfície de corte é prolongada internamente para além das duas faces da casca. A marca continua aderente ao corpo, mas a operação final não termina tangente à malha nem deixa pontes invisíveis.
- Se o Boolean exato não soltar a região em uma malha densa ou problemática, o Build elimina somente as faces que ainda atravessam a costura, separa os lados por conectividade e tampa os novos contornos. Não há Voxel Remesh nem reconstrução do corpo.
- As tampas permanecem como faces contínuas, seguindo o conceito simples dos cutters open source. Isso evita diagonais sobrepostas e preserva todos os detalhes fora da faixa do corte.
- Depois dos pinos e soquetes, somente os contornos criados na vizinhança da costura são fechados; defeitos preexistentes longe do corte não são alterados.
- O modo Resultado bloqueia alterações acidentais no Draft até o usuário voltar ao planejamento; ao voltar, o original é selecionado e todos os resultados antigos são ocultados.
- Um encaixe só é construído quando as duas peças candidatas estão próximas da mesma marca. Ilhas ou estátuas desconectadas no mesmo objeto nunca são usadas como o outro lado do pino.
- Cada corte e cada encaixe é validado antes de substituir a etapa anterior. Se o Boolean perder a peça principal ou criar arestas inválidas, somente essa operação é desfeita; fragmentos microscópicos nunca são publicados como peças.
- O resumo do Build distingue peças que já eram desconectadas de novas separações. Uma fenda que ainda não soltou o membro é informada claramente como ligação física restante.
- O original é preservado; **Voltar ao planejamento** restaura as marcas editáveis.

## Instalação

1. No Blender, abra `Edit → Preferences → Add-ons`.
2. Escolha `Install from Disk…`.
3. Selecione `Cut3D_addon.zip`.
4. Ative **Cut3D — Corte & Pinos para Impressão 3D**.
5. No Viewport 3D, pressione `N` e abra a aba **Cut3D**.

## Fluxo de uso

1. Selecione a malha que deseja cortar.
2. Escolha **Modo Fácil** ou **Modo Rascunho**.
3. Clique em **Reto** ou **Curvo**.
4. Pressione o mouse dentro ou fora do modelo, atravesse somente a região desejada e solte.
5. Repita para planejar outros cortes. Até aqui, a malha original não é modificada.
6. Em um corte curvo, clique em **Editar superfície ponto a ponto**, gire a câmera e ajuste as bordas da frente e do verso.
7. Ajuste pino, lado A/B, formato e folga, se necessário.
8. Clique em **Build Draft · Construir Peças**.

Um único corte pode abrir uma fenda sem soltar uma peça quando existe outro caminho físico ligando-a ao modelo — por exemplo, a mão encostada no quadril ou os dois pés unidos pela base. Nesse caso, adicione o segundo corte necessário e execute o Build novamente.

## Controles

- Arrastar com o botão esquerdo: desenhar o corte.
- `Esc`: cancelar o desenho ou reposicionamento.
- **Reposicionar marca**: colocar o corte em outro ponto da superfície.
- `G` / `R`: mover ou girar o controle selecionado.
- **Voltar ao planejamento**: ocultar o resultado e recuperar o Draft.

No editor da superfície curva:

- Arrastar com o botão esquerdo: mover um ponto; com snap ligado, ele acompanha a malha.
- Botão do meio: girar a câmera para alternar entre frente e verso.
- `Ctrl` + clique esquerdo: adicionar um ponto ao trecho mais próximo.
- `X` ou `Delete`: remover o ponto selecionado.
- `S`: ligar ou desligar o snap na superfície.
- `Ctrl+Z` / `Ctrl+Shift+Z`: desfazer/refazer.
- `R`: restaurar o perímetro que existia ao abrir o editor.
- `A`: reajustar todos os controles à malha.
- `Enter`: confirmar; `Esc` ou botão direito: cancelar.

Para dimensionar o pino, clique em **Dimensionar pino** e arraste as alças coloridas. Pressione `S` para escala uniforme. As alças X/Y alteram a largura e a alça Z altera o comprimento.

## Encaixes e exportação

Formatos de encaixe: cilindro, quadrado, sextavado e rabo de andorinha. Há presets de folga para PLA, PETG, ABS/ASA, resina e encaixe solto. As peças podem ser exportadas em STL, OBJ ou 3MF.

## Validação

A versão 4.3.15 foi verificada no Blender 5.1.2 com:

- múltiplos cortes retos;
- corte curvo com pino e soquete;
- corte local sem atingir uma geometria sobreposta atrás;
- dois cortes acumulados necessários para abrir uma malha em forma de loop;
- calibração em cenas métricas e modelos STL em milímetros;
- modelo real com aproximadamente 2 milhões de faces, separado em cabeça e corpo sem modificar o original.
- superfície curva com frente e verso independentes, suavização contínua e Build usando exatamente a forma editada.
- projeção de todos os controles curvos na casca de uma esfera e no modelo real;
- aparo de um gesto reto iniciado centenas de pixels fora do modelo;
- escalas X/Y/Z do pino preservadas pela recentralização e usadas pelo Build.
- persistência da posição do corte e do centro do pino depois de salvar/reabrir um arquivo com os controles técnicos ocultos.
- cena real com 3.112.331 faces e três cortes curvos: três peças principais construídas, todas visíveis, sem ilhas microscópicas dos booleanos.
- cena real com duas figuras e 3.112.331 faces no alvo: um único corte curvo separou cabeça e corpo, preservou a segunda figura e produziu três peças com pino/soquete; o original permaneceu oculto e recuperável.
- auditoria da cena real: a cabeça terminou com zero bordas abertas e zero arestas com mais de duas faces; o corpo reteve somente as 27 bordas e 19 arestas problemáticas que já existiam no arquivo original, sem criar novos defeitos.

Para melhores resultados, use malhas fechadas e sem auto-interseções. Aplique a escala quando o painel mostrar o aviso correspondente.
