# Investigação da inicialização nativa — 2026-10-18

## Conclusão e limite

A causa inicial da ausência dos filhos no primeiro ensaio real **não pôde ser
estabelecida conclusivamente**. O registro disponível prova a ausência, mas não
contém os eventos internos de criação do módulo. Não há prova de falha do AAC,
do Bluetooth, do firmware ou do EasyEffects. A experiência excelente relatada
pelo usuário pertence à instalação antiga; não homologa este candidato.

Foi reproduzido um defeito distinto e relevante de recuperação: destruir um filho
criado por `stream.rules` deixa-o ausente enquanto o dispositivo continua presente.
A regra é processada quando o objeto físico é anunciado; a destruição do filho
não anuncia novamente o dispositivo. O supervisor anterior encerrava todo o
cliente após dez segundos dessa condição, removendo também o sink virtual e o
lado saudável. A nova revisão permite solicitar novamente somente o filho.
Isso corrige um caminho demonstrado de indisponibilidade; não prova retrospectivamente
por que os dois filhos faltaram na primeira inicialização real.

## Evidências preservadas do primeiro ensaio

Os seis arquivos foram examinados: `native.log`, `commands.jsonl`, `before.json`,
`after.json`, `final-evidence.json`, `summary.json`. Permanecem no diretório local
`ensaio-20261018T174321`, junto da configuração efetivamente gerada. Dados pessoais,
endereços reais e dumps de aplicativos não são publicados neste repositório.

Horários de 18/10/2026, UTC; no computador eram três horas mais cedo:

| Momento | Evidência |
| --- | --- |
| 20:43:21.658 | Pré-condições aprovadas; watchdog antigo ativo antes da troca |
| 20:43:21.668 / .809 | Parada do watchdog e remoção do módulo null previamente identificado |
| 20:43:22.319 | `split_lr` nativo visível, marcador de propriedade correto e portas FL/FR; filhos ausentes |
| Até 20:43:33.804 | Snapshots sucessivos sem filhos; alvos físicos presentes; log `LEFT: native mono stream not ready` |
| Depois desse ponto | Supervisor remove o cliente após dez segundos de erro dos filhos; desaparece o virtual |
| 20:43:37.002 | Espera externa falha por ausência do virtual; rollback imediato |
| Final, 18.918 s totais | Serviço antigo, null sink, rotas, níveis, mute, padrão, conexões e hashes restaurados |

Nenhum estímulo foi reproduzido e o candidato não ficou pronto. O campo `corked`
de um aplicativo mudou de falso para verdadeiro, com origem não estabelecida;
as rotas e mute dele foram restaurados, mas não se afirma restauração integral
do estado de reprodução. Não houve comando de pausa, reprodução ou busca.

## Investigação isolada

PipeWire 1.6.9 e WirePlumber 0.5.17, as mesmas versões instaladas. Foram usados
servidor, sockets Pulse/PipeWire, D-Bus, configuração e estado privados; sinks
simulados com nomes no formato Bluetooth, sem monitores físicos do WirePlumber.

A configuração anterior conseguiu criar os filhos com correspondência por MAC,
com a política do WirePlumber já ativa e, em outro experimento, com EasyEffects
8.2.9 separado e sem janela. Copiar estado salvo do WirePlumber também não
reproduziu a ausência inicial; apenas restaurou o ganho salvo, comportamento
esperado. Esses resultados não excluem uma corrida ou interação específica da
sessão real. A perda deliberada de um filho reproduziu o defeito de recuperação.

Durante o desenvolvimento do novo teste, criar um `default` metadata de teste
junto do criado pelo WirePlumber produziu dois stores e queda do cliente nativo
por sinal 11. Isso foi um erro do fixture, corrigido para deixar o WirePlumber
ser seu único proprietário. Não é atribuído ao ensaio real. O controlador agora
exige exatamente um store antes de lançar o cliente. Uma duplicação posterior
por outro componente permanece um risco externo; não se manipula o store alheio.

## Correção

- Mesmo `libpipewire-module-combine-stream`, agora com `combine.on-demand-streams`
  e regras automáticas vazias. O supervisor resolve cada alvo e pede um filho pela
  API nativa de metadata, com `target.object` igual ao serial atual do alvo.
- A chave `combine.on-demand-stream.left/right` é escrita somente no subject do
  virtual próprio. Retentativa remove exclusivamente essa chave antes de repetir
  o valor, pois escrever um valor idêntico não emite um novo evento de criação.
- Filho ausente/em erro: retentativa apenas desse lado, respeitando o backoff já
  existente. Filho saudável ou aguardando portas: preservado. Desaparecimento do
  virtual ou morte do cliente ainda exige recriar somente o cliente candidato.
- Metadata ausente/duplicado, nomes ambíguos ou propriedade estrangeira falham
  visivelmente. Não há criação de stores na sessão do usuário.
- Logs distinguem ausência de dispositivo, ausência de filho, pedido de criação,
  estado/portas pendentes e erro. O pedido inclui virtual, serial do alvo e canal.
  `NATIVE_DEBUG=true` acrescenta mensagens internas do módulo no próximo início.
- Overrides de ambiente capazes de redirecionar streams internos são removidos
  apenas do ambiente do cliente filho. Não foi demonstrado que estivessem ativos
  no primeiro ensaio. Endereço do servidor/runtime continua preservado.

Não aumentamos o prazo de inicialização nem ajustamos ganho, codec, perfil,
quantum, frequência ou buffers. FL/FR → MONO → portas físicas mantém o mesmo
mapeamento. Compensação e resampling mantêm a configuração anterior. A dependência
adicional é `pw-metadata`, fornecido pelas ferramentas PipeWire, e o store padrão
normal da sessão. Não existe caminho novo de reconexão ou controle de mídia.

## Validação desta revisão

- 36 testes unitários aprovados. Novas regressões cobrem criação explícita e
  mapeamento, coalescimento assíncrono, filho ausente, portas atrasadas, alvo
  tardio/ausente, ambiguidade, falha de comando, serial novo/erro de filho,
  metadata duplicado e isolamento dos overrides de ambiente.
- Teste nativo básico e teste com WirePlumber ativo antes do cliente, atraso
  artificial de dois segundos e identificadores Bluetooth simulados aprovados.
  Filhos inicialmente ausentes e um alvo deliberadamente descoberto depois foram
  criados sem substituir o virtual ou o primeiro filho.
- Captura de amostras nos sinks simulados confirmou sinais e ganho esperados dos
  canais. Não mede sincronização acústica ou a passagem pelo preset pessoal.
- Recuperação de link perdido/cruzado, hotplug simulado, exclusão de supervisor
  duplicado, compatibilidade da flag, reinício de supervisor/servidor/política e
  remoção do virtual aprovados. O reinício do servidor inclui reiniciar a política
  isolada, como faria sua unidade de usuário; o controlador não inicia WirePlumber.
- Destruição isolada do filho esquerdo: recuperação aprovada, preservando IDs do
  virtual, filho e links direitos, além de níveis e mute físicos/virtual.
- Candidato também ficou ROUTED com EasyEffects separado e WirePlumber ativo.
  É um teste de coexistência/inicialização, não uma medição do processamento ou
  dos presets da sessão pessoal, nem parte obrigatória do CI.
- ShellCheck 0.11.0, sintaxe Bash/Python, verificação da unidade systemd e
  `git diff --check` aprovados. Verificar o resultado do CI no commit publicado;
  este documento não substitui a indicação de checks do PR.

Não houve novo ensaio real, instalação, parada de watchdog instalado ou mudança
de conexões, reprodução, volumes e rotas reais nesta missão. Os backups e o
candidato antigo de homologação foram preservados como evidência histórica.

## Pipocada ao alterar volume

A causa não foi medida. Possibilidades: descontinuidade de ganho, interação entre
controle de volume e processamento/limiter do EasyEffects, volume do transporte
Bluetooth, ou ajuste de buffers. Nenhuma delas foi promovida a diagnóstico e
nenhuma correção especulativa foi implementada. Em ensaio autorizado, registrar
horário, controle usado, nível anterior/novo, presença de clipping/erro e relato
auditivo. Comparações com processamento desabilitado ou outro codec devem ocorrer
em sessões separadas autorizadas, mantendo as demais variáveis comparáveis.

## Riscos e próximo passo

A inicialização real, a preservação do caminho pessoal via EasyEffects, a ausência
de cortes e a consistência após conexões independentes continuam pendentes. Um
grafo correto pode ter latências acústicas diferentes; a API on-demand não mede
nem elimina a diferença oculta do transporte. Novos filhos podem produzir uma
interrupção no lado recuperado. Portas eternamente pendentes permanecem em erro
visível para diagnóstico, sem reiniciar o lado saudável. O PR permanece rascunho;
a próxima etapa é o [segundo ensaio autorizado](SECOND-TRIAL.md).

## Fontes primárias

- [API e mapas do combine-stream](https://docs.pipewire.org/page_module_combine_stream.html)
- [PipeWire 1.6.9: registry_event_global, metadata_property, create_stream e remoção](https://github.com/PipeWire/pipewire/blob/1.6.9/src/modules/module-combine-stream.c)
- [PipeWire 1.6.9: overrides em pw_stream_connect](https://github.com/PipeWire/pipewire/blob/1.6.9/src/pipewire/stream.c)
- [Propriedades de streams, target e política](https://docs.pipewire.org/page_man_pipewire-props_7.html)

## Revisão posterior — retorno e comparação

O segundo ensaio em e17ada5 alcançou ROUTED em 2,594 s e o manteve nas 43
amostras registradas. O retorno inicial falhou e exigiu recuperação adicional,
conferida em 319,723 s. O usuário posteriormente comparou com um fone estéreo
convencional e considerou a experiência normal: a suspeita de separação defeituosa
não sustenta mudanças de áudio. Não há aprovação acústica definitiva.

O [diagnóstico e contrato de retorno](ROLLBACK.md) substitui o controle temporário
antigo; o [plano A–B–A](COMPARISON.md) prepara a comparação, sem executá-la.
