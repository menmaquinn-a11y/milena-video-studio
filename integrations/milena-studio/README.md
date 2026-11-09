# Milena Video Studio

Integração experimental de edição assistida em português, usando o motor e a API
MCP do Concat. Não é um novo modelo de IA nem uma versão oficial do Concat.

O editor já oferece as ferramentas de edição; esta camada acrescenta um fluxo
para vídeos legendados e configuração para um cliente de IA controlar o editor.
O cliente conversa com esta integração, que envia os comandos ao Concat instalado.

## O que já faz

- Encaminha as ferramentas do Concat: cortar, ajustar áudio, títulos, efeitos,
  desfazer, ver quadros e acompanhar exportações.
- `studio_prepare_video`: cria um projeto, importa o vídeo e um SRT opcional,
  preserva resolução e taxa de quadros e salva o projeto.
- `studio_import_srt`: valida UTF-8 e todos os tempos antes de adicionar legendas
  com fundo discreto. A importação inteira é uma etapa desfazível.
- `studio_export_video`: salva e inicia um MP4 H.264 na pasta `exports`, sem
  substituir um arquivo existente. Acompanhe o job com `export_wait` ou
  `export_status`: começar a exportar não significa que ela terminou.
- `studio_health`: verifica versão e conexão do editor.

Não traduz, não produz dublagem e não publica no TikTok por conta própria. O
assistente conectado prepara/revisa os textos e decide quais ferramentas chamar.
Os vídeos continuam inteiros, a menos que você peça cortes.

## Requisitos

- Python 3.11 ou posterior.
- Uma versão do Concat que aceite `concat --mcp` e ofereça as ferramentas
  descritas em [docs/MCP.md](../../docs/MCP.md). Versões antigas podem não ter MCP.
- Um cliente de IA com suporte a MCP. Para o Codex local, veja a
  [documentação oficial da OpenAI](https://learn.chatgpt.com/docs/extend/mcp).

Esta camada não chama uma API de IA, não contém chave OpenAI e não exige uma
assinatura própria. O custo e a disponibilidade do cliente/modelo são separados.

## Windows

Com o Concat e o Python instalados, execute no PowerShell, na raiz do repositório:

```powershell
.\integrations\milena-studio\setup-windows.ps1 -RegisterCodex
```

`-RegisterCodex` é opcional e exige o comando `codex` instalado. Sem essa opção,
o script mostra a configuração JSON para um cliente MCP local. Ele não muda a
política do PowerShell, não instala o Concat e não muda as permissões do Windows.

Se o editor estiver em outra pasta:

```powershell
.\integrations\milena-studio\setup-windows.ps1 -ConcatPath 'D:\Apps\Concat\concat.exe'
```

O padrão de trabalho é `Videos\MilenaStudio`, na pasta do usuário. Coloque vídeos
e legendas dentro dela. `projects` e `exports` serão criadas ali. Reinicie o cliente
MCP depois do registro e peça para chamar `studio_health`.

## Instalação manual, macOS ou Linux

```sh
cd integrations/milena-studio
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/milena-studio --concat /usr/bin/concat --workspace /caminho/absoluto/Videos
```

O último comando inicia um servidor **stdio**: o cliente MCP deve iniciá-lo e
conversar pelos seus fluxos de entrada/saída. Não é uma janela de chat interativa.
Cadastre esse executável e seus argumentos no cliente; por exemplo:

```sh
codex mcp add milena-studio -- /caminho/absoluto/.venv/bin/milena-studio \
  --concat /usr/bin/concat --workspace /caminho/absoluto/Videos
```

`--mode auto` segue o comportamento do Concat: usa a janela quando Automation está
ligada; caso contrário, usa o motor sem janela. `--mode window` exige a conexão
com a janela. Os projetos do agente são próprios; a versão atual do Concat não
permite editar ao vivo o mesmo projeto já aberto na janela.

## ChatGPT no navegador

O ChatGPT web não lê a configuração local do Codex. Ele precisa de uma conexão
de ferramenta suportada, acessível e autorizada. Esta versão oferece um endpoint
Streamable HTTP **somente no endereço local**, para um executor ou túnel autenticado:

```sh
milena-studio --concat /usr/bin/concat --workspace /caminho/absoluto/Videos \
  --transport streamable-http --port 8765
```

O endpoint é `http://127.0.0.1:8765/mcp`. Ele não tem autenticação própria e não
deve ser publicado diretamente na internet. Use um transporte autenticado, como
o [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
quando disponível na conta. Instalação e acesso do cliente precisam ser verificados
separadamente. Este repositório, sozinho, não conecta uma conversa nem dá acesso
ao computador. Não incluímos credenciais, links públicos ou túnel já ativado.

O transporte HTTP não retém sessões de clientes: reconexões do túnel não acumulam
sessões ociosas. Os projetos abertos e a fila de edições continuam no processo do
estúdio. Se uma instalação antiga registrar `8 sessions are already open`, atualize
o pacote e reinicie o estúdio; os projetos já salvos permanecem no disco.

## Fluxo de exemplo

1. `studio_health` para verificar a conexão.
2. `studio_prepare_video` com `video`, `name` e `srt` em caminhos absolutos.
3. `timeline_read` e `preview_frame` para revisar antes da exportação.
4. `studio_export_video` com `path` e um `filename` novo terminado em `.mp4`.
5. `export_wait` até o job terminar; conferir o arquivo final.

As legendas precisam estar traduzidas antes da importação. Ao repetir
`studio_import_srt`, novas legendas são adicionadas; para corrigir uma importação,
desfaça-a antes ou edite os títulos existentes.

## Testes

```sh
python -m pip install .
python -m unittest discover -s tests -v
```

Os testes do adaptador usam um editor simulado no protocolo MCP para validar a
conexão e os erros. O teste de fumaça separado requer um Concat real com MCP e
FFmpeg/ffprobe no PATH:

```sh
python tests/smoke_real.py --concat /caminho/concat --workspace /tmp/milena-smoke
```

O adaptador só permite caminhos dentro da pasta configurada, inclusive para
comandos encaminhados e caminhos dentro de comandos em lote. Não expõe terminal,
upload de arquivos, chave de API ou publicação em redes sociais. O cliente pode
enviar ao serviço de IA os textos e as prévias retornados pelas ferramentas;
processamento local do editor não torna o cliente de IA offline.

Código desta integração: AGPL-3.0-or-later, como o projeto de origem. Veja
[LICENSE](../../LICENSE). Marcas e modelos do projeto original mantêm suas regras.

## Validação desta versão

Validado em Linux com Python 3.12, MCP SDK 1.30.0 e Concat oficial 0.2.9:
12 testes automatizados e um fluxo real pelo protocolo stdio, criando um vídeo
de teste, adicionando legendas acentuadas, gerando uma prévia e exportando MP4
com áudio a 320 × 180 e 30000/1001 FPS. O script de instalação do Windows precisa
de uma verificação no computador de destino. Não foi necessário recompilar ou
alterar o motor Rust do editor.
