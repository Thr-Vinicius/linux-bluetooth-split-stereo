# Revalidação: identidade estável e captura atual por janela

Preparação não é autorização. Nenhum ensaio real é executado nesta revisão.
O controlador de áudio habitual não foi alterado.

## Correção do bloqueio anterior

A tentativa posterior ao commit 35bb8cd terminou antes da troca. A captura atual
confirmou os mesmos MACs, A2DP/AAC, watchdog correto, null original, rotas e backups,
mas os índices/seriais diferiam da preparação anterior. A comparação adicional de
IDs históricos e o executor antigo tratavam essa diferença como bloqueio.
Essa classificação foi excessiva: esses números têm validade na sessão corrente,
não identificam permanentemente o fone. Volumes anteriores também não são o estado
que uma nova janela deve restaurar. As evidências anteriores permanecem intactas.

## Política estável

O plano versão 2 identifica cada lado por MAC e verifica concordância entre
Pulse e PipeWire: device.api, classe de mídia, endereço, perfil, codec e factory.
A preparação real exige BlueZ A2DP/AAC e factory nativa correspondente; nomes
simulados só existem nos servidores privados de teste. Um nome esperado contendo
outro endereço, mais de um sink/nó para o mesmo MAC ou propriedade de outro dono
é rejeitado. O nome atual do endpoint é resolvido novamente a partir do MAC.

O original exige um único module-null-sink, owner_module/pulse.module.id
correspondentes, factory de null sink, FL/FR e argumentos esperados, além das
rotas L/R e EasyEffects verificadas. Seu ID numérico pode mudar entre sessões.
O histórico opcional fornece somente as restrições estáveis: mudança real de
argumentos, codec, classe/factory ou ownership não é liberada como se fosse ID.

O watchdog é identificado pela unidade e caminho do script verificado por hash.
Consultas ao manager confirmam ExecMainPID, MainPID, InvocationID, instante de
início e cgroup. GetUnitProcesses confirma a linha de comando do processo efetivo
nesse grupo, evitando interpretar um PID do host pelo /proc de outro namespace.
Uma nova execução legítima entre sessões pode ser vinculada novamente se a mesma
política de unidade/script/processo for confirmada. Dentro da janela, PID,
InvocationID e identidade efetiva ficam fixados; restart inesperado bloqueia.

## Captura final e intervenção

O executor resolve e captura o estado atual em seu preflight de leitura e novamente
imediatamente antes da primeira intervenção. Captura índices/seriais, nós/portas,
módulo atual, volumes por canal, mute, padrão, rotas e aplicativos. O rollback usa
exclusivamente essa última captura. Mudança de volume antes dela é legítima e não
é uma falha de identidade. O arquivo revalidation-audit.jsonl registra as diferenças
em relação à preparação, sem utilizá-las como IDs de controle.

Depois da captura final, mesmo uma recriação do mesmo MAC é uma mudança de recurso
durante a janela e bloqueia a operação. Antes do freeze e de cada escrita de áudio,
o adaptador confirma novamente os recursos atuais, incluindo portas e propriedades.
Os comandos de ganho/mute usam o índice numérico validado naquela janela, em vez
de pedir ao servidor que resolva novamente um nome antigo. Uma ambiguidade nova
também é rejeitada. Links removidos precisam partir das portas EasyEffects já
identificadas e ser fallback, não uma rota válida ou alheia.

O virtual original fica identificado pela instância atual até sua remoção controlada.
Depois, somente o candidato com token próprio ou o módulo null cujo ID foi devolvido
pela criação do próprio supervisor pode ocupar o nome. O null restaurado ganha seu
próprio vínculo de índice/serial; falha parcial pode ser retomada sem adotar um módulo
estrangeiro apenas porque tem o mesmo nome/argumentos. Recursos candidatos continuam
sob o ledger ID+serial e só o proprietário os encerra.

As APIs de consulta e escrita não oferecem uma transação atômica única entre Pulse,
PipeWire e systemd. As verificações são imediatas e repetidas, os alvos são limitados
ao conjunto validado e divergências observadas falham de forma explícita. Não se
promete impedir uma alteração externa não observável entre duas chamadas. Por isso
não iniciar durante reconexão/reconfiguração e não tentar remapear recursos no meio
da intervenção. Se um recurso for substituído, o retorno pode ficar FAILED; não
escrever no substituto nem declarar restauração integral.

## Preparação e auditoria

```bash
python3 tools/trial-supervisor.py --prepare --session /DIRETORIO/NOVO \
  --config /home/arthur/.config/linux-bluetooth-split-stereo/config \
  --manifest /CAMINHO/outputs/homologacao/manifest.json \
  --history /CAMINHO/captura-anterior/prepared-before.json
```

O histórico é opcional; se fornecido, suas restrições estáveis são verificadas.
Índices/seriais, volumes/mute e detalhes de rotas anteriores ficam apenas no log
de diferenças. O executor também compara a captura feita na preparação com a
captura final da janela. Planos antigos sem schema 2 devem ser regenerados, pois
não contêm a política estável; não se tenta reinterpretá-los silenciosamente.

Mantêm-se os limites do [supervisor](TRIAL-SUPERVISOR.md): máximo de 600 s desde
ARMED, retorno até 360 s e aviso 30 s antes. A execução real continua dependendo de
nova autorização específica, sem instalação, reconexão ou merge.

## Testes e limites

Unitários: mudança legítima de IDs/seriais/nomes e módulo entre sessões; novos níveis
e mute; MAC incorreto; duplicação; discrepância Pulse/PipeWire; ownership estrangeiro;
argumentos inesperados; alteração de portas; recriação depois da captura final;
comando numérico atual e processo efetivo do watchdog. A rejeição antes de escrever
é verificada, não apenas a emissão de uma mensagem.

`SPLIT_TEST_MAC_TARGETS=1 python3 tests/rollback-native.py --supervisor --identity-rebind`
cria dispositivos e servidor privados, registra uma preparação, recria os endpoints
e o original com novos IDs, altera níveis/mute e executa candidato/retorno. Os MACs
são fictícios e as propriedades BlueZ são simuladas sobre sinks dummy. O mesmo teste
com `--easyeffects` usa EasyEffects real privado. Verifica a política estável, diferenças
auditadas, estado atual restaurado e links independentes preservados.

Os 11 cenários E2E anteriores permanecem. Com as verificações adicionais, a janela
reduzida do fixture é 24 s e o retorno automático aos 8 s; isso dá margem às consultas
repetidas, sem alterar os 600/360 s da operação real. Systemd/BlueZ e acústica reais
continuam fora desses testes. O manager privado não pode iniciar no cgroup somente
de leitura; o watchdog de teste usa SIGSTOP/SIGCONT em processo privado.
