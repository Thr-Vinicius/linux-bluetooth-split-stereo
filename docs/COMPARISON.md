# Comparação A–B–A proposta — até dez minutos, incluindo retorno

**Preparação somente. Não executar sem autorização específica. PR #1 em rascunho.**
A = instalação original, B = candidato identificado por commit e hashes.
A suspeita inicial de separação defeituosa foi retirada após comparação do usuário
com um fone estéreo convencional. Não há evidência suficiente desse defeito e não
se modificaram fase, panorama, ganho ou compensação para corrigi-lo.
O objetivo é verificar consistência e recuperação, sem presumir superioridade.

## Antes de pedir autorização

- Confirmar os dois dispositivos conectados, carregados, mesmo perfil/codec e
  saídas únicas. Não reconectar, reiniciar serviços ou executar resync.
- Conferir hashes e backups frescos dos originais, serviço/PID/freezer/enable,
  argumentos e owner_module do único null sink, canais/volumes/mute, padrão,
  dispositivos, grafo e links, preset/rota EasyEffects e aplicativos/MPRIS.
  Estado diferente do backup antigo exige nova captura; não sobrescrever mudanças
  legítimas com uma cópia histórica. A [política de identidade](TRIAL-IDENTITY.md)
  valida MAC, propriedades, módulo e processo; índices/seriais e níveis anteriores
  são apenas auditoria. Capturar os valores atuais antes da intervenção e fixar
  essas identidades somente durante a janela.
- Preparar diretório candidato separado e token único; AUTO_DEFAULT=false,
  diagnóstico nativo ativo. Fixar opções, trecho, níveis, controle de volume,
  processamento e caminho aplicativo → EasyEffects → split para A e B.
- Usar o [supervisor integrado](TRIAL-SUPERVISOR.md), testado de ponta a ponta, e revalidar seu controle conforme
  [ROLLBACK.md](ROLLBACK.md). A biblioteca não inicia ensaios. Exigir controle do
  mesmo contexto que criou os processos e atendimento do pedido por arquivo.
  Demonstrar recuperação se o candidato falhar; não confiar em PID salvo numa
  chamada efêmera. Sem controle/retorno comprovados, não iniciar.
- Confirmar que o watchdog pode ser congelado e retomado no mesmo PID sem flag
  de resync pendente. Não pará-lo/iniciá-lo: sua partida pode normalizar volumes.
- Combinar material e disponibilidade do usuário, notificações e interrupção por
  falha. A autorização deverá cobrir freeze/thaw específico, mute temporário,
  substituição somente do null próprio e restauração das rotas/níveis capturados.
  Não inclui instalação, reconexões, reinício global ou controle do player.

## Janela e limites

Cronômetro monotônico e guarda começam em ARMED, **antes da primeira intervenção**,
incluindo a breve avaliação A inicial (até 30 s para enviar o pedido de troca). Reservar
quatro minutos para retorno e conferência. O usuário pode encerrar antes. Avisar
antes do encerramento normal; iniciar retorno até o minuto seis, mesmo sem resposta.
Não aguardar autorização adicional para cumprir o prazo já autorizado.

| Minuto máximo | Ação |
| --- | --- |
| 0–0,5 | A: usuário reproduz referência conhecida e trecho escolhido; registrar audição e grafo. |
| 0,5–2 | Congelar somente o watchdog identificado, confirmar frozen, mute temporário; remover exclusivamente o null confirmado. Iniciar B com grupo/token/ledger. |
| até 30 s da partida B | Exigir virtual FL/FR, filhos MONO esquerdo/direito, destinos/canais/links corretos, ROUTED e ausência de reinícios/erros. Qualquer falta: retorno imediato. |
| 2–4 | Avisar prontidão; usuário inicia os mesmos materiais. Observação passiva e avaliação. Pequenos ajustes voluntários no mesmo controle, se confortáveis. |
| 4–6 | Avisar encerramento; terminar B e executar retorno verificado. Se concluído, usuário compara A novamente com o mesmo trecho. |
| 6–10 | Reserva exclusiva para recuperação, conferência e registros; não prolongar B nem começar novo teste. |

Não insistir com novas partidas, reconexões, resync ou ajustes de codec. Perda de
componente, ruído forte, nível inesperado, desconexão espontânea ou controle perdido
exigem retorno imediato. Registrar a falha, sem tentar mascará-la. O minuto dez
é o limite, não a hora de começar a recuperação. Se a guarda ou a margem disponível
não puderem garantir essa janela antes da troca, cancelar a intervenção.

## Referências e roteiro simples

Gerar em diretório novo com `python3 tools/make-references.py --output DIRETORIO`.
São WAV estéreo PCM16, 48 kHz, 440 Hz, pico 0,025 (-32,04 dBFS), fade de 30 ms.
Não há reprodução automática. Esse pico baixo não substitui nível confortável
confirmado pelo usuário; não aumentar volumes para compensar silêncio.

- `left.wav`: 4 s, tom somente FL entre 1 e 3 s.
- `right.wav`: 4 s, tom somente FR entre 1 e 3 s.
- `center.wav`: 4 s, amostras idênticas e em fase nos canais entre 1 e 3 s.
- `sequence.wav`: 12 s, esquerda 1–3 s, direita 5–7 s, centro 9–11 s.

Ouvir a mesma sequência uma vez em A, B e A final. Não julgar separação por música
ou fala sem conteúdo de canais conhecido. A referência central é um teste perceptivo;
a geometria/ajuste e o processamento podem influenciar a imagem percebida.
Em seguida, usar exatamente o mesmo trecho curto de vídeo/música preferido.
O usuário controla início, pausa e seleção; o observador não comanda o player.

Perguntas para cada etapa: esquerda e direita corretas? Centro estável? Atraso entre
fones ou imagem/áudio? Cortes, estalos, distorção ou deriva? Pipocada no ajuste de
volume, em qual lado e controle? Houve necessidade de ressincronização? O aplicativo
continuou reproduzindo após a troca e o retorno? Responder “não avaliado” quando
faltarem tempo ou referência; uma resposta parcial não aprova o restante.

| Etapa / horário | Referência e trecho | L/R | Centro | Atraso fones / vídeo | Cortes / estalos | Volume: controle, antes/depois, ruído | EasyEffects / resync / aplicativo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A inicial | | | | | | | |
| B | | | | | | | |
| A final | | | | | | | |

## Retorno e critérios

O proprietário original atende `return.request` ou o prazo. Confere contexto,
muta saídas selecionadas, encerra grupo identificado e espera sumirem nós, streams,
portas, links e clientes candidatos por ID+serial. Só então recria/confirma o null
com argumentos/owner_module corretos, restaura níveis/mute/padrão e links próprios,
rota EasyEffects e fluxo sobrevivente identificado. Retoma o mesmo watchdog e
confere novamente recursos, estado do serviço, dispositivos/perfil e hashes.

Capturar aplicativos imediatamente antes do retorno, inclusive o vídeo iniciado
após o snapshot inicial. Conferir saída, mute, corked e MPRIS. Fluxo recriado deve
ser declarado; não mover um novo fluxo por semelhança de nome nem emitir play para
esconder interrupção. Se precisar, usuário escolhe manualmente a saída. Retorno
com divergência/estado desconhecido permanece FAILED ou possui limitação explícita;
não usar apenas um arquivo “done” como prova. Ver [contrato](ROLLBACK.md).

Separar no relatório: (1) prontidão/links/processos/níveis e tempo medidos por
software; (2) percepções com horário informadas pelo usuário; (3) itens não avaliados.
ROUTED não mede alinhamento acústico, milissegundos, drift, rádio ou todo corte breve.
Não aprovar qualidade acústica sem relato. Pipocadas seguem o diagnóstico separado
em [VOLUME-ARTIFACTS.md](VOLUME-ARTIFACTS.md), sem correção especulativa.

## Consistência entre conexões: outra etapa

Um A–B–A na mesma conexão limita diferenças imediatas, mas não demonstra redução
da variabilidade histórica após conexões. Um resultado favorável permite propor,
sem executar, janelas separadas com amostra previamente combinada (por exemplo,
pelo menos três sessões por arquitetura), ordem alternada e condições registradas.
Não excluir partidas ruins ou falhas. Reportar contagens, duração e todas as
ocorrências; amostra pequena continua exploratória. Reconexões manuais exigem
escopo e autorização separados. Captura acústica sincronizada também exige
preparação própria. Nenhuma arquitetura é declarada superior nesta preparação.

## Preparação com EasyEffects ocioso

A preparação pode registrar IDLE_UNPROVEN quando não há reprodução efetiva e os links estão completamente ausentes. Isso não aprova roteamento ou processamento ainda não demonstrados. Antes da troca, o usuário inicia A pelo caminho normal; exigir ACTIVE_VERIFIED na captura final antes de qualquer freeze. Não criar ligações para satisfazer o preflight. Se A continuar ociosa ou o caminho estiver errado/incompleto, encerrar sem intervenção. Ver [revalidação](TRIAL-EASYEFFECTS.md).
