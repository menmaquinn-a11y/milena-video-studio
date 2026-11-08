# Milena · Baixar vídeos

Um site **local** para baixar um vídeo público do YouTube ou TikTok por vez.
Abre no navegador do notebook e salva MP4 em `Videos\MilenaStudio\downloads`.
Tem fila de até quatro pedidos, escolha de qualidade máxima (720p, 1080p ou
original), progresso e botão para salvar uma cópia pelo navegador.

## Windows

1. Extraia o pacote ZIP em uma pasta sua.
2. Abra `INICIAR_WINDOWS.cmd` com dois cliques. Requer Python 3.11 ou posterior.
3. Na primeira execução, o programa instala os componentes pelo PyPI e prepara
   o Deno oficial, se não houver Deno 2.3+ ou Node.js 22+ disponível. O Deno é
   baixado de uma versão fixa do GitHub oficial e verificado por SHA-256.
4. O site abre em `http://127.0.0.1:8767`. Mantenha a janela aberta.

O instalador não pede administrador nem muda as políticas do PowerShell. Os
componentes ficam em `.venv` e `.runtime` dentro da própria pasta. Não depende
do Concat, do túnel ou de uma chave OpenAI para baixar. O Concat pode editar os
arquivos salvos quando a integração estiver conectada.

`ATUALIZAR_EXTRATOR.cmd` atualiza yt-dlp e os scripts EJS pelo PyPI. Use quando as
plataformas mudarem. Isso altera as versões instaladas localmente; o arquivo
requirements.txt registra as versões da instalação inicial.

## Privacidade e limites

- Servidor limitado a `127.0.0.1`. Não publica o computador na internet.
- Sem rastreadores, anúncios, fontes externas, cookies de redes sociais ou upload
  automático. Os próprios YouTube/TikTok e CDNs recebem as requisições necessárias
  aos downloads; eles podem registrar IP e outras informações de rede.
- Não acessa contas, cookies ou senhas do navegador, nem aceita configuração
  arbitrária do yt-dlp. Não contorna login, DRM ou verificação antibot.
- Só aceita URLs de vídeos específicos dos domínios permitidos. Perfis, playlists,
  lives e links de outros sites são recusados.
- Downloads até duas horas, 2 GB por arquivo e 30 minutos de processamento. A
  qualidade escolhida é um teto, sujeito aos formatos oferecidos pela plataforma.
- Histórico somente na memória do programa, sem os links originais. Fechar a
  janela encerra o site; os MP4 concluídos permanecem na pasta.
- Restrições de plataforma, região e mudanças de extrator podem impedir downloads.
  Sucesso em testes locais não garante que todo vídeo público será acessível.
- Qualquer pessoa com acesso à sua conta do Windows ou à pasta poderá acessar os
  vídeos. Não compartilhe a pasta pelo Windows/OneDrive se quiser mantê-la privada.
- Baixe apenas conteúdos que você tem permissão para salvar.

## Desenvolvimento e verificação

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python bootstrap.py
.venv/bin/python app.py --no-browser
python -m unittest discover -s tests -v
```

No Linux/macOS, instale Deno 2.3+ ou Node.js 22+ pelo projeto oficial. A preparação
automática do Deno incluída no pacote é para Windows x86_64. Para outro destino,
use `python app.py --destination /caminho/absoluto/da/pasta`.

O servidor de prévia `preview.cjs` é exclusivo de desenvolvimento, não faz
downloads e exibe essa condição na página. O programa Python entregue para uso
sempre usa loopback e valida Host, cookie de sessão e Origin/token nos pedidos.

## Validação

Oito testes locais cobrem links, limites de qualidade em vídeos horizontais e
verticais, fila, preservação de arquivos existentes, proteção do servidor e
entrega de um arquivo de teste. A interface foi revisada no navegador. Tentativas
com vídeos reais de teste do YouTube e TikTok não concluíram neste ambiente;
o suporte real depende também do acesso às plataformas no notebook de destino.

Baseado em yt-dlp, yt-dlp-ejs e imageio-ffmpeg. Licenças de cada dependência e
dos binários permanecem com seus projetos. Código desta integração: AGPL-3.0-or-later;
veja o LICENSE do repositório de origem.
