/* SPDX-License-Identifier: AGPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Jareer Abdullah */
// Read-only development preview. Production uses the Python loopback server.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const index = process.argv.indexOf('--port');
const port = index >= 0 ? Number(process.argv[index + 1]) : Number(process.env.PORT || 4173);
http.createServer((request, response) => {
  response.setHeader('Cache-Control','no-store');
  const json = (status,data) => { response.writeHead(status,{'Content-Type':'application/json'}); response.end(JSON.stringify(data)); };
  if (request.url === '/api/status' && request.method === 'GET') return json(200,{preview:true,jsReady:true,destination:'Videos / MilenaStudio / downloads',jobs:[]});
  if (request.method !== 'GET') return json(503,{error:'Esta é a prévia de desenvolvimento. Execute INICIAR_WINDOWS.cmd no notebook para baixar vídeos.'});
  const assets = {'/':['index.html','text/html; charset=utf-8'],'/app.js':['app.js','text/javascript; charset=utf-8'],'/style.css':['style.css','text/css; charset=utf-8']};
  const asset = assets[request.url];
  if (!asset) return json(404,{error:'Página não encontrada.'});
  response.writeHead(200,{'Content-Type':asset[1]});
  response.end(fs.readFileSync(path.join(__dirname,'web',asset[0])));
}).listen(port,'0.0.0.0');
