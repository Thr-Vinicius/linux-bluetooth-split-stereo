# Retorno de ensaios temporários — correção e limites

Esta revisão altera o suporte de ensaio, sem instalar processos ou serviços.
O motor está em `tools/trial_support.py`; não há CLI que inicie uma troca real.
O procedimento precisa ser executado por um supervisor persistente no contexto
que criou os processos, após autorização específica. As cópias locais antigas de
`session.py` são evidências históricas, não o procedimento para uma nova execução.

## Diagnóstico do segundo ensaio

O candidato e17ada5 ficou pronto em 2,594 s. A primeira tentativa de retorno
registrou `old_null: Unknown virtual remains` e `no_candidate=false`, mas retomou
o watchdog e gravou `done.json` mesmo com erro. O supervisor original interpretou
essa marca como conclusão e pulou sua própria limpeza. A recuperação adicional
só foi conferida em 319,723 s. Os arquivos originais de evidência foram preservados.

Falhas comprovadas na leitura do procedimento anterior:

1. `stop_candidate` podia retornar sem sinalizar nada se o PID não fosse visível
   ou tivesse outra identidade. Seu retorno não era prova de encerramento.
2. PIDs numéricos eram lidos de outra chamada da ferramenta, sem identificação
   do namespace. A checagem silenciosamente ignorava o processo; não encaminhava
   um pedido ao supervisor que possuía o handle verdadeiro.
3. Depois de detectar o virtual remanescente, o procedimento continuava a criar
   links e retomava o watchdog. A barreira de remoção não protegia o handoff.
4. Erros eram coletados, mas um arquivo de conclusão era escrito mesmo assim.
5. A comparação de aplicativos incluía os filhos internos, que devem desaparecer.
   A comparação de todo o grafo também ignorava que o vídeo só começou depois
   da captura inicial. O fluxo do navegador foi recriado durante o retorno, e
   não se pode afirmar continuidade interna integral.

Uma reprodução sem áudio confirmou o mecanismo de contexto: o mesmo processo
privado era PID 5 no namespace que o iniciou e não existia com esse PID na chamada
seguinte; os inodes de `/proc/self/ns/pid` eram diferentes. O pedido por arquivo
foi atendido pelo proprietário original e o processo privado foi encerrado.
Isso comprova a fragilidade ambiental do PID salvo e é compatível com o ocorrido.
O ensaio antigo não capturou seu namespace, portanto não transforma esta
reprodução posterior em prova forense completa de cada sinal daquele retorno.

## Novo contrato

- `OwnedGroup` mantém o `Popen`, namespace/boot, grupo/sessão e instante de criação.
  Enumera descendentes somente enquanto o líder original é identificável. Usa
  pidfds para sinalizar processos verificados, impedindo a corrida de reutilização
  do PID. Outro contexto é recusado antes de qualquer mute ou escrita de áudio.
- `request-return.py --session /diretorio/privado` apenas cria `return.request`.
  O supervisor original atende por `ReturnSupervisor.poll(deadline)`. Criar o
  arquivo não comprova que o retorno ocorreu; é preciso ler o estado verificado.
- Um `TRIAL_TOKEN` único, opcional, marca virtual e filhos com `split.session`.
  Essa propriedade de identificação não muda áudio, fase, ganho ou buffers.
  Na execução normal sem token, a configuração de áudio permanece equivalente.
- `Resources` registra ID **e serial** de nós, cliente, portas e links envolvidos.
  Após encerrar os processos, espera a remoção de todos eles, inclusive do cliente
  quando seus nós já sumiram. IDs reutilizados por outros objetos não são removidos.
- Recursos remanescentes ou término não comprovado produzem FAILED, sem recriar
  sobre um nome ocupado, sem retomar o watchdog e sem declarar conclusão.
- Só então se confirma/recria o único module-null-sink com os argumentos salvos,
  sua relação owner_module com o sink, portas, níveis por canal/mute, padrão,
  rotas próprias e saída afetada do EasyEffects. Módulos ambíguos ou estrangeiros
  não são removidos. As demais saídas não recebem comandos de volume.
- O adaptador `WatchdogLease` só faz thaw do mesmo PID previamente pausado, sem
  flag de resync pendente; nunca inicia o script antigo. O estado é conferido
  depois do thaw e o áudio é novamente verificado. Não há fallback para reconexão.
- Retorno repetido, já verificado, é somente de leitura. Falha parcial pode ser
  retomada pelo proprietário original, sem duplicar módulo ou recriar links bons.
  As mudanças manuais posteriores são apontadas, não desfeitas silenciosamente.

Estados: STOPPING → RESTORING → RESTORED, ou FAILED em qualquer barreira.
RESTORED_WITH_APP_LIMIT distingue recursos restaurados de identidade/estado de
aplicativo não preservados. Não inclui streams internos do candidato na comparação
com aplicativos. Um fluxo novo não é movido só porque possui o mesmo nome do antigo.

## Integração necessária para o próximo ensaio autorizado

Manter um único supervisor vivo durante a janela. Registrar o grupo de processos
e o ledger de recursos assim que forem criados, antes de aceitar a prontidão.
Um acompanhante de prazo pode rodar **nesse mesmo contexto**, com a mesma identidade
verificada; não executar um segundo rollback por importação numa chamada efêmera.
O contexto deve permanecer vivo até o estado final, e a perda do executor deve ter
um caminho de recuperação previamente demonstrado. Se isso não puder ser garantido
pela ferramenta, usar um terminal local estável sob controle do usuário e validar
seu controle antes da troca. Não iniciar com uma guarda apenas presumida.

O motor foi integrado ao [supervisor persistente](TRIAL-SUPERVISOR.md), com
preflight de leitura e executor explícito de plano revisado. O fluxo completo é
testado em isolamento; controle de systemd e áudio reais continuam sem ensaio
nesta missão. O executor deve permanecer vivo até o estado final.
O [plano comparativo](COMPARISON.md) define os gates; não autoriza executar o teste.

## Cobertura e limites

Testes unitários: outro contexto, PID reutilizado, filho real, remoção atrasada,
cliente remanescente, identidade de recurso ausente, prazo, falha de restauração,
thaw inválido, repetição e aplicativos recriados. Servidores privados verificam
retorno normal, candidato incompleto e ausência inicial de virtual, falha injetada
no primeiro link e recuperação, volumes/mute, hashes, rotas e IDs alheios intactos.

A versão opcional com `--easyeffects` usa EasyEffects real, estado privado e sinal
em sinks simulados. Systemd/BlueZ são simulados nos testes: não qualificam freeze,
reconexão, rádio, firmware, preferências pessoais ou áudio acústico em hardware.
A operação pode falhar se o servidor real desaparecer; a garantia é não declarar
sucesso nem fazer handoff sem prova. Prazo de remoção é uma barreira operacional,
não uma solução por aumento arbitrário de timeout.

Python 3.9+ e kernel com pidfds são necessários para esse suporte de ensaio. Não
há fallback que mate por PID em sistemas sem esse recurso. A instalação regular
do split não passa a depender do motor de ensaios.

## Integração posterior

O supervisor e o procedimento exato estão em [TRIAL-SUPERVISOR.md](TRIAL-SUPERVISOR.md).
O prazo global também limita espera de processos e remoção de recursos. O serviço
real inclui InvocationID além de MainPID na identificação. A comparação de rotas
não exige preservar fallback transitório das portas EasyEffects já controladas,
mas continua exigindo as rotas efetivamente alheias.
