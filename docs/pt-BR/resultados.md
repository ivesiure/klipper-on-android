# Resultados

Tudo aqui foi **medido**, não estimado. Onde há dúvida, está dito.

## Referência: um host PC que imprime bem há meses

```
srtt=0.003   rttvar=0.000   rto=0.025
bytes_retransmit=9   em 14 MB de klippy.log
Timer too close: 0   (nunca)
```

A referência é 3 ms, não os 1–2 ms que se costuma supor. Isso muda a leitura de tudo abaixo.

## O celular, pela ponte

### Ida e volta bruta no protocolo (500 amostras, laço Python síncrono)

```
min 4,57   mediana 5,39   média 7,07   p95 11,44   p99 12,31   máx 13,93   desvio 2,60 ms
0 perdas em 500
```

Isto é **teto**, não `srtt`: carrega overhead de interpretador e um laço que espera bloco a
bloco.

### Medido pelo próprio Klipper, 150 s conectado

```
srtt=0.006   rttvar=0.001   rto=0.025   min_half_rtt=0.001819
bytes_invalid=0        Timer too close: 0        print_stall=0
mcu_awake=0.006  mcu_task_avg=0.000018  mcu_task_stddev=0.000028
freq=71999773  (nominal 72000000)
ponte: tx=3758  rx=30067  errors=0
```

Lendo a máquina de verdade: mesa 19,0 °C, bico 20,0 °C, MCU 23,6 °C.

### Ociosidade longa

Ponte e `klippy` subiram, e 44 minutos depois o socket de API ainda respondia
`{"state": "ready", "state_message": "Printer is ready"}` — sem exceção.

```
srtt=0.007   rttvar=0.002   rto=0.025
bytes_invalid=0   bytes_retransmit=16   send_seq=285=receive_seq
freq=72000829  (nominal 72000000)
```

O log ficou mudo depois de 62 s e isso não é falha — ver a armadilha *"O log parar não
significa que o klippy morreu"*.

## Sob carga: o teste que decide

`Timer too close` só aparece com geração de passos sob carga, então números em repouso provam o
enlace mas não o host. A sequência, do mais barato ao mais caro:

### Movimento puro — frio, sem filamento, Z parado em 10 mm

Cerca de 4,7 minutos: diagonais a 150 mm/s, ziguezague e 700 segmentos de 2 mm para forçar o
caminho de compressão de passos.

```
Timer too close: 0     print_stall: 0     bytes_invalid: 0
```

Use `G28` completo, não `G28 X Y`: o `z_hop` do `safe_z_home` só afasta o bico quando o Z entra
no homing, e depois de um boot a posição de Z é desconhecida.

### Uma impressão de verdade

`SpeedTestStructure`, **36,5 min**, 9,73 m de filamento, estado `complete`.

```
Timer too close: 0     print_stall: 0
```

A primeira tentativa falhou por motivo sem relação — um caminho de `[virtual_sdcard]` herdado
do host anterior (ver armadilhas). A segunda foi até o fim.

### Pausar, retomar, cancelar

Exercidos num Benchy sacrificado: pausa mantendo os aquecedores, retomada continuando de onde
parou, cancelamento desligando tudo.

### Recuperação

Mate a ponte — que é o que acontece sempre que a impressora reenumera — e não toque em nada: a
impressora volta a `ready` em **48 s**. O `sv restart klippy` mais `FIRMWARE_RESTART` do
watchdog, sozinho, mediu ~36 s, três vezes.

## Bateria

### Como medir direito (e por que a primeira tentativa não valeu)

A primeira medição foi invalidada pelo próprio método: o aparelho foi sondado por SSH dezenas de
vezes dentro da janela que se estava medindo, e cada sessão acorda CPU e rádio. Medir mexendo no
que se mede não é medir.

Use o contador de coulomb, não a porcentagem:

```
/sys/class/power_supply/battery/charge_counter   µAh, contínuo
/sys/class/power_supply/battery/charge_full      µAh totais
```

A porcentagem anda em degraus de ~35.000 µAh; uma janela de uma hora tem erro de quantização
maior que o sinal. Com o `charge_counter`, 60 minutos bastam. Um amostrador local gravando em
arquivo, com ninguém conectado até o fim, é o único método limpo. `dumpsys batterystats --reset`
antes da janela faz o relatório dizer **quais uids** consumiram — a diferença entre "gasta
4 %/h" e "gasta 4 %/h por causa disto".

### Duas janelas de 50 minutos, mesmo método, ninguém conectado

| | carga/h | %/h | tensão | energia/h |
|---|---|---|---|---|
| **Imprimindo** (99 → 94 %) | 209,7 mAh | **5,99** | ~4,05 V | ~849 mWh |
| **Repouso** (48 → 42 %) | 262,2 mAh | **7,49** | ~3,72 V | ~975 mWh |

**Repouso custou mais que imprimir**, e não é artefato de unidade — a inversão sobrevive à
conversão para energia. Pior: a janela de repouso rodou *depois* do modo avião, do Bluetooth e
NFC desligados e de três remoções de pacote. Não há explicação medida. O suspeito é o estado de
carga: as duas janelas rodaram em faixas muito diferentes (99–94 % contra 48–42 %), e medidor de
bateria é notoriamente impreciso perto dos extremos. Isso é hipótese, não medição; repetir as
duas janelas em faixas parecidas, guardando as amostras brutas, resolveria.

Uma armadilha relacionada: a média das amostras de `current_now` deu 179 mA onde o contador de
coulomb registrou 262 mAh/h — discordância de 46 %. Uma amostra por minuto perde os picos; o
contador integra tudo. Não calcule consumo a partir de corrente amostrada.

A bateria mal esquentou: 21,4 → 22,6 °C em 50 minutos de impressão, com o celular ao lado da
impressora e não montado em cima dela.

### O hub com entrada de energia

```
status: carregando   charge_type: Fast
~1030 mA líquidos entrando, com o CH340 presente no barramento
38 % -> 100 % em ~2 h
```

O celular carrega e serve de host USB ao mesmo tempo. A autonomia deixou de ser restrição
operacional: ~1030 mA entrando contra ~210 mA saindo durante a impressão. O mesmo hub traz um
adaptador Ethernet USB (também um chip WCH — um para o qual o kernel *tem* driver), reconhecido
de fábrica.

## O que não fechou

* **`bytes_retransmit` é instável entre rodadas** — 0, 23 e 16 em três rodadas onde o host de
  referência mostra 9 ao longo de meses. Com `bytes_invalid=0` e `rttvar=1 ms` não tem cara de
  corrupção; tem cara do timeout de retransmissão. Só mais carga vai dizer.
* **`bytes_invalid` não tem causa identificada.** Em duas impressões ele escalou com o **tempo**
  (1,35–1,70 por minuto), não com o volume de dados — então não é corrupção do enlace. Qual
  evento periódico o produz continua em aberto.
