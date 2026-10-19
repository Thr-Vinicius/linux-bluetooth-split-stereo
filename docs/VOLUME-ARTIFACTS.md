# Pequenas pipocadas ao ajustar volume — investigação preliminar

O relato do usuário é válido, mas a causa ainda não foi estabelecida. Não foram
alterados ganho, fase, panorama, compensação, taxa, quantum ou processamento.

## Evidência disponível

As 43 amostras do segundo ensaio mostram níveis do virtual em 30%, 40% e 50%,
com grafo ROUTED. A resolução de cinco segundos não captura a forma de onda no
instante do ajuste, nem o estalo acústico. O log de latência do módulo também não
identifica, sozinho, um estalo. Não há base para atribuir o artefato a AAC/firmware.

O controlador não ajusta volumes na recuperação de links. Seu ganho inicial é
configurado uma vez; WirePlumber pode restaurar valores salvos. O procedimento
antigo de partida do watchdog normaliza níveis e move fluxos, uma razão concreta
para evitar stop/start no meio da comparação. Isso não prova que causou a pipocada
relatada durante ajustes voluntários.

Passos discretos no controle de volume, processamento do EasyEffects e mudanças
no transporte são hipóteses distintas. A ausência de uma rampa no comando externo
não prova ausência de suavização interna no PipeWire ou no dispositivo. Não se
adicionou uma rampa ou ajuste especulativo para mascarar o sintoma.

## Diagnóstico futuro, separado e autorizado

1. Definir um único controle e passos pequenos, mesmo áudio/trecho, níveis, preset
   e perfil. Registrar horário, valor anterior/novo, lado e percepção. Separar
   ruído durante o gesto de ruído na partida/retorno.
2. Primeiro comparar A/B mantendo EasyEffects no mesmo caminho. Não alterar codec,
   compensação ou preset durante a mesma observação.
3. Em outra execução aprovada, comparar o mesmo ajuste com processamento ativo
   e bypass, uma variável por vez. Não mudar configurações pessoais nesta missão.
4. Se autorizado, capturar PCM antes/depois do processamento, com resolução por
   amostra, para procurar clipping, salto ou descontinuidade no momento marcado.
   Os taps acrescentam recursos e podem conter áudio privado; seu escopo e destino
   devem ser aprovados antes. Não houve essa captura aqui.
5. Se PCM permanecer limpo e o estalo for ouvido, ainda falta medir a saída real.
   Uma captura acústica simultânea adequada pode investigar a etapa posterior;
   não concluir que é Bluetooth apenas por exclusão de um único tap.

Sem essas observações, a causa fica **pendente**. Logs de volume demonstram o
ajuste, não seu resultado acústico. Aprovar estabilidade do grafo não aprova
volume sem estalos.
