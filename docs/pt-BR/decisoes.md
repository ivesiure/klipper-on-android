# Decisões, e por quê

## Por que um celular e não um Raspberry Pi

O argumento é de **alocação**, não de gosto. Um Pi pode ser customizado e servir a muitos usos;
o celular ainda funciona bem e não tinha nenhum. E o celular traz de fábrica o que um Pi
precisaria montado em volta: bateria, carregamento, tela e sensores legíveis pelo shell. Há
evidência disso na própria história do projeto — horas foram gastas desenhando, para o Pi, um
UPS com microcontrolador, optoacoplador na rede elétrica e circuito de religar. O celular vem
com tudo isso.

## Por que KernelSU e não Magisk

Sete tentativas com Magisk falharam, todas em bootloop, e todas pela mesma razão: o Magisk
injeta o `magiskinit` no **ramdisk**, e neste aparelho era essa a camada quebrada. Os suspeitos
de sempre foram eliminados com evidência — versão do Magisk (duas versões bem diferentes
falharam igual), tar reduzido contra pacote de firmware completo (o `boot.img` era idêntico byte
a byte), criptografia do `/data` (formatado com o boot novo já gravado), rejeição pelo
bootloader (a tela prova que ele aceita a imagem), AVB 2.0 (a partição `vbmeta` está zerada) e
dm-verity (flags ausentes do ramdisk, confirmado por leitura).

O KernelSU compila o root dentro do próprio kernel, não toca no ramdisk, e bootou de primeira.

A versão do app gerenciador **tem de casar com a do kernel**. Com um app mais novo ele mostra
"em execução" e mesmo assim não funciona, porque aquele número é o kernel se apresentando, não o
app.

## Por que um driver próprio e não o Octo4a

O ecossistema inteiro instala o Octo4a — um servidor OctoPrint completo em Java — só para
emprestar o driver serial dele. E com CH340 isso falha: há uma issue exatamente sobre isso,
fechada sem solução, e ela é o primeiro resultado de busca para o sintoma. Ver
[`estado-da-arte.md`](estado-da-arte.md).

## Por que não recompilar o kernel com `ch341`

É uma linha no defconfig (`CONFIG_USB_SERIAL_CH341=y`) e o fonte é público. Continua sendo uma
saída válida — mas exige toolchain, build e gravar uma imagem de boot, e o driver em espaço de
usuário resolve sem nada disso. Se um dia o driver em espaço de usuário incomodar, a opção do
kernel está a uma linha de distância.

## Por que não uma ponte CDC-ACM externa (ESP32-C3, FTDI, RP2040)

Também funciona: o kernel **tem** `cdc_acm`, `ftdi_sio` e `pl2303`. Era o plano até o driver
funcionar. Exige peça e solda na UART da placa — abrir a impressora. Fica como plano B.

## Por que o trio também fica no host anterior

O host anterior do Klipper (um servidor doméstico rodando a pilha em containers) mantém seus
containers `klipper`, `moonraker` e `mainsail`, **parados**, como backup. O caminho de volta é
subi-los e trocar o cabo USB de lugar — com o celular desplugado da placa antes, porque dois
hosts numa mesma serial não é um estado que alguém queira. O proxy reverso do servidor encaminha
o endereço antigo do Mainsail para o celular, então nada mudou nos favoritos de ninguém.

## Por que os patches não foram enviados upstream

Os dois bugs são reais e continuam sem correção upstream (`chelper` sem `-lm`,
`os.getloadavg()` chamado cru no `statistics.py`). Mas o retorno era incerto — o Klipper revisa
devagar, e o do `getloadavg` esbarraria num legítimo "não damos suporte a Android" — e o custo
era tempo de revisão. Os arquivos `.diff` daqui são, portanto, uma **receita de reconstrução**,
não material para pull request: se o Klipper ou o Moonraker forem reinstalados no celular, é
assim que dois dias de diagnóstico não se repetem.
