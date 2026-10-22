# Supervisor integrado do ensaio A–B–A

Preparação apenas: não executar a janela real sem autorização específica.
O PR continua em rascunho. A instalação habitual não usa este supervisor.

## Componentes e fluxo completo

`tools/trial-supervisor.py --prepare` faz leituras e grava somente um diretório
novo de preparação. Confere originais/backups, versões de código por hash,
watchdog/PID/InvocationID/freezer, estado de conexões já conhecido pelo watchdog,
A2DP/AAC, null sink único/owner_module, metadata, layout estéreo e rotas próprias.
O plano salvo não concede autorização. Sua [política estável](TRIAL-IDENTITY.md)
permite IDs/níveis atuais diferentes dos históricos e os recaptura antes da troca;
propriedades estáveis inesperadas continuam bloqueando.

Após autorização, `--execute-reviewed-plan` conserva um processo proprietário
vivo até o resultado final. Usa os mesmos `Session`, `AudioAdapter`, `OwnedGroup`
e `ReturnSupervisor` exercitados de ponta a ponta. Um lock de vida impede dois
proprietários; cada diretório é de uso único. Nenhum PID é usado como comando no protocolo IPC. O pedido de início exige
ARMED e heartbeat recente do proprietário (até 2 s); estado antigo não basta.

1. Preflight de leitura. ARMED publica identidade/contexto e aguarda start.request.
2. A inicial é ouvida nesse intervalo; sem pedido em 30 s, cancela sem intervenção.
3. Pedido de início: recaptura níveis/rotas/aplicativos imediatamente antes da troca.
4. Congela somente o serviço identificado, confere frozen, muta saídas selecionadas,
   remove apenas o null identificado e inicia o candidato em grupo próprio.
5. Espera até 30 s por prontidão. Sink ainda ausente é pendência nessa fase;
   erro/saída/prazo encerram a tentativa. ROUTED exige os dois filhos e links.
6. Restaura os níveis no caminho temporário e a rota de saída EasyEffects previamente
   identificada. O usuário inicia os mesmos materiais; não há controle de mídia.
7. O proprietário observa candidato/grafo. Pedido por arquivo, SIGINT/SIGTERM/SIGHUP,
   perda de prontidão ou prazo iniciam retorno no mesmo contexto.
8. O motor encerra grupo, verifica remoção por ID+serial, restaura original e só
   retoma o mesmo serviço após verificação. Compara novamente depois do thaw.
9. Resultado final distingue RESTORED, RESTORED_WITH_APP_LIMIT e FAILED.
   Uma falha persistente não retoma o watchdog nem declara conclusão.

`events.jsonl`, `commands.jsonl`, `ownership.json`, `before.json`, `candidate.log`,
`observations.jsonl` e `state.json` registram a execução. `ownership.json` é uma
trilha de diagnóstico, não autorização para matar PIDs de outra chamada. Um pedido
por arquivo confirma envio, não execução nem sucesso.

## Prazo e falhas

Relógio monotônico começa em ARMED, antes de qualquer intervenção, incluindo A
inicial. Configuração real: máximo 600 s, início automático do retorno em 360 s,
aviso 30 s antes e quatro minutos reservados. A ausência de resposta não estende
a janela. A inicial deve caber nos 30 s de armamento; material pode ser combinado
antes. O usuário compara A final assim que o retorno estiver conferido.

Comandos de áudio e serviço têm timeout de até 2 s e respeitam o prazo global.
Há margem de 2 s para registrar o resultado. A espera de processos e remoção de
recursos é limitada também pelo prazo global. Até três passagens de restauração
permitem recuperar falha transitória, sem relançar o candidato, reconectar ou
reiniciar serviços. Falha permanente resulta em FAILED e registra a última causa.

O monitor de prazo integra o laço do proprietário e continua sem o solicitante.
Não depende do observador ou de o agente mandar um segundo comando no minuto seis.
Não é um mecanismo em tempo real nem proteção contra SIGKILL, morte do executor,
travamento do kernel/servidor ou suspensão da máquina. O executor deve permanecer
aberto em terminal/sessão persistente até o fim; não iniciar em chamada descartável.
Se esse controle ou a comunicação não estiverem confirmados, não enviar start.request.
Uma falha irreparável pode impedir restauração integral: o limite exige parar
novas tentativas e registrar FAILED, sem alegar sucesso ou reconectar dispositivos.

## Falhas reais encontradas nos testes completos

- O primeiro monitor consultava o plano antes de o virtual existir e abortava
  imediatamente. Agora essa ausência é pendente somente na fase de prontidão.
- Após a morte do candidato com EasyEffects real, uma rota de fallback em portas
  controladas era exigida como se fosse alheia. A comparação agora exclui apenas
  o fallback dessas portas identificadas; links realmente alheios continuam exigidos.
- Um fluxo sobrevivente do EasyEffects que tinha destino split mantém esse destino
  pretendido no retorno, mesmo que a política tenha aplicado fallback transitório.
  Não se identifica um fluxo recriado apenas pelo nome.

## Testes e distinção de ambientes

`python3 tests/rollback-native.py --supervisor` cria PipeWire/Pulse/D-Bus e política
WirePlumber privados. Exercita onze cenários: pedido normal, prazo, morte efetiva
do candidato durante reprodução, falha depois da remoção do original, falha
transitória no primeiro link do retorno, prontidão expirada, cancelamento antes
da troca, saída do solicitante, SIGTERM do proprietário, comando que excede seu
timeout e falha persistente de retorno. Esta última passa somente se resultar em
FAILED, sem conclusão e sem retomada. Reproduz PCM em destinos simulados, verifica
stream ativo, estado original restaurado, níveis/mute/rotas e IDs alheios preservados.

`--supervisor --easyeffects` repete com EasyEffects real e estado/preset privados.
Os testes unitários cobrem também fronteiras de prazo, identidade e limites de mídia.
Uma execução adicional fez início e retorno a partir de outra chamada da ferramenta,
com namespace PID comprovadamente diferente; o mesmo proprietário concluiu a operação.

Neste ambiente, um manager systemd privado não pôde iniciar: criação de init.scope
falhou em cgroup somente de leitura. O teste `systemd --user --test` somente carrega
uma transação, não comprova freeze. O substituto usa processo privado real com
SIGSTOP/SIGCONT e identidade verificada; não toca o systemd pessoal. O adaptador
real foi inspecionado via consultas do serviço do host, sem freeze/thaw real.
Essa distinção não é aprovação em hardware.

## Operação real que dependerá de autorização

Usar diretório novo e preparar imediatamente antes da janela:

```bash
python3 tools/trial-supervisor.py --prepare --session /CAMINHO/ABA-NOVO \
  --config /home/arthur/.config/linux-bluetooth-split-stereo/config \
  --manifest /CAMINHO/outputs/homologacao/manifest.json
```

Somente após autorização para freeze/thaw, mute, substituição específica do null,
rotas afetadas e retorno dentro de dez minutos:

```bash
# Manter esta sessão/terminal vivo; esperar ARMED.
python3 tools/trial-supervisor.py --execute-reviewed-plan --session /CAMINHO/ABA-NOVO

# De outra chamada, depois de A inicial e do controle proprietário confirmado:
python3 tools/trial-supervisor.py --request-start --session /CAMINHO/ABA-NOVO

# Encerramento antecipado, sem sinalizar PIDs externos:
python3 tools/request-return.py --session /CAMINHO/ABA-NOVO
```

O agente lê ROUTED e avisa ao usuário para começar B. Lê RETURN_DUE_SOON e avisa
antes do encerramento normal. Confere `state.json` e evidências, dispositivo/serviço,
níveis/mute/rotas/hash e aplicativo/MPRIS depois. Não considerar apenas o envio do
pedido, o retorno da função ou a presença do null como prova suficiente.

Revisar [COMPARISON.md](COMPARISON.md), o [contrato de retorno](ROLLBACK.md) e o
[diagnóstico de volume](VOLUME-ARTIFACTS.md). Não modificar codec, processamento ou
compensação no meio da comparação e não presumir superioridade de A ou B.

## Revalidação atualizada

Planos schema 2 não usam índices, seriais ou níveis da preparação como identidade
permanente. Ver [TRIAL-IDENTITY.md](TRIAL-IDENTITY.md). O vínculo operacional é feito
com a captura final atual; depois dela, mudanças de identidade bloqueiam escritas.
Os testes privados passaram a usar 24 s de máximo/8 s até retorno para acomodar
as consultas adicionais; os limites reais permanecem 600 s/360 s.
