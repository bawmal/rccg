import os, pathlib

UI = pathlib.Path('/Users/bawomaleghemi/CascadeProjects/transcriber/web-ui/index.html')

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Rhema Lite</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#09090b;--surface:#111114;--surface2:#18181c;--surface3:#222228;
  --border:#2a2a32;--primary:#7c6af7;--primary-dim:#3d3580;
  --text:#e8e8f0;--muted:#68687a;--muted2:#3a3a46;
  --live:#22c55e;--live-dim:#14532d;--amber:#f59e0b;--red:#ef4444;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:grid;grid-template-rows:52px 1fr;overflow:hidden}

/* ── Header ── */
header{background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;padding:0 16px;z-index:10}
.brand{display:flex;align-items:center;gap:7px;font-weight:700;font-size:14px;letter-spacing:-.3px;color:var(--text)}
.brand svg{color:var(--primary);flex-shrink:0}
.pill{display:flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--border);background:var(--surface2);color:var(--muted);transition:all .3s;white-space:nowrap}
.pill.live{border-color:var(--live-dim);background:rgba(34,197,94,.08);color:var(--live)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--muted);flex-shrink:0}
.pill.live .dot{background:var(--live);box-shadow:0 0 5px var(--live);animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sp{flex:1}
select{background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer;outline:none;max-width:180px}
select:focus{border-color:var(--primary)}
button{display:flex;align-items:center;gap:4px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:11px;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
button:hover{background:var(--surface3)}
button.primary{background:var(--primary);border-color:var(--primary);color:#fff}
button.primary:hover{background:#6558e0}
button:disabled{opacity:.3;cursor:not-allowed;pointer-events:none}

/* ── Main layout ── */
main{display:grid;grid-template-columns:1fr 320px;min-height:0;overflow:hidden}

/* ── Left: projection area ── */
#proj-area{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px;position:relative;background:var(--bg);min-height:0}
#proj-area.has-verse{background:#000}
.proj-idle{display:flex;flex-direction:column;align-items:center;gap:14px;color:var(--muted2);font-size:13px;text-align:center}
.proj-idle svg{opacity:.2}
#proj-card{display:none;flex-direction:column;align-items:center;text-align:center;max-width:800px;width:100%}
#proj-ref{font-size:16px;font-weight:700;color:rgba(255,255,255,.45);margin-bottom:16px;letter-spacing:.5px;text-transform:uppercase}
#proj-text{font-size:clamp(20px,3.2vw,42px);line-height:1.6;color:#fff;font-style:italic;font-weight:400}
#proj-trans{margin-top:14px;font-size:12px;color:rgba(255,255,255,.28);font-weight:700;letter-spacing:1.5px;text-transform:uppercase}
.proj-actions{position:absolute;bottom:16px;right:16px;display:flex;gap:8px}
#proj-area.has-verse .proj-actions button{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.15);color:rgba(255,255,255,.6)}
#proj-area.has-verse .proj-actions button:hover{background:rgba(255,255,255,.15)}

/* ── Right sidebar ── */
aside{background:var(--surface);border-left:1px solid var(--border);display:flex;flex-direction:column;min-height:0;overflow:hidden}
.aside-section{border-bottom:1px solid var(--border);flex-shrink:0}
.aside-section:last-child{border-bottom:none;flex:1;overflow:hidden;display:flex;flex-direction:column}
.sec-hdr{padding:10px 14px;font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;justify-content:space-between}
.sec-body{padding:10px 14px}
.sec-scroll{flex:1;overflow-y:auto;padding:0}
.sec-scroll::-webkit-scrollbar{width:3px}
.sec-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── Manual lookup ── */
.lookup-row{display:flex;gap:6px;margin-bottom:8px}
.lookup-row input{flex:1;background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px 10px;font-size:12px;outline:none;min-width:0}
.lookup-row input:focus{border-color:var(--primary)}
.lookup-row input::placeholder{color:var(--muted)}
.lookup-hint{font-size:10px;color:var(--muted2);line-height:1.5}

/* ── Detected queue ── */
.det-card{padding:10px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .15s;position:relative}
.det-card:last-child{border-bottom:none}
.det-card:hover{background:var(--surface2)}
.det-card.active{background:rgba(124,106,247,.08);border-left:2px solid var(--primary)}
.det-ref{font-size:12px;font-weight:700;color:var(--primary);display:flex;align-items:center;gap:6px}
.det-txt{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.det-meta{font-size:10px;color:var(--muted2);margin-top:4px;display:flex;gap:8px;align-items:center}
.badge{font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;text-transform:uppercase;letter-spacing:.4px}
.badge.direct{background:rgba(34,197,94,.12);color:var(--live)}
.badge.semantic{background:rgba(124,106,247,.12);color:var(--primary)}
.badge.manual{background:rgba(245,158,11,.12);color:var(--amber)}
.conf{font-size:10px;color:var(--muted);font-weight:600}

/* ── Candidates ── */
.cand-card{padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .15s}
.cand-card:hover{background:var(--surface2)}
.cand-card:last-child{border-bottom:none}
.cand-ref{font-size:11px;font-weight:700;color:var(--primary)}
.cand-txt{font-size:11px;color:var(--muted);margin-top:2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cand-score{font-size:10px;color:var(--amber);font-weight:700;float:right}

/* ── Fullscreen overlay ── */
#fsoverlay{display:none;position:fixed;inset:0;background:#000;z-index:1000;flex-direction:column;align-items:center;justify-content:center;padding:80px;cursor:pointer}
#fsoverlay.on{display:flex}
#fs-ref{font-size:18px;font-weight:700;color:rgba(255,255,255,.35);margin-bottom:22px;letter-spacing:.5px;text-transform:uppercase}
#fs-text{font-size:clamp(26px,4.5vw,58px);line-height:1.55;color:#fff;text-align:center;max-width:1000px;font-style:italic}
#fs-trans{margin-top:18px;font-size:13px;color:rgba(255,255,255,.25);font-weight:700;letter-spacing:2px;text-transform:uppercase}
#fs-hint{position:absolute;bottom:22px;font-size:11px;color:rgba(255,255,255,.15)}
.empty-msg{padding:20px 14px;font-size:12px;color:var(--muted2);text-align:center}
#toast{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);background:#2a2a36;border:1px solid var(--border);color:var(--text);padding:7px 16px;border-radius:8px;font-size:12px;font-weight:600;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none}
</style>
</head>
<body>

<!-- Header -->
<header>
  <div class="brand">
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" x2="12" y1="19" y2="22"/>
    </svg>
    Rhema Lite
  </div>
  <div id="pill" class="pill"><span class="dot"></span><span id="ptxt">Connecting...</span></div>
  <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:6px;white-space:nowrap">
    Version <select id="tsel" onchange="setTrans(this.value)"><option>KJV</option></select>
  </label>
  <div class="sp"></div>
  <button onclick="clearDisplay()">Clear</button>
  <button id="fsbtn" class="primary" onclick="openFS()" disabled>&#x26F6; Fullscreen</button>
</header>

<!-- Main -->
<main>
  <!-- Left: live projection -->
  <div id="proj-area">
    <div class="proj-idle" id="idle-msg">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>
      </svg>
      Listening for Bible verses...<br/>
      <span style="font-size:11px;opacity:.6">Say a verse reference or quote a passage</span>
    </div>
    <div id="proj-card">
      <div id="proj-ref"></div>
      <div id="proj-text"></div>
      <div id="proj-trans"></div>
    </div>
    <div class="proj-actions">
      <button id="prev-btn" onclick="navVerse(-1)" disabled>&#8592; Prev</button>
      <button id="next-btn" onclick="navVerse(1)" disabled>&#8594; Next</button>
      <button class="primary" id="proj-fs-btn" onclick="openFS()" disabled>&#x26F6; Fullscreen</button>
    </div>
  </div>

  <!-- Right: sidebar -->
  <aside>

    <!-- Manual lookup -->
    <div class="aside-section">
      <div class="sec-hdr">Manual Lookup</div>
      <div class="sec-body">
        <div class="lookup-row">
          <input id="ref-input" type="text" placeholder="e.g. John 3:16" onkeydown="if(event.key==='Enter')lookupManual()"/>
          <button class="primary" onclick="lookupManual()">Go</button>
        </div>
        <div class="lookup-hint">Type any reference: <b>John 3:16</b>, <b>Ps 23:1</b>, <b>1 Cor 13:4</b></div>
      </div>
    </div>

    <!-- Candidates (low-confidence matches) -->
    <div class="aside-section" id="cands-section" style="display:none">
      <div class="sec-hdr">
        Possible Matches
        <span style="color:var(--amber);font-size:9px">Select to display</span>
      </div>
      <div id="cands-list"></div>
    </div>

    <!-- Detected verse queue -->
    <div class="aside-section">
      <div class="sec-hdr">
        Detected Verses
        <button style="padding:2px 7px;font-size:10px;border-radius:4px" onclick="clearQueue()">Clear</button>
      </div>
      <div class="sec-scroll" id="det-list">
        <div class="empty-msg" id="det-empty">Detected verses will appear here</div>
      </div>
    </div>

  </aside>
</main>

<!-- Fullscreen overlay -->
<div id="fsoverlay" onclick="closeFS()">
  <div id="fs-ref"></div>
  <div id="fs-text"></div>
  <div id="fs-trans"></div>
  <div id="fs-hint">Click to close &nbsp;&#183;&nbsp; F = fullscreen &nbsp;&#183;&nbsp; Arrow keys = navigate</div>
</div>

<div id="toast"></div>

<script>
'use strict';
let ws, at='KJV', queue=[], qIdx=-1;

/* ── WebSocket ── */
function connect(){
  ws=new WebSocket('ws://localhost:3001');
  ws.onopen=()=>setS('Live',true);
  ws.onmessage=e=>{try{route(JSON.parse(e.data));}catch(ex){console.warn(ex);}};
  ws.onerror=()=>setS('Error',false);
  ws.onclose=()=>{setS('Reconnecting...',false);setTimeout(connect,2000);};
}

function route(m){
  switch(m.type){
    case 'init':
      at=m.translation;
      buildTransSel(m.translations||[]);
      break;
    case 'translation_change':
      at=m.translation;
      document.getElementById('tsel').value=at;
      toast('Version: '+at);
      break;
    case 'transcript': break; /* ignore raw transcript */
    case 'verse_detected':
      addToQueue(m);
      /* Auto-display if high confidence or direct reference */
      if(m.confidence>=0.95||m.source==='direct'||m.source==='manual'){
        displayVerse(m, queue.length-1);
      }
      hideCands();
      break;
    case 'candidates':
      showCands(m.candidates);
      break;
  }
}

function setS(l,live){
  document.getElementById('ptxt').textContent=l;
  document.getElementById('pill').className='pill'+(live?' live':'');
}

function setTrans(v){
  if(ws&&ws.readyState===1) ws.send(JSON.stringify({action:'set_translation',translation:v}));
}

function buildTransSel(list){
  const s=document.getElementById('tsel');s.innerHTML='';
  list.forEach(t=>{
    const o=document.createElement('option');
    o.value=t.abbr;o.textContent=t.abbr+' \u2014 '+t.title;
    if(t.abbr===at)o.selected=true;
    s.appendChild(o);
  });
}

/* ── Display ── */
function displayVerse(v, idx){
  qIdx=idx;
  const proj=document.getElementById('proj-area');
  document.getElementById('idle-msg').style.display='none';
  const card=document.getElementById('proj-card');
  card.style.display='flex';
  document.getElementById('proj-ref').textContent=v.reference;
  document.getElementById('proj-text').textContent=v.text;
  document.getElementById('proj-trans').textContent=v.translation;
  proj.className='has-verse';
  document.getElementById('fsbtn').disabled=false;
  document.getElementById('proj-fs-btn').disabled=false;

  /* Update active state in queue */
  document.querySelectorAll('.det-card').forEach((c,i)=>{
    c.className='det-card'+(i===idx?' active':'');
  });

  /* Update nav buttons */
  document.getElementById('prev-btn').disabled=idx<=0;
  document.getElementById('next-btn').disabled=idx>=queue.length-1;

  /* Mirror to fullscreen if open */
  if(document.getElementById('fsoverlay').classList.contains('on')){
    document.getElementById('fs-ref').textContent=v.reference;
    document.getElementById('fs-text').textContent=v.text;
    document.getElementById('fs-trans').textContent=v.translation;
  }
}

function navVerse(dir){
  const ni=qIdx+dir;
  if(ni>=0&&ni<queue.length) displayVerse(queue[ni],ni);
}

/* ── Queue ── */
function addToQueue(v){
  queue.push(v);
  document.getElementById('det-empty')?.remove();
  const list=document.getElementById('det-list');
  const idx=queue.length-1;
  const conf=Math.round(v.confidence*100);
  const sc=v.source==='direct'?'direct':v.source==='manual'?'manual':'semantic';
  const d=document.createElement('div');
  d.className='det-card';
  d.innerHTML='<div class="det-ref">'+esc(v.reference)
    +'<span class="badge '+sc+'">'+v.source+'</span></div>'
    +'<div class="det-txt">'+esc(v.text)+'</div>'
    +'<div class="det-meta"><span class="conf">'+conf+'% match</span>'
    +'<span style="color:var(--muted2)">'+v.translation+'</span></div>';
  d.onclick=()=>displayVerse(v,idx);
  list.appendChild(d);
  list.scrollTop=list.scrollHeight;
}

function clearQueue(){
  queue=[];qIdx=-1;
  document.getElementById('det-list').innerHTML='<div class="empty-msg" id="det-empty">Detected verses will appear here</div>';
  clearDisplay();
  hideCands();
}

function clearDisplay(){
  document.getElementById('proj-area').className='';
  document.getElementById('idle-msg').style.display='flex';
  document.getElementById('proj-card').style.display='none';
  document.getElementById('fsbtn').disabled=true;
  document.getElementById('proj-fs-btn').disabled=true;
  document.getElementById('prev-btn').disabled=true;
  document.getElementById('next-btn').disabled=true;
  closeFS();
}

/* ── Candidates ── */
function showCands(cands){
  if(!cands||!cands.length)return;
  const sec=document.getElementById('cands-section');
  const list=document.getElementById('cands-list');
  sec.style.display='block';
  list.innerHTML='';
  cands.forEach(c=>{
    const d=document.createElement('div');d.className='cand-card';
    d.innerHTML='<span class="cand-score">'+Math.round(c.score*100)+'%</span>'
      +'<div class="cand-ref">'+esc(c.reference)+'</div>'
      +'<div class="cand-txt">'+esc(c.text)+'</div>';
    d.onclick=()=>{
      if(ws&&ws.readyState===1)
        ws.send(JSON.stringify({action:'select_candidate',book_name:c.book_name,chapter:c.chapter,verse:c.verse}));
      hideCands();
    };
    list.appendChild(d);
  });
}

function hideCands(){
  const sec=document.getElementById('cands-section');
  if(sec)sec.style.display='none';
}

/* ── Manual lookup ── */
function lookupManual(){
  const raw=document.getElementById('ref-input').value.trim();
  if(!raw)return;
  /* Parse "Book Chapter:Verse" */
  const m=raw.match(/^(.+?)\s+(\d+)[:\s](\d+)$/);
  if(!m){toast('Format: John 3:16');return;}
  const book=m[1].trim();
  const ch=parseInt(m[2]);
  const vs=parseInt(m[3]);
  if(ws&&ws.readyState===1){
    ws.send(JSON.stringify({action:'lookup',book_name:book,chapter:ch,verse:vs}));
  }
  document.getElementById('ref-input').value='';
}

/* ── Fullscreen ── */
function openFS(){
  if(qIdx<0)return;
  const v=queue[qIdx];
  document.getElementById('fs-ref').textContent=v.reference;
  document.getElementById('fs-text').textContent=v.text;
  document.getElementById('fs-trans').textContent=v.translation;
  document.getElementById('fsoverlay').classList.add('on');
}
function closeFS(){document.getElementById('fsoverlay').classList.remove('on');}

document.addEventListener('keydown',e=>{
  const ov=document.getElementById('fsoverlay').classList.contains('on');
  if(e.key==='Escape')closeFS();
  if(e.key==='f'||e.key==='F'){
    if(ov) !document.fullscreenElement
      ?document.getElementById('fsoverlay').requestFullscreen?.()
      :document.exitFullscreen?.();
  }
  if(ov&&e.key==='ArrowRight'){navVerse(1);}
  if(ov&&e.key==='ArrowLeft'){navVerse(-1);}
});

/* ── Helpers ── */
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
let tt;
function toast(msg){
  const t=document.getElementById('toast');t.textContent=msg;t.style.opacity='1';
  clearTimeout(tt);tt=setTimeout(()=>t.style.opacity='0',2200);
}

connect();
</script>
</body>
</html>
"""

UI.write_text(HTML)
print("Written", len(HTML), "chars to", UI)
