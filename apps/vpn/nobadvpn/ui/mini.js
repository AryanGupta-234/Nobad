/* NOBAD VPN mini.html: moved out of the page so the CSP needs no 'unsafe-inline' (#7). */
"use strict";
const $=s=>document.querySelector(s);
let S=null;
const T=s=>s;
async function api(p,b){try{const r=await fetch("/api/"+p,{method:b===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:b===undefined?undefined:JSON.stringify(b)});return await r.json()}catch(e){return{ok:false}}}
const rate=b=>b>=1e6?(b/1e6).toFixed(1)+" Mbps":b>=1e3?Math.round(b/1e3)+" kbps":Math.round(b)+" bps";
function draw(){
  if(!S)return;
  const th=S.settings&&S.settings.theme;if(th==="light"||th==="dark")document.documentElement.dataset.theme=th;
  const on=S.connected,wait=!!S.connecting,block=!on&&!wait&&S.ks_active;
  document.body.dataset.st=on?"on":wait?"wait":block?"block":"off";
  $("#stt").textContent=T(on?"Protected":wait?"Connecting…":block?"Blocked by kill switch":"Not connected");
  $("#sub").textContent=on?S.active:wait?S.connecting:(S.note||"");
  const sel=$("#srv"),cur=(on&&S.active)||(wait&&S.connecting)||sel.value||S.settings.last_region||"";
  const names=S.regions.map(r=>r.name);
  if(sel.dataset.sig!==names.join("|")){sel.dataset.sig=names.join("|");sel.innerHTML=names.map(n=>`<option></option>`).join("");[...sel.options].forEach((o,i)=>{o.value=o.textContent=names[i]})}
  sel.value=names.includes(cur)?cur:(names[0]||"");
  $("#go").textContent=T(on?"Disconnect":wait?"Connecting…":"Connect");$("#go").disabled=wait||(!on&&!names.length);
  $("#fast").disabled=wait||!names.length;$("#ks").checked=!!S.settings.kill_switch;sel.disabled=on||wait;
}
$("#go").onclick=()=>{if(!S)return;S.connected?api("disconnect",{}):api("connect",{name:$("#srv").value})};
$("#fast").onclick=()=>api("fastest",{});$("#open").onclick=()=>{api("window",{do:"show"});api("window",{do:"hide_mini"})};
$("#ks").onchange=e=>api("settings",{key:"kill_switch",value:e.target.checked});
addEventListener("blur",()=>setTimeout(()=>{if(!document.hasFocus())api("window",{do:"hide_mini"})},200));
addEventListener("keydown",e=>{if(e.key==="Escape")api("window",{do:"hide_mini"})});
function sse(){const es=new EventSource("/events");es.onmessage=e=>{try{const m=JSON.parse(e.data);
 if(m.type==="state"){S=m.payload;draw()}else if(m.type==="traffic"){$("#rx").textContent="↓ "+rate(m.payload.rx_bps);$("#tx").textContent="↑ "+rate(m.payload.tx_bps)}}catch(_){}};
 es.onopen=()=>api("state").then(s=>{if(s&&s.regions){S=s;draw()}});es.onerror=()=>{$("#sub").textContent=T("app offline")}}
sse();
