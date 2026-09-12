# Cut3D Studio

Primeira base de um produto web independente do Blender para preparar modelos 3D para impressão. O addon na pasta acima é apenas referência histórica: esta aplicação não importa Python nem exige Blender instalado.

## Executar

Requer Node.js 22 e npm.

```sh
npm install
npm run dev
```

Abra o endereço local mostrado pelo Vite. Para verificar: `npm run build` e `npm test`.

## Incremento disponível

- Importação local de STL e 3MF com geometria, sem upload. Cores, texturas e configurações de fatiamento não são preservadas.
- STL interpretado em milímetros; 3MF convertido para milímetros. Pacotes com unidades mistas são recusados.
- Visualização em 3D, enquadramento, malha e gizmo de orientação.
- **Corte livre como fluxo principal:** desenhar um traço aberto na vista ortográfica, editar pontos e ajustar frente, profundidade e espessura removida.
- Faixa de corte curva com alcance finito. O perfil segue o desenho inclusive quando retorna na horizontal; a profundidade inicial é estimada pela primeira casca visível e deve ser conferida pelo usuário.
- A construção subtrai a faixa do modelo e publica peças somente se houver uma nova separação. Sulcos rasos ou ligações físicas restantes mantêm o original e produzem um aviso.
- Corte plano continua disponível como ferramenta auxiliar.
- Construção real pelo Manifold em Web Worker, separação de componentes e rejeição explícita de entradas inválidas.
- Inspeção das peças afastadas; exportação ZIP com STL binário por componente. A prévia afastada não altera coordenadas exportadas. Modelos são centralizados ao importar.
- Busto procedural de demonstração incluído, sem arquivos externos.

## Limites explícitos

O corte livre atual é um **traço 2D aberto prolongado em profundidade**, com largura finita: remove material na espessura indicada. A vista ortográfica mantém o desenho e a faixa alinhados. O alcance é local, mas não reconhece semanticamente braços, roupas ou outras regiões; qualquer malha dentro da faixa pode ser atingida. A estimativa inicial de profundidade é uma ajuda, não uma garantia.

Ainda não há contorno fechado, frente/verso com formatos independentes, corte tridimensional arbitrário ao redor da escultura, recuos, encaixes, múltiplos cortes acumulados ou salvamento de projetos. Abrir/recarregar a página perde o planejamento. Modelos abertos ou não-manifold podem ser recusados. O tamanho máximo de arquivo é 150 MB; desempenho em scans densos ainda precisa ser medido. O carregamento e a compactação de exportação ainda ocorrem na interface; o corte roda em worker.

## Verificação desta etapa

Testes cobrem superfícies de separação não planas, caminhos que retornam em X, alcance local preservando uma peça atrás, recusa de sulcos insuficientes, corte curvo do busto de demonstração, integridade topológica das saídas, preservação do original e encaminhamento da mensagem de corte livre no worker. A compilação de produção inclui o worker e o WASM. A inspeção interativa no navegador permanece pendente: a revisão automática da ferramenta foi bloqueada por falta de créditos.

## Próximas decisões do produto

1. Evoluir o traço extrudado para superfícies livres com frente e verso independentes.
2. Edição sobre a casca ao redor da escultura e inspeção do volume interno.
3. Recuos e encaixes configuráveis sem exigir ferramentas de modelagem.
4. Construção transacional de vários cortes e salvamento de projeto.
5. Validação em modelos reais gerados por IA, conservando detalhes fora da região cortada.

A separação sob uma manga é um caso de validação, não uma restrição de uso. O usuário decide a posição e a forma dos cortes em qualquer modelo compatível.
