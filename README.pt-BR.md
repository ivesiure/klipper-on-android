# Klipper num celular Android rooteado

O **host do Klipper** (`klippy`, Moonraker e Mainsail) rodando num **celular Android com
root**, ligado por USB a uma **Ender 3 V3 SE** — uma impressora cuja placa conversa por um chip
USB-serial **CH340**, para o qual o kernel do Android não tem driver.

Este repositório é a parte que *não* é o driver: a receita, o arranjo dos serviços, os dois
patches que o Klipper exige no Android e, acima de tudo, as **armadilhas** — a lista dos jeitos
pelos quais esta montagem falha em silêncio ou manda o diagnóstico para o lado errado. O driver
em si vive em repositório próprio,
[`ch341-userspace-pty`](https://github.com/ivesiure/ch341-userspace-pty).

> **English:** [README.md](README.md) — toda a documentação também está em `docs/en/`.

## Por que isto existe

Todo guia de "Klipper no Android" resolve a porta serial do mesmo jeito: instala o
[Octo4a](https://github.com/feelfreelinux/octo4a) — um servidor OctoPrint completo, em Java —
só para emprestar o driver serial dele, e aponta o `[mcu] serial:` para o `serialpipe`. Com
uma placa CH340 esse caminho falha no primeiro handshake, e as issues abertas sobre isso nunca
foram resolvidas.

A alternativa tomada aqui: um **driver de CH340 em espaço de usuário, em Python puro**, que
fala com o chip por chamadas `ioctl` em `/dev/bus/usb` e o expõe como um **pty** comum. O
Klipper abre o pty como abriria qualquer dispositivo serial e nunca percebe a diferença. Sem
recompilar kernel, sem soldar peça na UART da placa, sem Octo4a.

Tudo que fica acima do driver — Klipper, Moonraker, Mainsail, supervisão, persistência no boot
— é o que este repositório documenta.

## Estado

Funciona, e foi medido em vez de suposto:

| O quê | Resultado |
|---|---|
| Ocioso, conectado | 44 min, `state: ready`, lendo as temperaturas da mesa, do bico e do MCU |
| Movimento puro sob carga | 4,7 min de diagonais a 150 mm/s, ziguezague e 700 segmentos de 2 mm — `Timer too close: 0`, `print_stall: 0`, `bytes_invalid: 0` |
| Uma impressão de verdade | 36,5 min, 9,73 m de filamento, `complete` — `Timer too close: 0`, `print_stall: 0` |
| Pausar / retomar / cancelar | Exercidos num Benchy sacrificado |
| Qualidade do enlace | `srtt` de 6–8 ms (o PC de referência dá 3 ms), `rttvar` de 1–2 ms |
| Recuperação | Matar a ponte e não fazer nada devolve a impressora a `ready` em 48 s |
| Boot | O celular foi reiniciado; o SSH e os cinco serviços voltaram sozinhos |
| Bateria | ~6 %/h imprimindo; um hub com entrada de energia carrega o celular enquanto ele é host USB |

Os números e o método estão em [`docs/pt-BR/resultados.md`](docs/pt-BR/resultados.md).

## O caminho, ponta a ponta

```
Placa da Ender 3 V3 SE (GD32F303, compatível com STM32F103)
   │  USART1, 250000 baud
   ▼
CH340  (1a86:7523)  ── USB ──►  celular Android rooteado (host USB)
                                   │  /dev/bus/usb/BBB/DDD   (root)
                                   ▼
                            ch341_pty.py  — o driver, Python puro, ioctls do USBDEVFS
                                   │
                                   ▼
                            pseudo-terminal (/dev/pts/N) + symlink estável ~/printer
                                   │
                                   ▼
                            klippy  ([mcu] serial: ~/printer)
                                   │  socket unix
                                   ▼
                            Moonraker (:7125)  ◄──  Mainsail (:8080, arquivos estáticos)
```

Cinco serviços do [runit](https://smarden.org/runit/) mantêm isso de pé: `bridge`, `klippy`,
`moonraker`, `mainsail` e `watchdog`. O watchdog existe porque supervisor só reinicia processo
que morre, e um host do Klipper que perdeu o pty não morre — ele fica em `shutdown`.

## Por onde começar

| | |
|---|---|
| [`docs/pt-BR/armadilhas.md`](docs/pt-BR/armadilhas.md) | **Leia primeiro.** Todas as falhas silenciosas encontradas no caminho, com o sintoma que cada uma produz. É a razão de este repositório existir |
| [`docs/pt-BR/instalacao.md`](docs/pt-BR/instalacao.md) | A receita, na ordem que funciona |
| [`docs/pt-BR/arquitetura.md`](docs/pt-BR/arquitetura.md) | Como as peças se encaixam, e por que cada uma existe |
| [`docs/pt-BR/decisoes.md`](docs/pt-BR/decisoes.md) | Por que celular e não Pi, por que KernelSU e não Magisk, por que driver e não kernel recompilado |
| [`docs/pt-BR/resultados.md`](docs/pt-BR/resultados.md) | As medições |
| [`docs/pt-BR/estado-da-arte.md`](docs/pt-BR/estado-da-arte.md) | O que já existia, e onde cada projeto para |
| [`patches/`](patches/) | As duas mudanças que o Klipper exige no Android, e a que o Moonraker exige |
| [`services/`](services/) | As definições de serviço do runit e o script de boot |
| [`scripts/`](scripts/) | O watchdog, o servidor estático do Mainsail e um cliente pequeno da API |
| [`config/`](config/) | Um `moonraker.conf` mínimo e a seção `[mcu]` do `printer.cfg` |

## O hardware em que isto foi feito

* **Impressora:** Creality Ender 3 V3 SE, placa `CR4NS200320C13`, MCU **GD32F303RET6**
  (compatível com STM32F103), serial na USART1 por um CH340 a 250000 baud. A V3 SE vem com
  duas placas possíveis (F103 e F401) e as duas usam CH340 — não dá para distingui-las por
  software. Esta é a F103.
* **Celular:** Samsung Galaxy S9+ (SM-G9650, Snapdragon 845), Android 10, kernel 4.9 com
  **KernelSU-Next**. O kernel tem `usbserial`, `ftdi_sio`, `pl2303` e `cdc_acm`, mas **não tem
  `ch341`** — e é essa a razão inteira do driver.
* **Hub:** um hub USB-C com entrada de energia (PD). Sem ele o celular, sendo host USB,
  *fornece* energia e não consegue carregar.

Nada aqui é específico da Samsung ou do S9+ além das notas de debloat; o que importa é ter
root, um ambiente Termux e um kernel sem `ch341`.

## Requisitos, num parágrafo

Um celular rooteado (o root só serve para abrir `/dev/bus/usb`), Termux instalado pelo F-Droid
ou pelo GitHub (a build da Play Store está abandonada), a impressora **ligada** (o CH340
enumera só com a energia do USB, mas o MCU só responde com os 24 V da impressora) e um checkout
do host do Klipper cuja versão **bata com o firmware da placa** — a divergência produz
`MCU Protocol error`, que é idêntico ao erro de firmware velho e manda o diagnóstico para
outro lugar.

## Licença

**GPL-3.0-only.** Os patches são obras derivadas do Klipper e do Moonraker, os dois GPL-3.0,
então o repositório inteiro leva a mesma licença. O driver é publicado à parte sob
**GPL-2.0-only**, porque a inicialização do chip é traduzida do `ch341.c` do kernel Linux — as
duas licenças são incompatíveis para combinação, e é por isso que os dois repositórios são
mantidos separados de propósito.
