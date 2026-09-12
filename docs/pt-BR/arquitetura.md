# Arquitetura

## O caminho, ponta a ponta

```
Placa da Ender 3 V3 SE (GD32F303 / compatível com STM32F103)
   │  USART1, 250000 baud
   ▼
CH340  (1a86:7523)  ── USB ──►  celular Android rooteado (host USB)
                                   │
                                   │  /dev/bus/usb/BBB/DDD   (root)
                                   ▼
                            ch341_pty.py   ← o driver, em Python puro
                                   │  ioctls do USBDEVFS, sem libusb
                                   ▼
                            pseudo-terminal  (/dev/pts/N)
                                   │  symlink estável: ~/printer
                                   ▼
                            klippy  ([mcu] serial: ~/printer)
                                   │  socket unix (~/pdata/run/klipper.sock)
                                   ▼
                            Moonraker  (0.0.0.0:7125)
                                   ▲
                            Mainsail (arquivos estáticos na :8080, fala direto com a :7125)
```

## Por que cada peça existe

**Por que um driver próprio?** O kernel do Android não tem o módulo `ch341`. Sem ele, nenhum
processo Linux consegue um `/dev/ttyUSB0`. As alternativas eram: recompilar o kernel (uma linha
no defconfig, mas exige toolchain e gravar uma imagem de boot), usar uma ponte CDC-ACM externa
(um ESP32-C3 ou FTDI na UART da placa, que exige peça e solda), ou escrever o driver. A terceira
não custa peça nem kernel.

**Por que USBDEVFS e não libusb/pyusb?** No Termux, libusb significa compilar uma biblioteca
nativa e, no caminho sem root, depender do `termux-usb` para receber o descritor. Com root,
falar com `/dev/bus/usb/BBB/DDD` por `fcntl.ioctl` usa só a biblioteca padrão e elimina a
dependência inteira.

**Por que um pty?** Porque o Klipper abre `[mcu] serial:` como um dispositivo serial comum. O
pty é o adaptador que faz o driver parecer uma porta serial para tudo que está acima. O que ele
não carrega — paridade, stop bits, DTR/RTS, controle de fluxo por hardware — o Klipper não
precisa.

**Por que root?** Só por permissão: `/dev/bus/usb` é `root:usb 0660`. Root não cria driver; ele
dá acesso ao nó por onde o driver fala.

**Por que o `klippy` e o Moonraker também rodam como root?** Não por escolha. Com o SELinux em
enforcing, a ponte vive no domínio do KernelSU e o pty que ela cria carrega um rótulo que um
processo de app não consegue abrir — o `chcon` é recusado até para o root. O socket unix que o
`klippy` serve é igualmente verificado contra o contexto do *servidor*. Quem fala com o `klippy`
tem de estar no mesmo domínio. O servidor estático do Mainsail e o watchdog continuam sem
privilégio: um só serve arquivos, o outro fala TCP com o Moonraker, e TCP não sofre a
restrição.

**Por que um watchdog?** O runit reinicia processos que morrem. Quando a impressora reenumera,
a ponte morre e volta com um pty *novo* — mas o `klippy` não morre; ele guarda o descritor velho
e entra em `shutdown`. Para o supervisor está tudo de pé. O watchdog sonda o estado da
impressora pelo Moonraker e, em duas leituras ruins seguidas, faz a única sequência que
funciona: reiniciar o `klippy` (pty novo), depois `FIRMWARE_RESTART`.

**Por que sem nginx?** O nginx do Termux não linka contra a OpenSSL instalada, e atualizar a
OpenSSL arrisca o `sshd`, a única entrada no aparelho. O Mainsail fala direto com o Moonraker
(`"hostname": null` no `config.json`) e seus arquivos são servidos por um script Tornado de 12
linhas, usando o Tornado que já está no virtualenv do Moonraker.

## Os processos que ficam de pé

| Serviço | Usuário | Papel |
|---|---|---|
| `bridge` | root | Segura o dispositivo USB e o pty. Espera o CH340 antes de iniciar o driver |
| `klippy` | root | Abre `~/printer`. Espera o symlink indefinidamente |
| `moonraker` | root | API na `:7125`. Espera o socket do `klippy` |
| `mainsail` | usuário | Arquivos estáticos na `:8080` |
| `watchdog` | usuário | Sonda `/printer/info` a cada 15 s; recupera um `klippy` preso em `shutdown` |

A ordem importa: ponte primeiro, depois `klippy`, depois Moonraker. Cada `run` espera a peça
anterior em vez de falhar e reiniciar, então uma impressora desplugada ou desligada custa um
`grep` a cada cinco segundos em vez de um processo por segundo.

Os três serviços root gravam o pid real e repassam o `TERM` à mão, porque o `runsv` não consegue
parar um processo iniciado por `su` — o sinal para no `su`.

## Estado em disco

```
~/printer                 symlink para o pty atual (recriado pela ponte a cada partida)
~/pdata/config/           printer.cfg, moonraker.conf
~/pdata/run/              klipper.sock, klipper.tty, *.pid
~/pdata/logs/             klippy.log, moonraker.log, diretórios do svlogd por serviço
~/pdata/gcodes/           onde o Moonraker guarda os uploads — e para onde o [virtual_sdcard] tem de apontar
~/pdata/sv/               os cinco serviços do runit (diretório próprio, não o $PREFIX/var/service)
~/.termux/boot/           o script de boot, executado pelo Termux:Boot
```
