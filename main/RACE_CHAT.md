# Race Chat / IA — configuração e limites

Implementado em 21/09/2026 como recurso adicional do Overlay. No código-fonte, execute `main/main.py` normalmente e use a linha **RaceChat** no Manager: **ON/OFF** liga ou desliga; **Config** abre os controles. Para experimentar só o chat, sem iniciar a telemetria:

```powershell
cd C:\Users\27b\Desktop\overlay
.\.venv\Scripts\python.exe main\racechat.py
```

O executável que já está aberto não recebe alterações Python automaticamente. Esta implementação não encerra nem substitui esse executável. Use o código-fonte ou faça uma compilação posterior, quando não estiver a correr. Não há dependências novas além do requirements existente (PyQt6 inclui QtMultimedia; websocket-client serve EventSub).

## Sincronização entre os perfis 27 e 27b

Cada perfil mantém `AppData\Local\OverlayRaceChat` e segredos DPAPI do próprio usuário. O script recuperado `C:\Users\27\Documents\ProfileSync\SYNC_IRACING_VOICEMEETER_27_27B.ps1` chama `OverlayApp.exe --racechat-sync`, sem abrir o Manager, conectar contas ou publicar mensagens. A tarefa existente continua executando no login de 27; ao abrir o overlay atualizado uma vez como 27b, a migração e o gancho de login desse perfil são preparados automaticamente. As contas do iRacing permanecem fora do armazenamento de RaceChat.

A transferência usa snapshots DPAPI da máquina em pastas locais de cada perfil, com DACL sem herança permitindo somente 27, 27b e os administradores/SYSTEM do Windows. O destino recriptografa os segredos com DPAPI do seu usuário; não existem tokens em texto aberto. O app verifica as permissões antes de ler ou gravar uma transferência. As alterações são conciliadas por campo, incluindo renovação e limpeza explícita de tokens; um perfil novo e vazio não apaga as contas do outro. Os originais ficam em `profile-sync-originals`. As configurações e transferências são reconciliadas no login, ao abrir/ler o armazenamento e ao salvar. Mudanças de destino em conexões já abertas passam a valer ao reconectar essas conexões.

As credenciais antigas de 27b só podem ser migradas dentro desse perfil. Até a primeira abertura ali, 27 recebe os destinos e informa que falta migrar as credenciais, sem tentar conectar. O modo `--racechat-sync --dry-run` verifica a política sem escrever dados.

## O que está disponível

- Painel discreto, sempre no topo, sem aceitar foco de teclado; permite arrastar com o botão esquerdo e salva a posição ao soltar. Monitor, posição e dimensões configuráveis, incluindo monitores com coordenadas negativas. Fora do cockpit fica oculto por padrão na integração; há opção explícita para mostrar fora do iRacing.
- Janela de controlo separada com mensagens de Discord, Twitch e YouTube, plataforma/autor/destino, seleção para responder, digitação, conversa com IA e ditado.
- O controle isolado começa desligado e sem mensagens de exemplo. Desligar preserva o histórico real em memória e remove mensagens simuladas. Respostas locais simuladas à IA, solicitadas pelo utilizador enquanto desligado, têm **DEMO** em cada mensagem, inclusive no painel; o título permanece **RaceChat**. Na integração, ON liga as contas salvas e OFF desliga; o estado ON/OFF é preservado como nos outros widgets.
- Discord: leitura por REST a cada 3 s. Um ID de servidor ativa descoberta dos canais de texto, anúncios e tópicos ativos acessíveis ao bot, atualizada a cada minuto. Alternativamente, aceita até 8 IDs de canais fixos. Bot, apenas mensagens novas depois de conectar, nome do canal e autor, cursor, deduplicação, backoff e envio explícito. O histórico inicial é usado somente para estabelecer o cursor e não aparece no painel. Não é um cliente completo de Discord: não sincroniza edições/remoções, membros ou presença.
- Twitch: EventSub WebSocket `channel.chat.message`, validação do token no início e periodicamente, keepalive, reconexão, deduplicação e API `chat/messages` para enviar. Recusa de moderação não é mostrada como sucesso. Uma ligação a um canal por vez.
- YouTube: descobre `activeLiveChatId` pelo ID do vídeo ao vivo, ignora o lote inicial de histórico e segue `nextPageToken` e `pollingIntervalMillis`; envia mensagens de texto via API. Uma live por vez. Não transmite vídeo.
- IA própria via OpenAI Responses, transcrição e síntese de voz. Conversa recente só em memória; `store:false` na Responses. Áudio fica em memória nesta aplicação. Isto não altera políticas de retenção do fornecedor. A sua conta API e cobrança são separadas; não herda conversa, credenciais ou assinatura Codex.

## Fluxo de uso e atalhos

1. Configure contas e destinos na aba **Configuração local**, salve e clique **Ligar contas configuradas**. Pode ligar apenas a IA, deixando destinos vazios. Uma plataforma incompleta é desligada com aviso, sem bloquear as outras.
2. Selecione uma mensagem: o destino muda para a plataforma/canal correspondente. Discord/Twitch usam resposta à mensagem selecionada quando disponível. YouTube envia ao canal; escreva `@nome` no texto se quiser identificar a pessoa, pois esta implementação não cria threads YouTube.
3. Escreva uma resposta, ou escolha **Ditar resposta para o destino selecionado**. Ative conscientemente o microfone selecionado. Prefira headset; não selecione loopback/mistura estéreo se não pretende transmitir áudio de outras pessoas.
4. **Ctrl+Alt+F9** inicia/termina gravação (máximo 30 s). Não é escuta contínua. A transcrição preenche o rascunho e mantém o destino escolhido no início do ditado.
5. **Ctrl+Alt+F11** ou **Enviar resposta** publica o rascunho no destino visível. **Ctrl+Alt+F10** lê a mensagem selecionada ou, sem seleção, as últimas cinco. Atalhos só ficam registados quando abrir Race Chat; se já estiverem ocupados, use os botões. Não substituem os atalhos existentes.
6. No modo **Falar com a IA**, a transcrição inicia conversa. Comandos exatos `ler mensagens` / `leia as mensagens` fazem a leitura, e `enviar resposta` publica o rascunho atual. Escolha o modo de ditado para ditar essas palavras literalmente. Reconhecimento de voz pode errar; o atalho físico é a opção mais previsível para publicação.
7. A opção **Incluir últimas 12 mensagens** envia esse contexto à OpenAI apenas quando perguntar à IA. Mensagens recebidas não provocam chamadas automáticas. A IA não possui ferramentas de publicação nem de execução local; somente ações explícitas do utilizador enviam mensagens.

Durante gravação há indicador no botão e no painel. Desmarcar o consentimento, fechar a janela, desligar ou sair interrompe a gravação. Fechar a janela de controlo integrada preserva o painel e as ligações; use **Disconnect** para parar rede/voz. Um pedido HTTP de envio já transmitido não pode ser desfeito ao desligar. Falhas ambíguas nunca provocam reenvio automático: verifique o canal antes de repetir.

## Cadastro e autorização — links oficiais

### Discord

1. Abra o [Discord Developer Portal](https://discord.com/developers/applications), crie uma aplicação e configure o **Bot**. Use exclusivamente o token do BOT, nunca token de conta pessoal/self-bot.
2. Ative **Message Content Intent** em Bot/Privileged Gateway Intents. Conforme o tamanho/estado de verificação da app, pode ser necessária aprovação. Sem esse acesso, o conteúdo pode vir vazio mesmo em REST.
3. Em Installation/OAuth2 URL Generator escolha instalação em servidor e scope `bot`. Permissões mínimas desta versão: **View Channels**, **Read Message History**, **Send Messages**. Não conceda Administrator. Para threads, é preciso permissão específica Send Messages in Threads e acesso à thread.
4. Abra o link de instalação gerado pelo portal para adicionar o bot ao servidor que administra. Não há callback local Discord nesta versão: instalação do bot é feita no portal. Não adicionamos servidor nem enviamos teste automaticamente.
5. No Discord, ative Developer Mode e copie os IDs dos canais de texto. Insira-os separados por vírgulas. O ID do servidor ajuda na configuração, mas não é necessário para esta API por canal.
6. Cole o token apenas no campo local mascarado e salve.

Referências: [mensagens, conteúdo e permissões](https://docs.discord.com/developers/resources/message), [instalação de apps](https://docs.discord.com/developers/quick-start/getting-started).

### Twitch

1. Abra o [console de aplicações Twitch](https://dev.twitch.tv/console/apps) e registe uma aplicação do tipo **Public** para Device Code. Use o Client ID e o login do canal na configuração local, depois salve.
2. Clique **Autorizar Twitch no navegador**. O botão solicita Device Code e abre a URL oficial devolvida pela Twitch. Entre na conta que deverá ler/enviar mensagens e autorize `user:read:chat` e `user:write:chat`.
3. **Não há callback/redirect URI utilizado por este fluxo.** Caso o formulário de cadastro exija um valor, pode cadastrar `http://localhost` como campo administrativo; este programa não escuta nem recebe tokens nesse endereço. Não configure 18765 como callback Twitch. Não usa Client Secret.
4. O token fica cifrado localmente após autorização. Clique **Ligar contas configuradas**. Não confunda a conta autorizada (remetente) com o canal a acompanhar.

A autorização guarda access token e refresh token com DPAPI. Ao receber HTTP 401, renova e repete o pedido uma única vez; falhas de rede ou timeout não repetem publicações. Sem refresh token válido, solicita nova autorização. Tokens guardados antes desta atualização precisam de nova autorização para obter refresh token. Tokens inseridos manualmente também devem pertencer ao mesmo Client ID. Ligações interrompidas podem perder mensagens no intervalo; EventSub não fornece histórico por este conector.

Referências: [registar aplicação](https://dev.twitch.tv/docs/authentication/register-app/), [Device Code OAuth](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#device-code-grant-flow), [chat e permissões](https://dev.twitch.tv/docs/chat/authenticating/), [EventSub WebSocket](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).

### YouTube / Google

1. Abra o [Google Cloud Console](https://console.cloud.google.com/) e selecione/crie um projeto. Ative [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).
2. Configure o [Google Auth Platform / consentimento](https://console.cloud.google.com/auth/overview). Para app em teste, inclua a sua conta entre os utilizadores de teste. Configure o scope `https://www.googleapis.com/auth/youtube.force-ssl`, requerido para publicação. Google pode exigir verificação para distribuição pública/escopos sensíveis.
3. Em [clientes OAuth](https://console.cloud.google.com/auth/clients), crie **Desktop app / Aplicativo para computador** e descarregue o JSON. Não escolha Web Application.
4. Clique **Autorizar YouTube — importar JSON Google Desktop** e selecione o JSON local. O programa lê `installed.client_id/client_secret`, usa endpoints oficiais fixos, PKCE S256 e `state` aleatório, abre o navegador e recebe o código exclusivamente em **`http://127.0.0.1:18765/`**. A porta só fica aberta durante autorização (até 3 min). Se ocupada, falha sem alterar serviços/firewall. Clientes Desktop permitem loopback; não há lista de redirects Web para cadastrar.
5. Escolha a conta/canal que deverá publicar. A aplicação guarda access token, refresh token e dados do cliente Desktop com DPAPI; o JSON original permanece onde o descarregou, não é copiado ao projeto. Guarde-o privadamente. O access token é renovado após HTTP 401 quando existe refresh token válido. Se a autorização for revogada ou o refresh token expirar, repita a autorização; o cliente cifrado é reutilizado pelo botão.
6. Insira o **ID do vídeo ao vivo**, 11 caracteres, obtido de `v=` ou do caminho `youtu.be/`. Salve e ligue. O chat precisa estar ativo; vídeo gravado, live terminada ou chat desativado não funcionam.

Referências: [OAuth Desktop e loopback](https://developers.google.com/identity/protocols/oauth2/native-app), [leitura e intervalo de polling](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list), [publicação e scope](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/insert). Uso de polling consome quota; erros 403 exigem verificar quota/permissões. O conector não implementa streamList nesta versão.

### OpenAI

Crie uma chave em [API keys](https://platform.openai.com/api-keys), configure faturação/limites no seu projeto e insira a chave no campo local. Defaults configuráveis: `gpt-4.1-mini`, `gpt-4o-mini-transcribe`, `gpt-4o-mini-tts`, voz `coral`. A disponibilidade depende da sua conta. Ative somente o seu microfone; respostas faladas são voz sintética de IA. Referências: [Responses/texto](https://developers.openai.com/api/docs/guides/text), [transcrição](https://developers.openai.com/api/docs/guides/speech-to-text), [síntese de voz](https://developers.openai.com/api/docs/guides/text-to-speech).

## Segredos e dados

Preferências não secretas em `%LOCALAPPDATA%\OverlayRaceChat\settings.json`; tokens/chave em `secrets.dpapi`, protegidos por DPAPI do utilizador Windows. Não ficam em `overlay.json`, no repositório, em logs ou URLs de erro. A aplicação não guarda histórico/áudio em disco. **Apagar credenciais guardadas** remove os valores locais; revogação nas plataformas continua a ser necessária para invalidar tokens remotamente. Não envie tokens/chaves/JSON secreto pela conversa.

Para preparar destinos posteriormente, bastam dados públicos/não secretos: nome/ID do servidor Discord e IDs dos canais, login do canal Twitch e conta remetente desejada, canal YouTube e URL da live.

## Limites de voz Discord, presença e captura

**Áudio de canal Discord não implementado nesta versão.** Discord exige suporte DAVE/E2EE para chamadas desde março de 2026, conforme a [documentação oficial](https://discord.com/blog/every-voice-and-video-call-on-discord-is-now-end-to-end-encrypted). Uma futura integração precisa de biblioteca compatível, testes reais e interface de participação/transcrição visível e opcional. Não há entrada automática, gravação de participantes ou reação quando alguém entra. É possível usar Discord normalmente em paralelo; o microfone do Race Chat é independente.

Não existe captura de ecrã ou webcam, nem controle de rato/teclado pela IA. Uma extensão de visão deve ser um provedor opcional somente leitura, acionado explicitamente e separado dos transportes de chat. A IA é instruída a não afirmar que vê a corrida. Telemetria, overlays, hotkeys existentes e transmissão OBS não são modificados.

## Validação e manutenção

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Testes usam APIs simuladas e Qt offscreen: roteamento de respostas, menções Discord desativadas, falhas sem duplicar envios, limites YouTube, paginação/backoff, deduplicação, isolamento de contexto IA, DPAPI real, OAuth state/PKCE via loopback local e UI sem foco. Na configuração assistida posterior, OAuth Google real e identidade do canal YouTube foram validados; bot Discord foi instalado. Não houve envio real, teste de hardware de microfone, cobrança OpenAI ou validação end-to-end do chat dos fornecedores. Presença/voz Discord e renovação automática de OAuth continuam fora da implementação entregue.

## Configuração assistida só pelo navegador

`tools/racechat_setup_browser.py` oferece um formulário temporário para guardar as mesmas credenciais sem abrir a janela desktop. Execute-o explicitamente com o Python do projeto; ele imprime uma URL local de sessão. Escuta somente em `127.0.0.1:18766`, com bind exclusivo, caminho aleatório, verificação de origem/CSRF, sem logs HTTP ou eco de segredos. Expira em 30 minutos ou ao clicar **Encerrar configuração**. Não é um serviço permanente, não modifica firewall e não arranca com o Overlay.

O formulário permite guardar token Discord/API key, cliente Google, destinos e iniciar OAuth Google ou Twitch Device Code. O botão de validação verifica a identidade Twitch/YouTube e bot/servidores Discord somente por leitura. Não inicia transmissões, publica mensagens ou ativa microfone. Guarde um token novo somente nesse formulário local ou na UI do Overlay; nunca no chat com o agente.

Na configuração assistida de 21/09/2026, Twitch OAuth foi concluído para `wesimracers` e o serviço estabeleceu uma subscrição real EventSub de mensagens do canal. A ligação foi encerrada após o handshake; não houve mensagem de teste publicada.
