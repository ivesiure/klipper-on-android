# Instalação

Leia [`armadilhas.md`](armadilhas.md) antes. Quase todo passo abaixo tem um jeito silencioso de
dar errado, e é lá que cada um está explicado.

Os caminhos assumem o home do Termux, `/data/data/com.termux/files/home`, chamado de `~` abaixo.
A pilha guarda seu estado em `~/pdata` (`config/`, `logs/`, `run/`, `gcodes/`, `sv/`).

## 0. Pré-requisitos

* Um celular Android **rooteado**. Aqui: KernelSU-Next. O root serve para uma coisa só — abrir
  `/dev/bus/usb`.
* **Termux** do F-Droid ou do GitHub. A build da Play Store está abandonada.
* A impressora **ligada**. O CH340 enumera só com a energia do barramento USB, mas o MCU só
  responde com a fonte de 24 V da própria impressora.
* Um hub USB-C com entrada de energia (PD), se pretende imprimir qualquer coisa longa. Como
  host USB o celular fornece energia e não carrega sem um.

## 1. Ambiente no Termux

```bash
pkg install -y python clang libffi git make openssh termux-services iproute2
```

Para acesso remoto: `passwd`, depois `sshd` (escuta na porta **8022**). Tudo daqui em diante é
muito mais fácil por SSH do que na tela do celular.

## 2. A ponte

Pegue o [`ch341_pty.py`](https://github.com/ivesiure/ch341-userspace-pty) e rode como root:

```bash
su -c "HOME=$HOME LINK=$HOME/printer nohup /data/data/com.termux/files/usr/bin/python $HOME/ch341_pty.py > $HOME/bridge.log 2>&1 &"
```

O log deve dizer o dispositivo, a versão do chip, os endpoints e o pty. Contadores `tx`/`rx`
crescendo com `errors=0` é o sinal de saúde. Repare no caminho completo do `python` e no `HOME`
explícito — o `PATH` do root não inclui o Termux, e o home do root é `/`.

Esta é a forma iniciada à mão, para os primeiros testes. Sob supervisão a mesma coisa é feita
pelo `services/bridge/run`, que também espera o chip aparecer antes de gastar um processo com
ele.

## 3. Klipper

A versão do host **tem de bater com o firmware da placa**, senão dá `MCU Protocol error` — que é
idêntico ao erro que um firmware velho produz e manda você na direção errada. Aqui a placa roda
um fork que controla a tela original da impressora, fixado num commit específico; use o que o
seu firmware foi construído a partir de, e ajuste o `.version` para bater.

```bash
git clone <seu fork do klipper> klipper
git -C klipper checkout <commit do qual o firmware foi construído>
printf %s "<string de versão que o firmware reporta>" > klipper/klippy/.version
```

Virtualenv e dependências (ver a armadilha do greenlet):

```bash
python -m venv klippy-env
grep -v "^greenlet" klipper/scripts/klippy-requirements.txt > req.txt
./klippy-env/bin/pip install "greenlet>=3.2"
./klippy-env/bin/pip install -r req.txt
```

### Os dois patches obrigatórios — aplique, não só leia sobre eles

```bash
git -C klipper apply /caminho/para/patches/klipper-android.diff
```

1. `-lm` em `COMPILE_ARGS` (`klippy/chelper/__init__.py`). No Bionic a `libm` não é resolvida
   implicitamente; o helper em C compila mas não carrega.
2. Um fallback para `os.getloadavg()` (`klippy/extras/statistics.py`), lendo `/proc/loadavg`.
   A função não existe no Android.

Se o seu checkout se afastou daquele contra o qual o diff foi feito, o `git apply` vai falhar e
os dois trechos são pequenos o bastante para aplicar à mão.

### Confira que entraram, *antes* de subir

As duas falhas mentem de jeitos diferentes, e a segunda é a pior:

```bash
grep -q -- '-lm' klipper/klippy/chelper/__init__.py     && echo "patch 1 ok" || echo "PATCH 1 FALTANDO"
grep -q 'proc/loadavg' klipper/klippy/extras/statistics.py && echo "patch 2 ok" || echo "PATCH 2 FALTANDO"
cd klipper/klippy && ../../klippy-env/bin/python -c "import chelper; chelper.get_ffi()" && echo "chelper carrega"
```

Sem o patch 1, o `chelper` falha ao carregar — barulhento, você vê na hora. Sem o patch 2, o
`Loaded MCU` **sai**, tudo parece certo, e o `klippy` morre um segundo depois por um timer de
estatística. É a falha que manda o diagnóstico para a ponte, para a serial, para o firmware —
qualquer lugar menos um módulo de estatística. Por isso a verificação vem antes de subir, não
depois.

## 4. Configuração

Na seção `[mcu]` do `printer.cfg`:

```ini
[mcu]
serial: /data/data/com.termux/files/home/printer
baud: 115200
restart_method: command
```

O `baud` é **fictício** — a taxa real (250000) é definida pela ponte, no chip. O pyserial
recusa taxas fora do padrão num pty, e não há UART daquele lado de qualquer forma.

O `restart_method: command` é **obrigatório**: o reset padrão alterna o DTR, que um pty não
tem (ver armadilhas).

Se o `printer.cfg` veio de outro host, procure nele caminhos absolutos: um `[virtual_sdcard]`
apontando para um diretório que não existe aqui faz todo upload "sumir" na hora de imprimir
(ver armadilhas).

## 5. Subir o `klippy`

```bash
nohup ./klippy-env/bin/python klipper/klippy/klippy.py \
  -I ~/pdata/run/klipper.tty \
  -a ~/pdata/run/klipper.sock \
  -l ~/pdata/logs/klippy.log \
  ~/pdata/config/printer.cfg &
```

Os três caminhos são explícitos porque os padrões apontam para `/tmp`, que o Termux não tem.

Sob supervisão o `klippy` roda como **root** (`services/klippy/run`), por uma razão que só
aparece depois de um reboot: o pty da ponte carrega um rótulo de SELinux que um processo de app
não consegue abrir, e nenhum `chmod`, `chown` ou `chcon` muda isso. Ver a seção de SELinux das
armadilhas. Iniciado à mão por `nohup` de um shell root funciona de qualquer jeito, e é
exatamente isso que esconde o problema.

## 6. Verificar pelo efeito, não pela ausência de erro

```bash
awk '/Start printer at/{n=NR} /Loaded MCU/{m=NR} END{print (m>n)}' ~/pdata/logs/klippy.log   # 1 = placa respondeu
grep -c "Unhandled exception" ~/pdata/logs/klippy.log                                        # 0 = ficou de pé
grep -o "srtt=[0-9.]* rttvar=[0-9.]*" ~/pdata/logs/klippy.log | tail -3
grep -o "bytes_retransmit=[0-9]* bytes_invalid=[0-9]*" ~/pdata/logs/klippy.log | tail -2
grep -c "Timer too close" ~/pdata/logs/klippy.log
```

E lembre que o log ficar mudo depois de um minuto é normal — um Klipper ocioso não escreve
nada. O socket de API é a fonte da verdade (`scripts/klipctl.py`, ou o comando de uma linha nas
armadilhas).

## 7. Moonraker e Mainsail

É o que dá pausar, retomar e cancelar, e portanto o que torna razoável imprimir algo que
importe.

```bash
pkg install -y libsodium python-pillow libjpeg-turbo unzip
git clone --depth 1 https://github.com/Arksine/moonraker.git ~/moonraker

# --system-site-packages: aproveita o python-pillow do Termux em vez de compilar o Pillow no 3.14.
python -m venv --system-site-packages ~/moonraker-env
~/moonraker-env/bin/pip install -r ~/moonraker/scripts/moonraker-requirements.txt
```

O Moonraker tem seu próprio patch obrigatório (`patches/moonraker-android.diff`): o
`proc_stats` varre `/sys/class/hwmon/`, que existe mas um processo de app não pode abrir — o
`isdir()` passa, o `scandir()` estoura e o componente derruba o Moonraker na carga. Sob
supervisor isso é laço de reinício.

```bash
git -C ~/moonraker apply /caminho/para/patches/moonraker-android.diff
grep -q '_hwmon_ok' ~/moonraker/moonraker/components/proc_stats.py && echo "patch ok" || echo "FALTANDO"
```

Todas as dependências compiladas — `streaming-form-data`, `dbus-fast`, `zeroconf`, `libnacl` —
geraram wheel `cp314-android_24_arm64_v8a` sem intervenção. O Python 3.14 não foi obstáculo
aqui.

Rode **como módulo, de dentro do repositório**; o `server.py` direto não funciona mais:

```bash
cd ~/moonraker && nohup ~/moonraker-env/bin/python -m moonraker -d ~/pdata &
```

Um `moonraker.conf` mínimo está em `config/`. Os dois campos que importam:

```ini
[server]
klippy_uds_address: /data/data/com.termux/files/home/pdata/run/klipper.sock
[machine]
provider: none
```

**Mainsail**, servido sem nginx (o nginx do Termux não linka, e o conserto óbvio pode levar o
`sshd` junto — ver armadilhas):

```bash
mkdir -p ~/mainsail && cd ~/mainsail
curl -sSL -O https://github.com/mainsail-crew/mainsail/releases/latest/download/mainsail.zip
unzip -oq mainsail.zip && rm mainsail.zip
# no config.json: "hostname": null, "port": 7125, "instancesDB": "browser"
nohup ~/moonraker-env/bin/python ~/serve_mainsail.py &   # Tornado, porta 8080
```

`"hostname": null` faz o Mainsail falar com o Moonraker no host da própria URL, então a
montagem sobrevive à troca de IP do celular.

### Verificar, de novo pelo efeito

```bash
curl -s http://<celular>:7125/server/info | grep -o '"klippy_connected":[a-z]*'   # true
curl -s -o /dev/null -w '%{http_code}\n' http://<celular>:8080/                   # 200
curl -s "http://<celular>:7125/printer/objects/query?extruder"                    # temperatura viva
```

Depois abra o Mainsail num navegador. O `curl` não aplica CORS, então um `200` dele não prova
que a interface vai conectar — se a página ficar em "Connecting", a origem que você está usando
está faltando no `cors_domains`.

## 8. Supervisão e boot

Quando tudo funciona à mão, ponha sob o runit. `services/` tem as cinco definições (`bridge`,
`klippy`, `moonraker`, `mainsail`, `watchdog`) e o script de boot.

Use um **diretório de serviços próprio**, `~/pdata/sv`, não o `$PREFIX/var/service`: aquele
pertence a pacotes, e os serviços que vêm lá giram num laço de reinício de log que queimou 22
minutos de CPU em 14 horas. Copie as definições sem nenhum diretório `supervise/`.

```bash
mkdir -p ~/pdata/sv && cp -r services/{bridge,klippy,moonraker,mainsail,watchdog} ~/pdata/sv/
cp scripts/watchdog.py scripts/serve_mainsail.py ~/
runsvdir ~/pdata/sv &
```

A persistência no boot precisa do addon **Termux:Boot**, assinado com a mesma chave do seu
Termux (`dumpsys package com.termux` diz qual build você tem), mais os dois passos por `su` das
armadilhas — armar o receptor e isentar os dois pacotes do Doze. O script de boot vai em
`~/.termux/boot/`. A primeira linha dele sobe o `sshd`, de propósito: o que quer que falhe
depois, ainda dá para entrar.

**Depois reinicie o celular.** É a única coisa que prova persistência, e é onde a parede do
SELinux aparece se algum serviço ainda estiver rodando como o usuário errado.

O caminho de recuperação foi medido, não suposto: mate a ponte, não toque em nada, e a
impressora está de volta em `ready` em 48 segundos.

## 9. Debloat (opcional, mas rende)

O celular vira um host de impressora sem tela; quase todo app de fábrica é peso morto. Escolha
o que remover pelo que **roda** (`dumpsys meminfo`) e pelo que **acorda o aparelho**
(`dumpsys batterystats`), não pelo que está instalado — e deixe um teclado, o launcher, as
configurações e tudo de Wi-Fi. Sem SIM inserido, modo avião com Wi-Fi ligado remove o maior
consumidor isolado, o modem procurando rede. Os detalhes e a única armadilha que isso armou
(um laço de crash da telefonia no reboot seguinte) estão nas armadilhas.
