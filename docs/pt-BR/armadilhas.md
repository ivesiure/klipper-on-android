# Armadilhas

Este é o documento mais valioso do repositório. Cada item descreve uma falha que é
**silenciosa** ou que **aponta o diagnóstico para outro lugar** — foi isso que tornou cada uma
cara. Estão agrupadas por camada e, dentro de cada grupo, mais ou menos por quanto custaram.

Sempre que há um conserto, é o que de fato segurou, não o primeiro que foi tentado.

## Protocolo e serial

### O limiar do VLQ do Klipper é `0x60`, não `0x80`

O Klipper codifica inteiros como quantidades de comprimento variável. A suposição natural é que
um valor cabe num byte quando está abaixo de `0x80`. Não cabe: o parser usa
`(c & 0x60) == 0x60` como marca de **sinal**, então valores de 96 a 127 precisam de dois bytes,
e a codificação em um byte é lida pelo MCU como número negativo.

```python
if v >= 0x60 or v < -0x20:
    out.append(((v >> 7) & 0x7f) | 0x80)
out.append(v & 0x7f)
```

O sintoma é exato e enganoso: pedir o dicionário de dados em blocos de 40 bytes funciona até o
offset 80 e **trava em 120 bytes recebidos, sempre no mesmo ponto** — o que parece falha de
transporte.

### O pty precisa de modo raw nas duas pontas

Um pseudo-terminal vem com disciplina de linha, e a disciplina de linha come bytes do
protocolo. O caso fatal: `0x11` e `0x13` são XON/XOFF, e o byte de sequência do Klipper é
`0x10 | n` — então `0x11` aparece o tempo todo.

O sintoma é uma transferência que devolve **zero bytes, sem erro em lugar nenhum**. Tanto o
lado do driver quanto o lado de quem lê precisam estar em modo raw.

### Bloco partido entre leituras não pode ser descartado

Pelo pty os dados chegam fragmentados. Um enquadrador que avança um byte quando o bloco está
incompleto come o começo desse bloco.

```python
if n < 5 or n > 64:      # lixo: descarta só este byte
    i += 1; continue
if i + n > len(buf):     # incompleto: guarda para a próxima leitura
    break
```

### `0x7e` não delimita bloco de forma confiável

O byte de sincronismo aparece dentro de cargas comprimidas (o dicionário de dados vem em zlib).
Enquadre pelo byte de tamanho e valide o CRC16-CCITT em vez de procurar `0x7e`.

### Repetir um número de sequência gera enxurrada de ack vazio

O MCU trata bloco com `seq` repetida como retransmissão e responde com um ack vazio
(`05 11 8f 08 7e`). Mais de 6 KB disso passaram antes de a causa aparecer. A `seq` que vem no
bloco recebido é a que o MCU espera **a seguir** — use ela.

## Klipper no Android

### `chelper` compila mas não carrega: falta `-lm`

```
dlopen failed: cannot locate symbol "atan2"
```

O objeto compartilhado **é gerado**; ele só falha no `dlopen`, o que faz parecer problema de
toolchain. A glibc resolve `atan2` implicitamente; o **Bionic não**. Acrescente `-lm` a
`COMPILE_ARGS` em `klippy/chelper/__init__.py` — ver `patches/klipper-android.diff`.

### `os.getloadavg()` não existe no Android — e derruba o `klippy` *depois* de conectar

```
AttributeError: module 'os' has no attribute 'getloadavg'
```

É chamado de `klippy/extras/statistics.py`. Dos dois patches, este é o pior de esquecer: o
`Loaded MCU` sai, tudo parece certo, e o processo morre um segundo depois por um **timer de
estatística**. Você vai olhar a ponte, a serial e o firmware antes de olhar um módulo de
estatística. O conserto que preserva a função é cair para `/proc/loadavg`, que existe no
Android. Confira que o patch entrou **antes** de subir o `klippy` (`instalacao.md` tem os
comandos de uma linha).

### A taxa do pty é fictícia — e isso resolve um erro que parece fatal

```
NotImplementedError: non-standard baudrates are not supported on this platform
```

O pyserial tenta configurar 250000 baud no pty, e 250000 não é taxa POSIX padrão. Não brigue
com o pyserial: não existe UART daquele lado do pseudo-terminal. A taxa real é definida pelo
driver, no CH340. Ponha `baud: 115200` no `[mcu]` e siga — nada muda no fio.

### O `-I` do `klippy` tem padrão `/tmp/printer`, e `/tmp` não existe no Termux

O diretório temporário do Termux é `$PREFIX/tmp`. Passe `-I`, `-a` e `-l` explícitos.

### O log parar não significa que o `klippy` morreu

O `klippy.log` congelou numa linha `Stats` e não escreveu nada por 43 minutos. O processo
continuava no `ps`, e a leitura ingênua — "travou" — estava errada: o socket de API respondia
`{"state": "ready", "state_message": "Printer is ready"}` o tempo todo.

A causa está em `statistics.py`:

```python
if max([s[0] for s in stats]):
    logging.info("Stats %.1f: %s", eventtime, stats_str)
```

Cada callback devolve `(ativo, texto)`. Com a impressora ociosa nenhum subsistema se declara
ativo, e o Klipper não escreve nada. **Silêncio no log é ocioso, não morto.**

Duas leituras erradas que isso induz, as duas cometidas aqui:

* `Stats N` não é o uptime do host. `N` é o relógio monotônico da máquina. O uptime real sai
  da linha `Start printer at ... (<epoch> <monotônico>)`: subtraia o monotônico de início do
  último `Stats`.
* `ps` mostrando o processo não prova que ele está conectado, e `State: S (sleeping)` é o
  estado normal de um laço de eventos, não travamento.

A verificação que vale, e que é somente leitura (não move a máquina):

```bash
python -c '
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(6)
s.connect("/data/data/com.termux/files/home/pdata/run/klipper.sock")
s.sendall(json.dumps({"id": 1, "method": "info", "params": {}}).encode() + b"\x03")
print(s.recv(4096).split(b"\x03")[0].decode())'
```

Verifique pelo efeito, não pela ausência de erro.

### MCU preso em shutdown — e a ordem que de fato recupera

Se o `klippy` cair, a placa fica em shutdown e a reconexão falha com *"Can not update MCU
config as it is shutdown"*. Não é falha da ponte — o enlace fica perfeito enquanto a placa
recusa configuração.

Recupera sem tocar na impressora, **desde que nesta ordem**:

```
1. sv restart klippy      # pega o pty novo
2. FIRMWARE_RESTART       # tira o MCU do shutdown
```

Invertida, não faz nada. `FIRMWARE_RESTART` sozinho devolve `{"result": "ok"}` e não muda
nada, porque o `klippy` ainda está falando com o **descritor do pty velho** — o pty morre junto
com a ponte, e a ponte reiniciada cria um novo (`/dev/pts/1` vira `/dev/pts/3`). Nenhum comando
que viaje pelo enlace conserta um enlace que não existe mais. O `scripts/watchdog.py` automatiza
exatamente esta sequência.

## Configuração herdada de outro lugar

### O `printer.cfg` traz caminhos de outro host — e os uploads "somem"

Ao mandar imprimir pelo Mainsail:

```
virtual_sdcard file open
KeyError: 'speedteststructure_pla_36m32s.gcode'
Unable to open file
```

O arquivo subiu certo. O Moonraker gravou no diretório `gcodes` dele e o `/server/files/list`
o mostra. Quem não o encontra é o `klippy`, porque a seção `[virtual_sdcard]` de um
`printer.cfg` copiado de um host anterior (aqui, um container) apontava para um diretório que
não existe no celular.

O sintoma engana duas vezes: o `KeyError` mostra o nome em minúsculas porque o Klipper casa
nomes sem diferenciar caixa, o que faz parecer problema de nome de arquivo; e a interface
mostra o arquivo, porque quem lista é o Moonraker, não o `klippy`. **Os dois olham para pastas
diferentes, e só o `klippy` está errado.** Procure no `printer.cfg` qualquer caminho absoluto
que não tenha nascido nesta máquina.

## Moonraker e Mainsail no Android

### `[machine] provider: none` — sem isto o Moonraker não sobe

O padrão do Moonraker é falar com o systemd por D-Bus, e o Android não tem nem um nem outro.
`provider: none` em `[machine]` é obrigatório. O custo conhecido: o `update_manager` e o
controle de serviços pela interface (reiniciar/parar) deixam de funcionar.

### O comando `ip` não existe no Termux — e o Moonraker chama ele

```
FileNotFoundError: [Errno 2] No such file or directory: 'ip'
ShellCommandError: Error running shell command: 'ip -json -det address'
```

Não é fatal — o Moonraker sobe e funciona — mas enche o log a cada atualização de rede.
`pkg install iproute2`.

### O nginx do Termux não linka — e o conserto óbvio é perigoso

```
CANNOT LINK EXECUTABLE "nginx": cannot locate symbol "SSL_set_quic_tls_cbs"
```

O pacote do nginx foi compilado contra uma OpenSSL mais nova que a instalada. **Não resolva com
`pkg upgrade openssl`:** o `openssh` linka contra a mesma biblioteca, e se o `sshd` quebrar você
perde o único acesso remoto ao aparelho — o resto se conserta na mão, no celular.

O caminho que evita o problema inteiro: o Mainsail sabe falar direto com o Moonraker, sem
proxy. No `config.json` dele, `"hostname": null` e `"port": 7125`. O `null` faz o Mainsail usar
o host da própria URL, então isso também sobrevive à troca de IP do celular. Os arquivos
estáticos saem por um script Tornado de 12 linhas (`scripts/serve_mainsail.py`) — o Tornado já
está no virtualenv do Moonraker.

Se um dia voltar a usar proxy: o pacote do Mainsail não faz proxy sozinho. Sem rotear
`/websocket`, `/printer`, `/api`, `/access`, `/machine` e `/server`, a interface carrega e fica
eternamente em "connecting" — sintoma que não diz nada sobre a causa.

### O Moonraker virou pacote: `server.py` direto não roda mais

```
ImportError: attempted relative import with no known parent package
```

Rode `python -m moonraker -d <diretório-de-dados>` **de dentro do diretório do repositório**.

### CORS: o `curl` aprova o que o navegador reprova

O Moonraker devolve **200 sem `Access-Control-Allow-Origin`** para uma origem fora do
`cors_domains`. Para o `curl` isso é sucesso; para o navegador é falha de rede, e o Mainsail
mostra um "Connecting" infinito sem nomear o CORS. Quando o consumidor é uma página, teste com
o cabeçalho `Origin:` — senão o teste mede outra coisa.

Duas listas que se confundem: `trusted_clients` autoriza o **cliente** (por IP);
`cors_domains` autoriza a **página** (por origem). A API responder não prova que a interface
vai conectar. E `http://*.local` não casa com `http://localhost:8080` — o curinga é o domínio
`.local`, não o nome `localhost` — nem com um host que tenha porta anexada. Abrir o Mainsail no
navegador do próprio celular exige `http://localhost:8080` listado explicitamente.

## SELinux: a parede que só aparece depois de um reboot

Tudo nesta seção funcionava com os processos iniciados à mão por `nohup`, e quebrou no primeiro
boot de verdade. É a razão para não confiar em "está funcionando" antes de a máquina ter sido
reiniciada uma vez.

O celular roda SELinux em **Enforcing**. A ponte, por precisar de `/dev/bus/usb`, roda no
domínio do KernelSU, `u:r:ksu:s0`. O `klippy`, como processo de app, é
`u:r:untrusted_app_27:s0:c...`. Daí vêm três paredes, e nenhuma delas é permissão de arquivo.

### O pty herda o rótulo de quem o criou — e o app não abre o do root

| Criado por | Rótulo |
|---|---|
| App | `u:object_r:untrusted_app_all_devpts:s0:c...` |
| Ponte (`ksu`) | `u:object_r:devpts:s0` |

O `klippy` falha com `Permission denied` **mesmo com o nó em `crw-rw-rw-`**. `chown` não ajuda,
`chmod` não ajuda, e `chcon` é recusado **até para o root** — a política não permite reetiquetar
devpts para o tipo do app. Root não vence SELinux em enforcing.

### O socket unix é verificado contra o contexto do servidor, não contra o rótulo do arquivo

```
Cannot connect to Klippy, Linux user 'u0_aNNN' lacks permission to open
Unix Domain Socket: .../klipper.sock
```

Com o socket em `srwxrwxrwx`. Aqui o `chcon` até funciona (o tipo continua `app_data_file`; só
faltavam as categorias MCS) — **e mesmo assim não resolve**, porque o `connectto` é avaliado
contra o contexto do **processo que serve** o socket, não contra o rótulo do arquivo.

### A conclusão: quem fala com o `klippy` tem de estar no mesmo contexto

Não há meio-termo. Como a ponte é obrigada a ser `ksu`, **o `klippy` e o Moonraker também rodam
como root**. O servidor estático do Mainsail e o watchdog continuam como usuário normal: um só
serve arquivos, o outro fala com o Moonraker por **TCP** (`127.0.0.1:7125`), e TCP não sofre
desta restrição.

`umask 0` no `klippy` é obrigatório. Conectar a um socket unix exige permissão de **escrita**;
criado pelo root com a umask padrão o socket sai `0755` e barra o Moonraker por DAC comum, antes
de o SELinux sequer opinar.

Um efeito colateral bom: arquivos que o root cria dentro do home do Termux herdam
`app_data_file`, então logs e configs continuam legíveis pelo usuário normal.

## Supervisão (runit)

### O `runsv` não consegue parar um processo iniciado por `su`

`sv down` e `sv restart` **penduram até o timeout**: o `TERM` vai para o `su`, que não o repassa
ao processo root. Isso quebra o watchdog, que depende de `sv restart klippy`.

Conserto, nos `run` de `bridge`, `klippy` e `moonraker`: gravar o pid real e repassar o sinal à
mão. O `exec` faz o shell virar o processo, então `$$` já é o pid final:

```sh
su -c "echo \$\$ > $PIDF; exec ..." &
child=$!
trap "p=\$(cat $PIDF); [ -n \"\$p\" ] && su -c \"kill \$p\"; exit 0" TERM INT
wait $child
```

### Moonraker reinicia em laço por `/sys/class/hwmon/`

```
PermissionError: [Errno 13] Permission denied: '/sys/class/hwmon/'
```

O `proc_stats` faz `os.path.isdir()` (que passa) e depois `os.scandir()` (que estoura), e o
componente derruba o Moonraker inteiro na carga — sob supervisor, vira laço de reinício. O
`patches/moonraker-android.diff` checa `os.access` antes e cai para `/sys/class/thermal`, que é
legível.

### O `runsv` entrega ambiente vazio — e o `~` do root no Android é `/`

A ponte entrou em laço de reinício com:

```
OSError: [Errno 30] Read-only file system: '/dev/pts/1' -> '/printer'
```

O driver expande `~/printer`. Sob `nohup` funcionava porque herdava o `HOME` do shell
interativo. Sob `runsv` **não há `HOME` nenhum**, então o `expanduser` cai na entrada `pwd` do
usuário — e a do root, no Android, é `/`. O alvo virou `/printer`, num sistema de arquivos
somente leitura.

Exporte `HOME` e `LINK` explicitamente no `run` do serviço. Vale para todos os serviços, não só
a ponte: nunca conte com o ambiente sob supervisor.

### Os serviços que vêm com o `termux-services` giram em laço — e não são seus

O laço ocupado mais caro desta pilha. Medido 14 horas depois de um boot:

```
runsv sshd        50.338 ticks   (503 s de CPU)
runsv ssh-agent   50.322 ticks
runsv nginx       32.300 ticks
                  ────────────
runsv moonraker      178 ticks
runsv bridge         154 ticks
runsv klippy          28 ticks
runsv watchdog         2 ticks
runsv mainsail         2 ticks
```

**Vinte e dois minutos de CPU queimados por três serviços que estavam `down` e sem uso**, contra
3,6 segundos da pilha inteira construída aqui.

A causa: o `log/run` deles aponta para `/sv/<nome>`, caminho que não existe nesta instalação. O
`runsv` sobe o serviço de log **mesmo com o serviço principal `down`** — o `svlogd` morre na
hora, o `runsv` o ressuscita, para sempre.

Apagar os diretórios só dura até o próximo `pkg upgrade`: eles pertencem a pacotes (`sshd/` e
`ssh-agent/` ao `openssh`, que é o seu acesso e não pode sair; `nginx/` ao `nginx`).

O conserto durável: **um diretório de serviços próprio.** Só os seus cinco serviços em
`~/pdata/sv`, com o `runsvdir` apontado para lá pelo script de boot. O gerenciador de pacotes
pode recriar o que quiser em `$PREFIX/var/service`; nada daquilo será supervisionado.

Ao copiar definições de serviço, não leve o `supervise/` junto. `cp -a` copia o estado do
supervisor anterior (pids, fifos) e o `runsv` não sobe com a trava herdada — o sintoma é
`runsvdir` vivo, zero processos `runsv`, pilha inteira fora. `rm -rf */supervise` antes de
subir.

### O runit só reinicia o que morre — e um `klippy` em shutdown não morre

A lição mais cara da etapa de supervisão. Quando a ponte cai (que é o que acontece sempre que a
impressora reenumera), o runit a devolve com um **pty novo**. Mas o `klippy` **continua vivo**,
segurando o descritor do pty velho, e entra em `shutdown`. Para o supervisor está tudo bem: o
processo está de pé.

É por isso que existe o `scripts/watchdog.py` — um quinto serviço que sonda o estado da
impressora pelo Moonraker e dispara a sequência de recuperação acima. Medido de ponta a ponta:
matar a ponte, não fazer nada, e a impressora está de volta em `ready` em 48 segundos.

### Cortar a energia do hub mata a impressão em curso

O carregador do celular foi trocado no meio de uma impressão. O carregador alimenta o **hub**,
e o celular fala com a impressora **através dele**. O hub caiu e levou o CH340 junto:

```
device gone: [Errno 19] No such device
watchdog: klippy in shutdown for 2 readings -> sv restart klippy -> FIRMWARE_RESTART -> startup
```

O watchdog fez o trabalho dele e recuperou o `klippy`. A impressão não voltou, e não tinha
como: o Klipper não tem recuperação de queda de energia. Com o MCU em shutdown no meio do
trabalho, a posição do cabeçote e a fila de movimentos se perdem. É como o Klipper funciona, não
defeito desta pilha.

A consequência: **o hub é ponto único de falha para a impressão.** Com o celular ligado direto
na impressora, mexer no carregador não afetava nada. Agora afeta — e trocar de carregador é
exatamente o tipo de coisa que se faz sem pensar.

### `time.sleep` num laço que espera evento atrasa a morte do processo

Descoberto no mesmo incidente, e foi regressão introduzida no mesmo dia. O laço principal da
ponte era:

```python
while not stop.is_set():
    time.sleep(STATS_SECS)      # passou de 5 para 60 naquele dia
```

A thread que detecta o sumiço do dispositivo chama `stop.set()`, mas o laço principal está
dormindo e só verifica ao acordar. Com 5 segundos o atraso passava despercebido; com 60, a
ponte levava **até um minuto para morrer** — e o supervisor só a reinicia depois disso.
Justamente na hora em que se quer o processo de volta rápido.

```python
while not stop.wait(STATS_SECS):   # volta na hora quando o evento é setado
```

Medido: `Event.wait` saiu em 0,10 s onde o `time.sleep` levava o intervalo inteiro.

E o `print` do sumiço não tinha `flush`. Como a saída é um cano para o `svlogd`, ela é
bufferizada em bloco: a mensagem só aparecia no log no flush seguinte. **O log registrava a
falha depois da hora em que ela ocorreu** — o que engana exatamente quem está reconstruindo um
incidente por carimbo de tempo.

### Supervisor sem espera vira laço ocupado quando o dispositivo some

Descoberto por uso real, não por teste: a impressora foi desligada e a ponte entrou em laço. O
driver não encontra o CH340, sai, e o `runsv` — fazendo o trabalho dele — o ressuscita cerca de
uma vez por segundo. Medido: **122 tentativas em 2 min 25 s**, cada uma gerando um `su`, um
interpretador Python e uma varredura do sysfs. Uma noite de impressora desligada daria ~24 mil
reinícios e dezenas de MB de log, queimando bateria para descobrir a mesma coisa 24 mil vezes.

O conserto: esperar o dispositivo no `run`, antes de gastar um processo com ele. Um laço de
shell com `sleep 5` custa um `grep` a cada cinco segundos:

```sh
has_ch340() { su -c "grep -qs 1a86 /sys/bus/usb/devices/*/idVendor" 2>/dev/null; }
while ! has_ch340; do sleep 5; done
```

Depois: 0 tentativas em 45 s, contra ~38 antes.

O mesmo valia para o `klippy`, em escala menor: ele desistia do pty após 60 s e reiniciava,
~60 vezes por hora à toa — o pty só aparece quando a ponte sobe, e a ponte só sobe quando a
impressora liga. Agora ele também espera indefinidamente.

A lição geral: supervisor reinicia o que morre, e é isso que se pede dele. Se a causa da morte
é uma condição externa que vai demorar, quem tem de esperar é o **serviço** — senão supervisão
correta vira desperdício correto.

### Caminho de serviço embutido em script quebra calado

Quando a pilha migrou para `~/pdata/sv`, o caminho fixo dentro do watchdog ficou para trás. O
`sv restart klippy` dele passou a falhar com `runsv not running` — e o watchdog não checava o
retorno, então seguia para o `FIRMWARE_RESTART` como se tivesse funcionado.

O defeito ficou invisível porque a segunda metade mascarava a primeira: `FIRMWARE_RESTART`
sozinho às vezes recupera, quando o `klippy` já pegou um pty novo por outro motivo. A
recuperação "funcionava" em alguns casos e estaria morta exatamente no caso para o qual existe
— a ponte caindo enquanto o `klippy` segura o descritor velho. Achado por acidente, testando
outra coisa. Ao mover um diretório de serviços, procure o caminho **em todo lugar**: arquivos
`run`, scripts de boot e dentro do código de qualquer coisa que chame `sv`.

### Sem `termux-wake-lock` o Android suspende tudo

Vai no script de boot, antes do `runsvdir`.

### O `sshd` não sobe sozinho — e um reboot teria deixado o aparelho inalcançável

A armadilha mais perigosa desta etapa, achada **antes** de qualquer reboot. O `sshd` tinha sido
iniciado à mão: não está sob o runit (o serviço `sshd/` vem com arquivo `down`) e não tinha
mecanismo de boot nenhum. O script de boot só subia o `runsvdir`.

Um reboot teria deixado o celular sem SSH e sem conserto remoto — só na mão, no aparelho. O
`sshd` é agora a **primeira linha** do script de boot, antes até do wake-lock, para que um
defeito em qualquer outro ponto da pilha ainda deixe uma porta de entrada. Ao montar boot
automático, comece pela via de acesso, não pelo serviço que interessa.

### Termux:Boot é um APK — e a assinatura tem de casar

O `runsvdir` sobe a pilha, mas quem o inicia depois de um reboot é o addon **Termux:Boot**, um
aplicativo separado. Dá para instalá-lo por SSH com root (`pm install`), mas o addon tem de ser
assinado com a **mesma chave** do Termux instalado.

Para descobrir qual: `dumpsys package com.termux`. `pkgFlags=[ DEBUGGABLE ]` com
`installer=null` significa a **build debug do GitHub**, então o addon tem de ser o
`termux-boot-app_*+github.debug.apk`; o do F-Droid seria recusado por assinatura incompatível.
Confira depois que `signatures:[...]` é idêntico nos dois pacotes.

Instalar não basta. Faltam dois passos, os dois por `su`:

```
am start -n com.termux.boot/.BootActivity            # arma o receptor; sem isto ele nunca dispara
dumpsys deviceidle whitelist +com.termux.boot        # no Android 10 o Doze engole o receptor
dumpsys deviceidle whitelist +com.termux
```

### `pgrep -f` também casa com a própria linha de comando

`pgrep -c -f klippy` conta a sua própria sessão SSH. O truque do colchete — `pgrep -f "[k]lippy"`
— não casa consigo mesmo. O mesmo vale, com consequência pior, para o `pkill -f` (abaixo).

## Ambiente

### O número do dispositivo USB muda a cada replug

`001/004`, depois `001/005`, depois `001/002` numa única sessão. Descubra o dispositivo por
**VID:PID** varrendo `/sys/bus/usb/devices/*/idVendor`. Fixar o caminho é garantia de quebrar.

### `greenlet==3.1.1` não compila no Python 3.14 (o do Termux)

Use `greenlet>=3.2`. E o `pip` é atômico por execução: com o greenlet falhando, **nada** é
instalado, embora as rodas fiquem em cache. Instale com a linha do greenlet filtrada do arquivo
de requisitos. Todos os outros pins antigos compilam, inclusive `markupsafe==1.1.1`.

### Python como root no Termux precisa de caminho completo

`su -c "/data/data/com.termux/files/usr/bin/python <script>"` — o `PATH` do root não inclui os
binários do Termux. E depois de `su`, `pkg` e `apt` somem: gerencie pacote como usuário normal.

### `pkill -f <padrão>` num comando remoto mata a própria sessão

Se o padrão aparece na linha de comando que o invoca, o `pkill` casa com ela também. Várias
sessões SSH foram perdidas assim, com sintoma de "rede instável". Use pidfile.

### Sem hub com entrada de energia, o celular não carrega

Ele é host USB e **fornece** energia. Para qualquer coisa longa o hub é requisito, não conforto
— ver os números nos resultados.

### `proot-distro` intercepta syscalls por ptrace

Isso acrescenta latência exatamente na grandeza que este projeto mede. Instale nativo no Termux.

## Manutenção num host Samsung

Estes são específicos do celular usado aqui, mas a forma do problema é geral: um celular
transformado em servidor sem tela continua rodando coisas de que um servidor não precisa.

### Escolha o que remover pelo que *roda*, não pelo que está instalado

APK dormente não custa nada além de disco. O que custa bateria é o que executa:

```bash
dumpsys meminfo | sed -n '/Total PSS by process/,/Total PSS by OOM/p'
```

Foi assim que saiu a primeira lista: o assistente, o serviço de reconhecimento facial, a loja
de apps, os serviços de conta do fabricante e o app de busca somavam ~470 MB em execução num
aparelho cujo trabalho é ser ponte USB. `pm uninstall --user 0 <pacote>` remove para o usuário
sem apagar o APK (ele fica em `/system`, somente leitura), e é por isso que
`cmd package install-existing <pacote>` reverte sem baixar nada — e por isso um factory reset
traz tudo de volta.

### Filtrar por memória acha uma coisa; filtrar por despertar acha outra

A primeira rodada usou `dumpsys meminfo` e pegou os processos gordos. Certo, mas incompleto —
num aparelho sempre acordado, o que custa bateria não é ocupar RAM, é acordar a CPU. O
`dumpsys batterystats` mostra o que o `meminfo` não mostra: jobs agendados, serviços de push e
whitelists temporárias que acordam o aparelho por conta própria. E os rádios, que não são
pacote nenhum: sem SIM inserido, o `Cell standby` era o maior consumidor isolado — o modem
procurando uma rede que nunca virá. **Modo avião com o Wi-Fi ligado** elimina isso, e o Wi-Fi
sobrevive ao modo avião (confirmado por uma sessão SSH ininterrupta). Varredura Bluetooth e NFC
também estavam ligados e não aparecem em lugar nenhum além do histórico de bateria.

### Deixe um teclado, deixe o launcher, deixe as configurações

Sem um app de teclado de verdade não se digita na tela — e se o Wi-Fi cair e for preciso
digitar a senha de novo no aparelho, você fica sem como escrever. Com o SSH como único acesso,
o teclado é seguro contra travamento. Nunca remova o Termux, o Termux:Boot, a UI do sistema, o
launcher, as configurações, o instalador de pacotes nem nada relacionado a Wi-Fi.

### Remover o agente de atualização do fabricante é decisão, não descuido

Num aparelho com root e kernel customizado, uma atualização OTA chegando sozinha pode mudar o
kernel, a política do SELinux ou permissões — no meio de uma impressão. Os agentes de
atualização foram removidos de propósito.

### O primeiro reboot depois do debloat pôs a telefonia em laço de crash

Sintoma: o aparelho "engasgando" a cada poucos segundos logo depois de um reboot, sem nada novo
aberto. Load average perto de 10; `system_server`, `logd` e `rild` no topo.

Causa: o serviço de IMS (VoLTE) do fabricante tinha sido desinstalado do usuário 0, mas o
sistema continua registrando o content provider dele como seu. O processo de telefonia tenta
ligá-lo no boot, falha com `SecurityException: Failed to find provider`, cai, é religado pelo
Android, e o fabricante gera um **relatório de bug (`dumpstate`) a cada queda** — 124 quedas e 7
relatórios em 20 minutos. É o `dumpstate` que engasga. Não apareceu no dia do debloat porque o
processo de telefonia já rodava e nunca religou o IMS; o reboot seguinte foi o primeiro desde
então. Modo avião não evita: a tentativa é no boot, antes de o rádio importar.

Diagnóstico em um comando — um processo só, centenas de vezes, é laço:

```bash
su -c "logcat -d -b crash" | grep Process: | awk '{print $(NF-2)}' | sort | uniq -c
```

Conserto: `su -c "pm install-existing <pacote-ims>"` — devolve o app de sistema ao usuário (o
APK nunca saiu de `/system/priv-app`). As quedas pararam no ato; reversível com
`pm uninstall -k --user 0`.

### Remover um bloqueio de tela cujo padrão foi gravado errado, com root

Um padrão definido e não aceito (a digital abre, mas o aparelho pede o padrão periodicamente).
`cmd lock_settings clear --old …` não ajuda: ele confere a credencial antiga antes, e sem ela
não há o que conferir. O que funcionou, num aparelho cujo armazenamento **não era cifrado**
(`ro.crypto.state = unsupported` — sem isso seria perigoso): fazer backup e remover
`/data/system/locksettings.db*` e `/data/system_de/0/spblob/`, e reiniciar. Sobe sem bloqueio;
as digitais precisam ser recadastradas; certificados de CA instalados pelo usuário não são
afetados.
