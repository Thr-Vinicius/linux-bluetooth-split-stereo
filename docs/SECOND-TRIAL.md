# Segundo ensaio proposto — vídeo normal e observação passiva

**Não executado e ainda sem autorização.** A autorização do primeiro ensaio não
se estende a este. O PR #1 continua em rascunho. Este procedimento não instala
arquivos, não faz merge e não autoriza desconectar os fones.

## Escopo a autorizar posteriormente

Janela máxima de dez minutos **incluindo troca e rollback**, medida por relógio
monotônico desde antes da primeira intervenção. Reservar os dois minutos finais
para restauração. Interromper a etapa de reprodução até o minuto oito. Principal
avaliação: usuário assistir normalmente a um vídeo escolhido por ele, durante
aproximadamente cinco minutos, enquanto o agente somente observa e registra.
Mudanças pequenas de volume são feitas voluntariamente pelo usuário, em nível
confortável, sem normalização dos volumes físicos. Não se emitem estímulos nem
comandos de reprodução/pausa/busca automaticamente.

## Preparação antes de qualquer intervenção

1. Obter autorização explícita para esta janela, incluindo a troca temporária,
   a seleção da saída do EasyEffects se necessária e a restauração das rotas
   exatas afetadas. Confirmar disponibilidade do usuário para ouvir e sinalizar.
2. Preparar diretório candidato **novo**, identificado por commit e hashes,
   sem sobrescrever o candidato nem as evidências anteriores. Config separada:
   alvos reais confirmados, `AUTO_DEFAULT=false`, debug nativo habilitado só no
   candidato. Preservar compensação e demais opções; não mudar duas variáveis.
3. Revalidar backups e comparar originais com o manifesto. Se houver mudança
   legítima desde a captura antiga, criar backup novo; não restaurar cópia antiga
   por cima dela. Capturar estado fresco do serviço, enable, módulo null, perfil/
   codec, volumes por canal/mute, padrão, grafo, rota do EasyEffects e aplicativos.
   Não reutilizar IDs históricos. Exigir um único store `default` metadata.
4. Confirmar controle de parada/início do watchdog específico pela interface de
   serviço local já validada, identificação única do `module-null-sink` antigo e
   rollback limitado ao sink/links próprios. Verificar se o estado salvo do
   watchdog antigo reconhece os dispositivos atuais; não executar sua rotina de
   reconexão no rollback. Se controle ou recuperação não forem verificáveis,
   **não iniciar**. Preparar registro de log e limite temporal independente do
   observador; o observador não é mecanismo de rollback.
5. Combinar trecho com fala e movimentos estéreo conhecidos, mantendo o caminho
   aplicativo → EasyEffects → split. Se não houver referência inequívoca de L/R
   no vídeo, registrar essa parte como inconclusiva; um clipe de canais conhecido
   pode ser avaliado separadamente com autorização. Não inferir exclusividade
   acústica de canais apenas de música genérica.

## Troca, somente depois da autorização

- Iniciar cronômetro e guarda de rollback antes de parar exclusivamente o watchdog
  antigo. Confirmar sua parada; não matar processos por nome.
- Confirmar novamente o ID e argumentos do único null sink `split_lr` e remover
  somente esse módulo. Iniciar o candidato em primeiro plano no diretório novo.
- Exigir um virtual próprio FL/FR, dois filhos MONO próprios, alvos/links corretos,
  ausência de crosswire/erros e estado ROUTED verificado. Se isso não ocorrer em
  até 30 segundos, ou se houver saída do cliente/reinícios repetidos, abortar e
  restaurar imediatamente. Esse é um critério operacional do ensaio, não uma
  correção por timeout no código.
- Usuário confirma/seleciona a saída temporária no caminho do EasyEffects dentro
  do escopo autorizado. Preservar demais rotas específicas. Usuário inicia o vídeo
  e informa tempo inicial, vozes centralizadas, percepção de sincronização e
  transições estéreo. Sem confirmação de som nos dois lados, abortar.
- Executar observador finito de leitura, em arquivo novo, por no máximo o tempo
  restante de reprodução; exemplo, a partir do candidato:

  ```bash
  python3 tools/observe-session.py --config /caminho/novo/config \
    --output /caminho/novo/observacao.jsonl --seconds 300 --interval 5
  ```

  O observador consulta grafo, níveis e perfil/codec. Não mede ondas sonoras, não
  detecta todo corte breve e não cria estímulos. Guardar também stdout/stderr do
  candidato. Registrar anotações auditivas do usuário em uma tabela de horários.
- Usuário faz pequenos ajustes de volume no controle escolhido e informa se houve
  pipocada, lateralidade ou salto inesperado. Registrar controle e níveis. Não
  alterar ganho/codec/preset para tentar corrigir durante a mesma observação.
- Qualquer corte persistente, ruído forte, volume inesperado, reconexão involuntária
  ou perda de controle: encerrar observação e candidato, iniciar rollback imediato.
  Não tentar recuperar por desconexão, reinício global ou mudança de codec.

## Rollback obrigatório e verificação

Encerrar somente o candidato/observador identificados. Recriar o null sink antigo
com seus argumentos frescos e restaurar exclusivamente seus links confirmados.
Não chamar automaticamente scripts antigos que possam reconectar transportes ou
normalizar volumes. Restaurar serviço à atividade anterior, sem alterar enable,
com sua condição de dispositivos conhecidos validada. Se houver risco de
reconexão pelo watchdog antigo, não iniciar o teste antes de resolver esse risco.

Restaurar volumes por canal/mute, padrão e apenas rotas específicas afetadas pela
troca, a partir do snapshot novo. A remoção/recriação do sink pode afetar clientes:
comparar rota, mute e `corked`, registrar qualquer diferença e não enviar comandos
de mídia para disfarçá-la. Se a aplicação exigir seleção manual, o usuário a faz.
Confirmar ambos conectados, mesmo A2DP/AAC, EasyEffects no caminho anterior,
serviços e enable originais, hashes originais iguais e nenhuma instância candidata
restante. Registrar tempo total, erros e resultado antes/depois. Não declarar
rollback integral se qualquer campo permanecer diferente ou desconhecido.

## Critérios de decisão

| Dimensão | Aprovação limitada ao ensaio | Rejeição / inconclusão |
| --- | --- | --- |
| Inicialização | ROUTED com dois filhos, portas/links exclusivos e sem reinícios | Ausência, erro, crosswire ou reinícios |
| Preservação | A2DP/AAC, caminho EasyEffects e volumes independentes preservados | Mudança inesperada ou diferença sem explicação |
| Audição inicial | Usuário confirma ambos os lados, vozes centralizadas e alinhamento satisfatório | Desalinhamento, voz lateralizada ou ausência de confirmação |
| Estéreo | Referência conhecida percebida no lado correto e grafo correspondente | Lado trocado; sem referência conhecida, inconclusivo |
| Reprodução | Nenhum corte, estalo ou deriva relatados no intervalo registrado | Qualquer ocorrência exige registro e investigação |
| Volume | Ajustes pequenos sem pipocada relatada ou salto inesperado | Artefato reproduzível ou dúvida do usuário |
| Restauração | Comparativo confirma todos os itens e tempo ≤10 min | Estado divergente, desconhecido ou limite excedido |

Um resultado favorável vale somente para aquela conexão e duração observada.
Não aprova consistência entre conexões, estabilidade prolongada nem sincronização
acústica medida. Para medir offset/drift/jitter, é necessária captura acústica
simultânea com dois canais e controle do atraso do próprio sistema de medição.

## Etapa separada: repetibilidade após reconexão

Exige nova autorização, com dispositivos, número de ciclos, prazo e rollback
especificados. Registrar condição anterior, ciclo, perfil/codec, tempos de prontidão,
relato de centralização/atraso e eventuais cortes usando o mesmo vídeo e níveis.
Definir previamente a quantidade de ciclos e tolerância auditiva com o usuário;
um único início bom não comprova repetibilidade. Não realizar essa etapa nesta
missão nem incluí-la implicitamente na autorização do vídeo.
