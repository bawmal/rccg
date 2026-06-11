import os
html = r"""<!DOCTYPE html><!-- RHEMA LITE v2 -->
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Rhema Lite</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0c0c0e;--surface:#131316;--surface2:#1a1a1e;--surface3:#222226;
  --border:#2c2c32;--border2:#3a3a42;
  --primary:#7c6af7;--primary-dim:#4a3f99;--primary-glow:rgba(124,106,247,.15);
  --text:#e4e4ec;--muted:#6b6b78;--muted2:#4a4a55;
  --live:#22c55e;--live-dim:#166534;--red:#ef4444;--amber:#f59e0b;--radius:10px;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:grid;grid-template-rows:54px 1fr 190px;overflow:hidden;font-size:14px}
header{background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;padding:0 16px}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;letter-spacing:-.4px;color:var(--text);margin-right:8px}
.brand svg{color:var(--primary)}
.pill{display:flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--muted);transition:all .3s}
.pill.live{border-color:var(--live-dim);background:rgba(34,197,94,.08);color:var(--live)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--muted);transition:background .3s;flex-shrink:0}
.pill.live .dot{background:var(--live);box-shadow:0 0 6px var(--live);animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.spacer{flex:1}
select{background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:7px;padding:5px 10px;font-size:12px;cursor:pointer;outline:none}
select:focus{border-color:var(--primary)}
button{display:flex;align-items:center;gap:5px;padding:6px 14px;border-radius:7px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
button:hover{background:var(--surface3)}
button.primary{background:var(--primary);border-color:var(--primary);color:#fff}
button.primary:hover{background:#6a59e0}
button.sm{padding:4px 10px;font-size:11px;border-radius:5px}
button:disabled{opacity:.35;cursor:not-allowed;pointer-events:none}
main{display:grid;grid-template-columns:1fr 340px 280px;gap:10px;padding:10px;min-height:0;overflow:hidden}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);display:flex;flex-direction:column;min-height:0;overflow:hidden}
.phdr{padding:10px 14px;border-bottom:1px solid var(--border);font-size:10px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.pbody{flex:1;overflow-y:auto;padding:12px}
.pbody::-webkit-scrollbar{width:4px}
.pbody::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.tline{padding:8px 12px;border-radius:7px;margin-bottom:6px;font-size:13px;line-height:1.6;animation:fu .2s ease;background:var(--surface2);border:1px solid var(--border)}
@keyframes fu{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.ttime{font-size:10px;color:var(--muted);margin-top:2px}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:10px;color:var(--muted2);font-size:12px;text-align:center;opacity:.7}
.empty svg{opacity:.5}
.vcard{background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:14px;margin-bottom:10px;animation:fu .25s ease}
.vcard.auto{border-color:var(--primary-dim);background:var(--primary-glow)}
.vref{font-size:12px;font-weight:700;color:var(--primary);display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:4px}
.vtrans{font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:rgba(124,106,247,.15);color:var(--primary)}
.vtext{font-size:14px;line-height:1.7;color:var(--text);margin:8px 0;font-style:italic}
.vact{display:flex;gap:7px;margin-top:8px}
.badge{display:inline-flex;align-items:center;font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px}
.badge.direct{background:rgba(34,197,94,.12);color:var(--live)}
.badge.semantic{background:rgba(124,106,247,.12);color:var(--primary)}
.badge.manual{background:rgba(245,158,11,.12);color:var(--amber)}
.cbar{height:3px;border-radius:2px;background:var(--border);margin-top:4px}
.cfill{height:100%;border-radius:2px;background:var(--primary)}
.cand{padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .15s}
.cand:last-child{border-bottom:none}
.cand:hover{background:var(--surface3)}
.cref{font-size:12px;font-weight:700;color:var(--primary)}
.ctxt{font-size:12px;color:var(--muted);line-height:1.5;margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cscore{font-size:10px;color:var(--amber);font-weight:600}
.stat{padding:9px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:12px}
.stat:last-child{border-bottom:none}
.slbl{color:var(--muted)}
.sval{font-weight:700;font-variant-numeric:tabular-nums}
.sval.ok{color:var(--live)}
footer{background:var(--surface);border-top:1px solid var(--border);display:grid;grid-template-rows:34px 1fr;padding:0 10px 10px}
.fhdr{display:flex;align-items:center;justify-content:space-between;font-size:10px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;color:var(--muted)}
#ft{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:8px 12px;font-size:12px;line-height:1.7;color:var(--text);overflow-y:auto;font-family:ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
#ft::-webkit-scrollbar{width:4px}
#ft::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
#ov{display:none;position:fixed;inset:0;background:#000;z-index:1000;flex-direction:column;align-items:center;justify-content:center;padding:60px;cursor:pointer}
#ov.on{display:flex}
#ov-ref{font-size:18px;font-weight:700;color:rgba(255,255,255,.4);margin-bottom:18px;letter-spacing:.5px}
#ov-text{font-size:clamp(22px,4vw,50px);line-height:1.55;color:#fff;text-align:center;max-width:900px;font-style:italic}
#ov-trans{margin-top:16px;font-size:13px;color:rgba(255,255,255,.3);font-weight:600;letter-spacing:1px;text-transform:uppercase}
#ov-hint{position:absolute;bottom:20px;font-size:11px;color:rgba(255,255,255,.18)}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:7px 18px;border-radius:8px;font-size:12px;font-weight:600;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none}
</style>
</head>
<body>
<header>
  <div class="brand">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" x2="12" y1="19" y2="22"/>
    </svg>
    Rhema Lite
  </div>
  <div id="pill" class="pill"><span class="dot"></span><span id="ptxt">Connecting...</span></div>
  <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:7px">
    Version <select id="tsel" onchange="setTrans(this.value)"><option>KJV</option></select>
  </label>
  <div class="spacer"></div>
  <button class="sm" onclick="clearAll()">Clear</button>
  <button class="sm" onclick="copyAll()">Copy</button>
  <button id="pbtn" class="sm primary" onclick="openPresent()" disabled>&#x26F6; Present</button>
</header>
<main>
  <div class="panel">
    <div class="phdr">Live Transcript <span id="lc" style="font-weight:500;font-size:10px">0 lines</span></div>
    <div class="pbody" id="tfeed">
      <div class="empty" id="te">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" x2="12" y1="19" y2="22"/>
        </svg>Waiting for speech...
      </div>
    </div>
  </div>
  <div class="panel">
    <div class="phdr">Detected Verses <button class="sm" onclick="clearVerses()">Clear</button></div>
    <div class="pbody" id="vfeed">
      <div class="empty" id="ve">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>
        </svg>Verses appear as you speak
      </div>
    </div>
  </div>
  <div style="display:grid;grid-template-rows:1fr auto;gap:10px;min-height:0">
    <div class="panel">
      <div class="phdr">Candidates <span style="color:var(--amber);font-size:9px">&lt;95% match</span></div>
      <div class="pbody" id="cfeed" style="padding:0">
        <div class="empty" id="ce" style="padding:16px">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>Possible matches here
        </div>
      </div>
    </div>
    <div class="panel" style="flex-shrink:0">
      <div class="phdr">Session</div>
      <div class="pbody" style="padding:0 14px">
        <div class="stat"><span class="slbl">Engine</span><span class="sval">Whisper offline</span></div>
        <div class="stat"><span class="slbl">Version</span><span class="sval" id="sv">KJV</span></div>
        <div class="stat"><span class="slbl">Verses</span><span class="sval" id="svc">0</span></div>
        <div class="stat"><span class="slbl">Words</span><span class="sval" id="swc">0</span></div>
        <div class="stat"><span class="slbl">Duration</span><span class="sval" id="sdur">00:00</span></div>
        <div class="stat"><span class="slbl">Internet</span><span class="sval ok">Not required</span></div>
      </div>
    </div>
  </div>
</main>
<footer>
  <div class="fhdr">Full Transcript <button class="sm" onclick="copyAll()">Copy</button></div>
  <div id="ft">Transcription will appear here...</div>
</footer>
<div id="ov" onclick="closePresent()">
  <div id="ov-ref"></div>
  <div id="ov-text"></div>
  <div id="ov-trans"></div>
  <div id="ov-hint">Click to close &nbsp;&#183;&nbsp; F = fullscreen &nbsp;&#183;&nbsp; Esc = exit</div>
</div>
<div id="toast"></div>
<script>
let ws,lines=[],wc=0,vc=0,st=null,tmr=null,cur=null,at='KJV';
function connect(){
  ws=new WebSocket('ws://localhost:3001');
  ws.onopen=()=>{setS('Live',true);st=Date.now();tmr=setInterval(tick,1000);};
  ws.onmessage=e=>{try{route(JSON.parse(e.data));}catch{}};
  ws.onerror=()=>setS('Error',false);
  ws.onclose=()=>{setS('Reconnecting...',false);clearInterval(tmr);setTimeout(connect,2000);};
}
function route(m){
  if(m.type==='init'){
    at=m.translation;
    const s=document.getElementById('tsel');s.innerHTML='';
    (m.translations||[]).forEach(t=>{const o=document.createElement('option');o.value=t.abbr;o.textContent=t.abbr+' \u2014 '+t.title;if(t.abbr===at)o.selected=true;s.appendChild(o);});
    document.getElementById('sv').textContent=at;
  }else if(m.type==='translation_change'){
    at=m.translation;document.getElementById('tsel').value=at;document.getElementById('sv').textContent=at;toast('Switched to '+at);
  }else if(m.type==='transcript'){
    addLine(m.text);
  }else if(m.type==='verse_detected'){
    addVerse(m);clearCands();
  }else if(m.type==='candidates'){
    showCands(m.candidates);
  }
}
function setS(l,live){document.getElementById('ptxt').textContent=l;document.getElementById('pill').className='pill'+(live?' live':'');}
function setTrans(v){if(ws&&ws.readyState===1)ws.send(JSON.stringify({action:'set_translation',translation:v}));}
function addLine(text){
  document.getElementById('te')?.remove();
  const f=document.getElementById('tfeed');
  const d=document.createElement('div');d.className='tline';
  d.innerHTML='<div>'+esc(text)+'</div><div class="ttime">'+now()+'</div>';
  f.appendChild(d);f.scrollTop=f.scrollHeight;
  lines.push(text);wc+=text.split(/\s+/).filter(Boolean).length;
  document.getElementById('swc').textContent=wc;
  document.getElementById('lc').textContent=lines.length+' lines';
  const ft=document.getElementById('ft');ft.textContent=lines.join('\n');ft.scrollTop=ft.scrollHeight;
}
function addVerse(v){
  document.getElementById('ve')?.remove();
  cur=v;document.getElementById('pbtn').disabled=false;
  const f=document.getElementById('vfeed');
  const conf=Math.round(v.confidence*100);
  const sc=v.source==='direct'?'direct':v.source==='manual'?'manual':'semantic';
  const isAuto=v.confidence>=0.95;
  const d=document.createElement('div');d.className='vcard'+(isAuto?' auto':'');
  d.innerHTML='<div class="vref">'+esc(v.reference)+'<span class="vtrans">'+esc(v.translation)+'</span><span class="badge '+sc+'">'+v.source+'</span></div>'
    +'<div class="cbar"><div class="cfill" style="width:'+conf+'%"></div></div>'
    +'<div class="vtext">'+esc(v.text)+'</div>'
    +'<div class="vact"><button class="sm primary" onclick=\'presentVerse('+JSON.stringify(v)+')\'>&#x26F6; Present</button>'
    +'<button class="sm" onclick="this.closest(\'.vcard\').remove()">Dismiss</button></div>';
  f.insertBefore(d,f.firstChild);
  if(isAuto&&v.source!=='manual')presentVerse(v);
  vc++;document.getElementById('svc').textContent=vc;
}
function showCands(cands){
  const f=document.getElementById('cfeed');f.innerHTML='';
  cands.forEach(c=>{
    const d=document.createElement('div');d.className='cand';
    d.innerHTML='<div style="display:flex;justify-content:space-between"><span class="cref">'+esc(c.reference)+'</span><span class="cscore">'+Math.round(c.score*100)+'%</span></div>'
      +'<div class="ctxt">'+esc(c.text)+'</div>';
    d.onclick=()=>{if(ws&&ws.readyState===1)ws.send(JSON.stringify({action:'select_candidate',book_name:c.book_name,chapter:c.chapter,verse:c.verse}));clearCands();};
    f.appendChild(d);
  });
}
function clearCands(){document.getElementById('cfeed').innerHTML='<div class="empty" id="ce" style="padding:16px"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>Possible matches here</div>';}
function presentVerse(v){
  document.getElementById('ov-ref').textContent=v.reference;
  document.getElementById('ov-text').textContent=v.text;
  document.getElementById('ov-trans').textContent=v.translation;
  document.getElementById('ov').classList.add('on');cur=v;
}
function openPresent(){if(cur)presentVerse(cur);}
function closePresent(){document.getElementById('ov').classList.remove('on');}
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')closePresent();
  if((e.key==='f'||e.key==='F')&&document.getElementById('ov').classList.contains('on'))
    !document.fullscreenElement?document.getElementById('ov').requestFullscreen?.():document.exitFullscreen?.();
});
function clearAll(){
  lines=[];wc=0;
  document.getElementById('tfeed').innerHTML='<div class="empty" id="te"><svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>Waiting for speech...</div>';
  document.getElementById('ft').textContent='Transcription will appear here...';
  document.getElementById('swc').textContent='0';document.getElementById('lc').textContent='0 lines';
}
function clearVerses(){
  vc=0;document.getElementById('vfeed').innerHTML='<div class="empty" id="ve"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>Verses appear as you speak</div>';
  document.getElementById('svc').textContent='0';document.getElementById('pbtn').disabled=true;clearCands();
}
function copyAll(){navigator.clipboard.writeText(lines.join('\n')).then(()=>toast('Copied!'));}
function tick(){const s=Math.floor((Date.now()-st)/1000);document.getElementById('sdur').textContent=String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function now(){return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
let tt;function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.style.opacity='1';clearTimeout(tt);tt=setTimeout(()=>t.style.opacity='0',2000);}
connect();
</script>
</body>
</html>"""

path = os.path.join(os.path.dirname(__file__), 'web-ui', 'index.html')
with open(path, 'w') as f:
    f.write(html)
print("Written:", path)
