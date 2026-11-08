/* SPDX-License-Identifier: AGPL-3.0-or-later
 * SPDX-FileCopyrightText: 2026 Jareer Abdullah */
'use strict';
const form = document.querySelector('#download-form');
const input = document.querySelector('#video-url');
const button = document.querySelector('#download-button');
const message = document.querySelector('#form-message');
const list = document.querySelector('#downloads');
const empty = list.firstElementChild.cloneNode(true);
const token = document.querySelector('meta[name="csrf-token"]').content;
let lastSignature = '';
let online = false;
let pollTimer;
function tell(text, error = false) { message.textContent = text; message.classList.toggle('error', error); }
function validLink(value) {
  let url;
  try { url = new URL(value.includes('://') ? value : 'https://' + value); } catch { return false; }
  if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return false;
  if (['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(url.hostname)) {
    return (url.pathname === '/watch' && /^[\w-]{11}$/.test(url.searchParams.get('v') || '')) || /^\/(shorts|live|embed)\/[\w-]{11}\/?$/.test(url.pathname);
  }
  if (['youtu.be','www.youtu.be'].includes(url.hostname)) return /^\/[\w-]{11}\/?$/.test(url.pathname);
  if (['tiktok.com','www.tiktok.com','m.tiktok.com'].includes(url.hostname)) return /^\/@[\w.]{1,40}\/video\/\d{10,25}\/?$/.test(url.pathname) || /^\/t\/[a-z\d]{4,40}\/?$/i.test(url.pathname);
  return ['vm.tiktok.com','vt.tiktok.com'].includes(url.hostname) && /^\/[a-z\d]{4,40}\/?$/i.test(url.pathname);
}
function element(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
function bytes(n) { if (!n) return ''; return n >= 1024 ** 3 ? (n / 1024 ** 3).toFixed(1) + ' GB' : (n / 1024 ** 2).toFixed(1) + ' MB'; }
function render(jobs) {
  document.querySelector('#queue-count').textContent = jobs.length;
  const signature = JSON.stringify(jobs);
  if (signature === lastSignature) return;
  lastSignature = signature;
  if (!jobs.length) { list.replaceChildren(empty.cloneNode(true)); return; }
  const nodes = jobs.map(job => {
    const row = element('article', 'job ' + job.state);
    const badge = element('span','job-badge', job.state === 'done' ? '✓' : job.state === 'error' ? '!' : job.platform === 'YouTube' ? '▶' : '♪');
    badge.setAttribute('aria-hidden', 'true');
    const main = element('div','job-main');
    main.append(element('h3','',job.title));
    const statuses = {queued:'Na fila',checking:'Consultando o vídeo',downloading:'Baixando',processing:'Preparando MP4',done:'Salvo na sua pasta',error:'Não foi possível baixar',cancelled:'Interrompido'};
    const meta = element('div','job-meta');
    [job.platform, job.quality === 'original' ? 'Original' : 'Até ' + job.quality + 'p', statuses[job.state] || 'Aguarde', job.size ? bytes(job.size) : null].filter(Boolean).forEach((text,index) => meta.append(element('span','', (index ? '·  ' : '') + text)));
    main.append(meta);
    if (!['done','error','cancelled'].includes(job.state)) {
      const progress = element('div','progress' + (typeof job.percent === 'number' ? '' : ' indeterminate'));
      progress.setAttribute('role','progressbar'); progress.setAttribute('aria-label','Progresso do download');
      if (typeof job.percent === 'number') progress.setAttribute('aria-valuenow', Math.round(job.percent));
      const fill = element('div','progress-fill'); if (typeof job.percent === 'number') fill.style.width = Math.max(0, Math.min(100,job.percent)) + '%';
      progress.append(fill); main.append(progress);
      const details = [typeof job.percent === 'number' ? Math.floor(job.percent) + '%' : null, job.speed ? bytes(job.speed) + '/s' : null, job.eta ? 'aprox. ' + Math.ceil(job.eta) + 's' : null].filter(Boolean);
      if (details.length) main.append(element('p','job-meta',details.join(' · ')));
    }
    if (job.error) main.append(element('p','job-message',job.error));
    row.append(badge,main);
    if (job.state === 'done') { const link = element('a','job-action','Salvar cópia ↗'); link.href = '/files/' + encodeURIComponent(job.id); link.download = job.filename; row.append(link); }
    return row;
  });
  list.replaceChildren(...nodes);
}
async function refresh() {
  clearTimeout(pollTimer);
  try {
    const response = await fetch('/api/status', {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Conexão indisponível.');
    online = true;
    document.querySelector('.local-badge').classList.remove('offline');
    document.querySelector('#connection-label').textContent = data.preview ? 'Prévia de desenvolvimento' : 'Rodando no seu notebook';
    document.querySelector('#destination').textContent = data.destination;
    render(data.jobs);
    if (!data.jsReady && !data.preview && !message.textContent) tell('O suporte JavaScript do YouTube precisa ser instalado. Execute INICIAR_WINDOWS.cmd novamente.',true);
  } catch {
    online = false;
    document.querySelector('.local-badge').classList.add('offline');
    document.querySelector('#connection-label').textContent = 'Conexão interrompida';
    tell('O baixador está desconectado. Abra INICIAR_WINDOWS.cmd e mantenha a janela aberta. O último progresso pode estar desatualizado.',true);
  } finally { pollTimer = setTimeout(refresh, online ? 1500 : 5000); }
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  const value = input.value.trim();
  if (!validLink(value)) { tell('Cole o link de um vídeo específico do YouTube ou TikTok.',true); input.focus(); return; }
  if (!online) { tell('O baixador está desconectado. Abra INICIAR_WINDOWS.cmd primeiro.',true); return; }
  button.disabled = true;
  tell('Adicionando à fila…');
  try {
    const response = await fetch('/api/downloads',{method:'POST',headers:{'Content-Type':'application/json','X-Milena-Token':token},body:JSON.stringify({url:value,quality:document.querySelector('#quality').value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Não foi possível iniciar.');
    input.value = ''; tell('Adicionado à fila. Você pode colar o próximo link.'); await refresh();
  } catch(error) { tell(error.message,true); }
  finally { button.disabled = false; }
});
document.querySelector('#paste').addEventListener('click',async () => {
  try { input.value = (await navigator.clipboard.readText()).trim(); input.focus(); tell(''); }
  catch { input.focus(); tell('Cole o link no campo com Ctrl+V ou mantenha o dedo pressionado.',false); }
});
input.addEventListener('input',()=> { if(message.classList.contains('error') && online) tell(''); });
const dialog = document.querySelector('#about-dialog');
document.querySelector('#about-button').addEventListener('click',()=>dialog.showModal());
document.querySelector('#close-dialog').addEventListener('click',()=>dialog.close());
refresh();
