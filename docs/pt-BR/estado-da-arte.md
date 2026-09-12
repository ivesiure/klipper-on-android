# Estado da arte

Levantado em setembro de 2026. O estado da arte muda; confira de novo antes de citar como
atual.

## Veredito

Prior art parcial é abundante; nada equivalente foi encontrado. Ninguém tinha publicado a
combinação: um driver de CH341 **em Python puro, por ioctls do USBDEVFS, sem libusb nem
pyusb**, com ponte para **pty**, em Android rooteado, validado contra o handshake do Klipper.

## O achado que mais importa: este caso é problema conhecido e em aberto

Todo projeto de Klipper-no-Android resolve a serial do mesmo jeito — instalando o Octo4a
inteiro só para emprestar o driver, e apontando o `[mcu]` para `/var/octo4a/serialpipe`. Com
CH340 isso falha:

* `d4rk50ul1/klipper-on-android` issue #24 — *"klipper is failing to connect to CH340 with
  driver from Octo4a"*, `Timeout on connect` no `identify_response`. Fechada sem solução. Hoje
  ela tem um comentário com o caminho alternativo e as duas descobertas que valem
  independentemente do driver: o pty em modo raw nas duas pontas e o `baud: 115200` fictício.
* `feelfreelinux/octo4a` issue #347 — atribui parte a toggle de DTR na troca de baudrate.
* Fórum do Klipper: *"CH340 - 250000 baud rate not supported"*.

O handshake `identify` foi fechado aqui a 250000 baud com CH340.

## Klipper com host Android

| Projeto | Onde para |
|---|---|
| `d4rk50ul1/klipper-on-android` | O README manda instalar o Octo4a para ter o driver CH34x |
| `galangtirta9/DroidicKlipper` | Root por Magisk; serial via `serialpipe` do Octo4a |
| `RyanEwen` (gist, Linux Deploy) | Mesma dependência do Octo4a |
| `umeiko/KlipperPhonesLinux` | O caminho oposto: troca o Android por Ubuntu/postmarketOS e recompila o kernel |
| `feelfreelinux/octo4a` | O mais próximo: o `VirtualSerialDriver.kt` dele **cria um pty**. Mas é Kotlin sobre a Android USB Host API, dentro de um app com UI |

## Pontes serial→pty em espaço de usuário

| Projeto | Onde para |
|---|---|
| `MarkWllms/Termux-serial-tty` | O mais próximo tecnicamente — cria pty. Mas C++ com libusb, e depende do `termux-usb` |
| `thingsapart/usbuart-termux` | Tem seção de Klipper no README. Baud fixo em 115200, e o autor afirma que nunca foi compilado nem testado |
| `jacklinquan/usbserial4a` | Python, mas via pyjnius sobre a API Java, e não cria pty |
| `gio3k/usbselfserial` | C++ header-only, libusb, focado em iOS, "not production ready" |
| `anszom/vtty` | Módulo de kernel |

## CH341 em Python via USBDEVFS

Nada. Os projetos Python de CH341 são todos de I2C/SPI/GPIO (`karlp/ch341-py2c`,
`pine64/libch341-spi-userspace`), sobre libusb. O driver do fabricante
(`WCHSoftGroup/ch341ser_linux`) é módulo de kernel.

## O que é diferente aqui, em cinco pontos

1. Python puro, só biblioteca padrão — os equivalentes são C/C++ com libusb, ou Java/Kotlin.
2. Root direto em `/dev/bus/usb`, sem `termux-usb` e sem app intermediário.
3. Sem Octo4a.
4. A taxa correta a 250000 baud, que é onde os outros quebram.
5. Evidência de funcionamento — o handshake que as issues abertas nunca fecharam, e impressões
   de verdade depois dele.
