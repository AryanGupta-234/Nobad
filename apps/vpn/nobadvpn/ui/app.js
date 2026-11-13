/* NOBAD VPN index.html: moved out of the page so the CSP needs no 'unsafe-inline' (#7). */
"use strict";
const FONTS=`"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,sans-serif`;
const ICO={moon:`<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`,
sun:`<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
search:`<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>`};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
async function api(p,b){try{const r=await fetch("/api/"+p,{method:b===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:b===undefined?undefined:JSON.stringify(b)});return await r.json()}catch(e){return{ok:false,error:String(e)}}}
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const S={hist:{},det:null,connected:false,connecting:null,active:null,since:null,ks:false,settings:{},regions:[],selected:null,exit:null,health:null,rtt:[],rx:[],tx:[],rate:0,ripples:[],pos:{},hover:null,mouse:{x:0,y:0},speed:0,speedTarget:0,speedMax:100,pendingMain:""};
const fmtRate=b=>b>=1e6?(b/1e6).toFixed(1)+" Mbps":b>=1e3?Math.round(b/1e3)+" kbps":Math.round(b)+" bps";
const pc=p=>!p||p.rtt==null?"#7b7e87":p.rtt<80?"#3bd69b":p.rtt<180?"#ff9a7c":"#ff5268";
function toast(m,ok){const t=$("#toast");t.className=ok?"ok":"";t.textContent=m;t.style.display="block";clearTimeout(toast.h);toast.h=setTimeout(()=>t.style.display="none",4500)}
/* ---------- state -> DOM ---------- */
function applyState(st){
 if(S.connected&&!st.connected&&S.det&&S.since){const sec=Math.floor(Date.now()/1000-S.since);toast("Session ended · "+Math.floor(sec/60)+"m "+sec%60+"s · ↓ "+fmtB(S.det.rx_total)+" ↑ "+fmtB(S.det.tx_total),true)}
 if(!S.connected&&st.connected&&st.active&&S.pos[st.active]){const q=S.pos[st.active];for(let k=0;k<3;k++)S.ripples.push({x:q.x,y:q.y,t0:performance.now()+k*240,c:"#3dffb0"});S.ripples.push({x:q.x,y:q.y,t0:performance.now(),c:"#3dffb0",big:1});wake(1700)}
 S.connected=st.connected;S.connecting=st.connecting;S.pendingMain="";S.active=st.active;S.since=st.since;S.ks=st.ks_active;S.settings=st.settings;applyTheme(S.settings.theme||getSavedTheme());splash(st);S.home=st.home;S.sessions=st.sessions||[];S.regions=st.regions;S.exit=st.exit;S.health=st.health;
 if(!S.selected||!S.regions.find(r=>r.name===S.selected))S.selected=st.settings.last_region&&S.regions.find(r=>r.name===st.settings.last_region)?st.settings.last_region:(S.regions[0]||{}).name||null;
 $("#adm").style.display=st.admin?"none":"inline";
 if(st.log&&!S.logged){S.logged=true;st.log.forEach(addLog)}
 if(!S.connected){S.rx.length=0;S.tx.length=0;S.rtt.length=0;S.det=null}
 render();if(window.NX)NX.onState(st);
}
function render(){
 document.body.dataset.st=S.connected?"on":S.connecting?"wait":"off";const pill=$("#pill");pill.className="pill"+(S.connected?" on":S.connecting?" wait":"");
 $("#pillt").textContent=S.connected?"protected"+(S.ks?" · kill switch":""):S.connecting?"connecting…":"not connected";
 $("#st").textContent=S.connected?"Protected":S.connecting?"Connecting…":"Not connected";
 $("#ss").textContent=S.connected?S.active:S.connecting?S.connecting:(S.selected?"Selected: "+S.selected:"No servers — import a .conf");
 const b=$("#bMain");b.disabled=!!S.connecting||!!S.pendingMain;b.className="pri shiny-cta"+(S.connected?" off":"")+((S.connecting||S.pendingMain)?" is-busy":"");
 setMainLabel(S.pendingMain|| (S.connected?"Disconnect":S.connecting?"Connecting…":"Connect"));
 $("#bFast").disabled=!!S.connecting||!!S.pendingMain||!S.regions.length;qbadge();hud();renderDeck();renderDet();extras();
 const e=S.exit;$("#ipV").textContent=e&&e.ip?e.ip:e&&e.error?"unavailable":"—";$("#ipL").textContent=(e&&!e.error?[[e.city,e.country].filter(Boolean).join(", "),(e.org||"").replace(/^AS\d+\s*/,"")].filter(Boolean).join(" · "):e&&e.error?"Lookup failed ("+e.error+") — press Refresh":"")||"Exit address";
 const h=S.health;$("#mRtt").textContent=h&&h.rtt!=null?h.rtt+" ms":"—";$("#mJit").textContent=h&&h.jitter!=null?h.jitter+" ms":"—";$("#mLoss").textContent=h?h.loss+"%":"—";
 const needle=($("#serverSearch")?.value||"").trim().toLowerCase(),onlyFav=!!$("#onlyFav")?.checked,sortMode=$("#serverSort")?.value||"best";
 let visible=srvList().filter(r=>(!needle||(r.name+" "+(r.host||"")).toLowerCase().includes(needle))&&(!onlyFav||(S.settings.favorites||[]).includes(r.name)));
 if(sortMode==="name")visible.sort((a,b)=>a.name.localeCompare(b.name));
 if(sortMode==="recent")visible.sort((a,b)=>(S.settings.favorites||[]).includes(b.name)-(S.settings.favorites||[]).includes(a.name));
 $("#serverCount").textContent=`${visible.length} of ${S.regions.length} locations · ${S.regions.length-(S.settings.favorites||[]).length} not favorited`;
 $("#srv").innerHTML=S.regions.length?visible.map(r=>{const p=r.ping,w=p&&p.rtt!=null?Math.max(6,100-p.rtt/3):0;
  return `<div class="row${S.active===r.name&&S.connected?" act":""}"><div class="nm"><div title="${esc(r.name)}">${esc(r.name)}${S.active===r.name&&S.connected?" ●":""}</div><div>${r.geo&&r.geo.city?esc(r.geo.city+(r.geo.country?", "+r.geo.country:""))+" · ":""}${esc(r.host||"no endpoint")}${r.port?":"+r.port:""}</div></div>${spark(r,w,p)}<div class="ms">${p&&p.rtt!=null?(p.est?"~":"")+p.rtt+" ms":"—"}</div><button class="star${(S.settings.favorites||[]).includes(r.name)?" y":""}" data-f="${esc(r.name)}" title="Favourite" aria-label="Favourite"><svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9-4.3-4.1 5.9-.8z"/></svg></button><button class="sm ic" data-edit="${esc(r.name)}" title="Edit config" aria-label="Edit ${esc(r.name)} config"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M14 6l4 4"/></svg></button><button class="sm" data-c="${esc(r.name)}" aria-label="Connect to ${esc(r.name)}">Go</button></div>` }).join(""):(S.regions.length?'<div class="empty-state">No locations match these filters. Try another search or clear Favorites.</div>':'<div class="note">No servers yet. Drop WireGuard .conf files into the configs folder or press Import.</div>');
 if(window.NX)NX.renderSettings();
  draw2();invalidate();
}
let ACC="#f65000";
function getSavedTheme(){try{return localStorage.getItem("nobad-theme")==="light"?"light":"dark"}catch(_){return "dark"}}
function applyTheme(theme){const mode=theme==="light"?"light":"dark";document.documentElement.dataset.theme=mode;try{localStorage.setItem("nobad-theme",mode)}catch(_){};const toggle=$("#bTheme"),panel=$("#themeSwitch");if(toggle)toggle.innerHTML=(mode==="dark"?ICO.moon+"<span>Dark</span>":ICO.sun+"<span>Light</span>");if(panel)panel.querySelectorAll("[data-theme-choice]").forEach(b=>b.classList.toggle("active",b.dataset.themeChoice===mode));ACC="#f65000"}
function chooseTheme(mode){applyTheme(mode);api("theme",{value:mode}).then(r=>{if(!r.ok)toast(r.error||"Could not save appearance")})}
function extras(){$$("#hChips [data-k]").forEach(b=>b.classList.toggle("on",!!S.settings[b.dataset.k]));}
function renderDeck(){const title=$("#deckTitle"),sub=$("#deckSub");if(!title)return;
 const h=S.health,lat=h&&h.rtt!=null?h.rtt+" ms":"—";
 title.textContent=S.pendingMain|| (S.connected?"Tunnel protected":S.connecting?"Connecting securely":"Ready to connect");
 sub.textContent=S.connected?(S.active||"Connected")+(S.ks?" · Kill switch armed":" · Encrypted tunnel active"):S.connecting?String(S.connecting):S.selected?"Selected location · "+S.selected:"Select a location or let NOBAD find one";
 
}
function spark(r,w,p){const h=S.hist[r.name]||[],v=h.filter(x=>x!=null);
 if(v.length<2)return `<div class="bar"><i style="width:${w}%;background:${pc(p)}"></i></div>`;
 const mx=Math.max(...v,50),pts=h.map((x,i)=>x==null?null:(i*54/Math.max(h.length-1,1)).toFixed(1)+","+(15-x/mx*13).toFixed(1)).filter(Boolean).join(" ");
 return `<svg class="spk" viewBox="0 0 54 16"><polyline points="${pts}" fill="none" stroke="${pc(p)}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`}
const SPL={t0:performance.now(),done:false};
function splash(st){const el=$("#splash");if(!el)return;
 const L=(id,ok,t)=>{const e=$("#sp_"+id);e.className=ok?"ok":"bad";e.querySelector("em").textContent=t};
 L("eng",true,"ready");L("adm",st.admin,st.admin?"granted":"not elevated");L("wg",st.wireguard,st.wireguard?"found":"not installed");
 L("srv",st.regions.length>0,st.regions.length+" loaded");L("tun",true,st.connected?"attached · "+st.active:"idle");$("#spbar").style.width="100%";
 if(!SPL.done){SPL.done=true;setTimeout(()=>{el.classList.add("hide");setTimeout(()=>el.remove(),700)},Math.max(400,1800-(performance.now()-SPL.t0)))}}
setTimeout(()=>{const e=$("#splash");if(e){e.classList.add("hide");setTimeout(()=>e.remove(),700)}},7000);
const PAL={open:false,sel:0,list:[]};
function tabTo(t){const b=$$("#dock [data-tab]").find(x=>x.dataset.tab===t);if(b)b.click()}
function palItems(){const a=[["Connect / disconnect",mainAction],["Connect to fastest server",()=>api("fastest",{})],["Run speed test",()=>{tabTo("t1");setSpeed(0);api("speedtest",{})}],["Check streaming services",()=>{tabTo("t1");api("streamcheck",{})}],["Probe all servers",()=>{tabTo("t2");api("probe",{})}],["Toggle kill switch",()=>api("settings",{key:"kill_switch",value:!S.settings.kill_switch})],["Open configs folder",()=>api("open_configs",{})]];
 [["Servers","t2"],["Streaming","t1"],["Details","t4"],["Settings","t3"]].forEach(([n,t])=>a.push(["Go to "+n,()=>tabTo(t)]));
 S.regions.forEach(r=>a.push(["Connect → "+r.name,()=>api("connect",{name:r.name})]));return a}
function palDraw(){const q=$("#palin").value.toLowerCase();PAL.list=palItems().filter(x=>x[0].toLowerCase().includes(q));PAL.sel=Math.min(PAL.sel,Math.max(0,PAL.list.length-1));
 $("#pall").innerHTML=PAL.list.map((x,i)=>`<div class="${i===PAL.sel?"s":""}" data-i="${i}" id="palo${i}" role="option" aria-selected="${i===PAL.sel}">${esc(x[0])}</div>`).join("")||'<div role="option" aria-disabled="true">No match</div>';
 const inp=$("#palin");if(PAL.list.length)inp.setAttribute("aria-activedescendant","palo"+PAL.sel);else inp.removeAttribute("aria-activedescendant");
 const cur=$("#palo"+PAL.sel);if(cur&&cur.scrollIntoView)cur.scrollIntoView({block:"nearest"})}
function palToggle(){PAL.open=!PAL.open;$("#pal").classList.toggle("o",PAL.open);if(PAL.open){PAL.prev=document.activeElement;$("#palin").value="";PAL.sel=0;palDraw();$("#palin").focus()}else if(PAL.prev&&PAL.prev.focus&&PAL.prev.isConnected){try{PAL.prev.focus()}catch(_){}}}
function palRun(i){const x=PAL.list[i];if(!x)return;palToggle();x[1]()}
$("#palin").oninput=()=>{PAL.sel=0;palDraw()};
$("#palin").onkeydown=e=>{if(e.key==="Tab"){e.preventDefault();return}if(e.key==="Escape"){e.stopPropagation();palToggle()}else if(e.key==="ArrowDown"){PAL.sel=Math.min(PAL.sel+1,PAL.list.length-1);palDraw();e.preventDefault()}else if(e.key==="ArrowUp"){PAL.sel=Math.max(PAL.sel-1,0);palDraw();e.preventDefault()}else if(e.key==="Enter")palRun(PAL.sel)};
$("#pall").onclick=e=>{const d=e.target.closest("[data-i]");if(d)palRun(+d.dataset.i)};
$("#pal").onclick=e=>{if(e.target.id==="pal")palToggle()};
$("#bPal").onclick=palToggle;
$("#bTheme").onclick=()=>chooseTheme(document.documentElement.dataset.theme==="dark"?"light":"dark");
$("#themeSwitch").onclick=e=>{const b=e.target.closest("[data-theme-choice]");if(b)chooseTheme(b.dataset.themeChoice)};
$("#hChips").onclick=e=>{const b=e.target.closest("[data-k]");if(b)api("settings",{key:b.dataset.k,value:!S.settings[b.dataset.k]})};
setInterval(()=>{if($("#t2").classList.contains("a")&&!S.connecting&&!document.hidden)api("probe",{})},30000);
function tick(){const u=$("#mUp");if(S.connected&&S.since){let s=Math.floor(Date.now()/1000-S.since);const p=n=>String(n).padStart(2,"0");u.textContent=`${p(Math.floor(s/3600))}:${p(Math.floor(s%3600/60))}:${p(s%60)}`}else u.textContent="—"}
setInterval(tick,1000);
const fmtB=n=>n>=1e9?(n/1e9).toFixed(2)+" GB":n>=1e6?(n/1e6).toFixed(1)+" MB":n>=1e3?Math.round(n/1e3)+" KB":(n||0)+" B";
function srvList(){const f=S.settings.favorites||[],pr=r=>r.ping&&r.ping.rtt!=null?r.ping.rtt:1e9;return S.regions.slice().sort((a,b)=>(f.includes(b.name)-f.includes(a.name))||(pr(a)-pr(b)))}
function hud(){const e=S.exit&&!S.exit.error?S.exit:null,h=$("#hS");
 h.textContent=S.connected?"Protected":S.connecting?"Connecting…":"Not connected";h.className=S.connected?"on":S.connecting?"wait":"";
 $("#hSub").textContent=S.connected?S.active+(e&&e.city?" · "+[e.city,e.country].filter(Boolean).join(", "):""):S.connecting?S.connecting:(S.selected?"Selected: "+S.selected:"Import a .conf to begin");
 if(!S.connected){$("#hRx").textContent="↓ —";$("#hTx").textContent="↑ —"}}
function qbadge(){const q=$("#qb"),h=S.health;if(!S.connected||!h||!h.q){q.style.display="none";return}q.style.display="inline-block";q.textContent=h.q;q.className="qb q-"+h.q}
function kv(rows){return rows.map(([k,v])=>`<div class="kvr"><span>${esc(k)}</span><b>${esc(v==null||v===""?"—":v)}</b></div>`).join("")}
const dur=n=>n>=3600?Math.floor(n/3600)+"h "+Math.floor(n%3600/60)+"m":n>=60?Math.floor(n/60)+"m "+n%60+"s":n+"s";
function when(ts){const d=new Date(ts*1000),t=d.toDateString()===new Date().toDateString();return(t?"Today ":d.toLocaleDateString(undefined,{month:"short",day:"numeric"})+" ")+d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}
function protHTML(){
 if(!S.connected)return '<div class="note">Connect to a server to run the protection check.</div>';
 const r=S.regions.find(x=>x.name===S.active),d=S.det,e=S.exit&&!S.exit.error?S.exit:null,h=S.home;
 const rows=[["Tunnel active",true,S.active],["Fresh handshake",d&&d.hs_age!=null?d.hs_age<180:null,d&&d.hs_age!=null?d.hs_age+" s ago":"waiting"],
  ["All traffic routed",r?!!r.full:null,r?(r.full?"0.0.0.0/0":"split tunnel"):""],["IPv6 covered",r?!!r.v6:null,r?(r.v6?"::/0 routed":"IPv6 may leak"):""],
  ["DNS inside tunnel",r?(!!r.dns||!!S.dnsActive):null,r?(r.dns?"tunnel DNS":"system DNS"):""],["Exit differs from real IP",e&&h&&h.ip?e.ip!==h.ip:null,e&&h&&h.ip?(e.ip!==h.ip?"changed":"same IP"):"unknown"],
  ["Kill switch armed",!!S.ks,S.ks?"armed":"off"]];
 const known=rows.filter(x=>x[1]!==null),ok=known.filter(x=>x[1]).length,n=known.length,f=n?ok/n:0,C=2*Math.PI*30;
 const col=f>=.99?"#3dffb0":f>=.7?"#ff9a7c":"#ff5a6e",lab=f>=.99?"Fully protected":f>=.7?"Mostly protected":"Needs attention";
 return `<div class="score"><svg viewBox="0 0 74 74"><circle cx="37" cy="37" r="30" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="7"/><circle cx="37" cy="37" r="30" fill="none" stroke="${col}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${(C*f).toFixed(1)} ${C.toFixed(1)}"/></svg><div><div class="t1" style="color:${col}">${ok}/${n} checks</div><div class="t2">${lab}</div></div></div>`+
  rows.map(([k,v,t])=>`<div class="pr ${v===null?"na":v?"":"bad"}"><i>${v===null?"–":v?"✓":"!"}</i><span>${esc(k)}</span><b>${esc(t)}</b></div>`).join("")}
function sessHTML(){const a=(S.sessions||[]).slice().reverse();if(!a.length)return '<div class="note">No sessions yet. They appear here after you disconnect.</div>';
 return a.map(x=>`<div class="ses"><div class="a1"><div>${esc(x.name)}</div><div>${esc(when(x.start))}</div></div><div class="a2"><b>${dur(x.secs)}</b>↓ ${fmtB(x.rx)} · ↑ ${fmtB(x.tx)}</div></div>`).join("")}
function renderDet(){if(!$("#t4").classList.contains("a"))return;
 const r=S.regions.find(x=>x.name===S.active),d=S.det,e=S.exit&&!S.exit.error?S.exit:null,st=S.settings;
 $("#det").innerHTML=kv([["Status",S.connected?"Protected":S.connecting?"Connecting…":"Not connected"],["Server",S.active],["Endpoint",(d&&d.endpoint)||(r?r.host+":"+r.port:null)],["Last handshake",d&&d.hs_age!=null?d.hs_age+" s ago":null],["Downloaded",d?fmtB(d.rx_total):null],["Uploaded",d?fmtB(d.tx_total):null],["Uptime",$("#mUp").textContent]]);
 $("#det2").innerHTML=kv([["Exit IP",e&&e.ip],["Location",e&&[e.city,e.region,e.country].filter(Boolean).join(", ")],["Provider",e&&e.org],["Kill switch",S.ks?"Armed":st.kill_switch?"On (arms when connected)":"Off"],["Auto-repair",st.auto_repair?"On":"Off"],["Streaming tune",st.stream_tuned?"MTU 1380 · keepalive 25":"Off"]]);$("#prot").innerHTML=protHTML();$("#sess").innerHTML=sessHTML()}
setInterval(renderDet,1000);
/* ---------- charts ---------- */
function series(cv,list,fmt){const dpr=Math.min(devicePixelRatio||1,3),w=cv.clientWidth,h=cv.clientHeight;if(!w)return;cv.width=w*dpr;cv.height=h*dpr;const c=cv.getContext("2d");c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,w,h);
 if(!list.some(s=>s.d.length)){c.fillStyle="#6b778c";c.font="11px "+FONTS;c.textAlign="center";c.fillText("Waiting for live data…",w/2,h/2+4);return}
 let mx=0;list.forEach(s=>s.d.forEach(v=>{if(v!=null&&v>mx)mx=v}));mx=Math.max(mx*1.25,list[0].min||1);
 c.strokeStyle="rgba(255,255,255,.06)";c.lineWidth=1;for(let i=1;i<3;i++){c.beginPath();c.moveTo(0,h*i/3);c.lineTo(w,h*i/3);c.stroke()}
 list.forEach((s,si)=>{const n=60,st=w/(n-1);c.beginPath();let started=false;s.d.forEach((v,i)=>{if(v==null){started=false;return}const x=w-(s.d.length-1-i)*st,y=h-4-(v/mx)*(h-10);if(!started){c.moveTo(x,y);started=true}else c.lineTo(x,y)});c.strokeStyle=s.c;c.lineWidth=1.6;c.stroke();
  if(si===0&&s.d.length>1){c.lineTo(w,h);c.lineTo(w-(s.d.length-1)*st,h);c.closePath();const g=c.createLinearGradient(0,0,0,h);g.addColorStop(0,s.c+"55");g.addColorStop(1,s.c+"00");c.fillStyle=g;c.fill()}});
 c.fillStyle="#7d8aa0";c.font="10px "+FONTS;c.textAlign="left";c.fillText(fmt(mx),4,11)}
function draw2(){series($("#cLat"),[{d:S.rtt,c:"#f65000",min:100}],v=>Math.round(v)+" ms latency");series($("#cTp"),[{d:S.rx,c:"#f65000",min:1e5},{d:S.tx,c:"#a9aab2"}],v=>fmtRate(v)+" · throughput") }
function gauge(){const cv=$("#gauge"),c=cv.getContext("2d"),w=cv.width,h=cv.height,cx=w/2,cy=h-30,R=w/2-52;c.clearRect(0,0,w,h);c.lineCap="round";
 for(let i=0;i<=20;i++){const a=Math.PI+Math.PI*i/20,l=i%5?6:12;c.lineWidth=2;c.strokeStyle="rgba(255,255,255,"+(i%5?.12:.26)+")";c.beginPath();c.moveTo(cx+Math.cos(a)*(R+16),cy+Math.sin(a)*(R+16));c.lineTo(cx+Math.cos(a)*(R+16+l),cy+Math.sin(a)*(R+16+l));c.stroke()}
 c.lineWidth=18;c.strokeStyle="rgba(255,255,255,.08)";c.beginPath();c.arc(cx,cy,R,Math.PI,2*Math.PI);c.stroke();
 const f=Math.min(1,S.speed/S.speedMax);
 if(f>0){const g=c.createLinearGradient(cx-R,0,cx+R,0);g.addColorStop(0,"#a93700");g.addColorStop(1,"#ff6418");c.save();c.shadowColor="#f65000";c.shadowBlur=18;c.strokeStyle=g;c.beginPath();c.arc(cx,cy,R,Math.PI,Math.PI+Math.PI*f);c.stroke();c.restore();
  const a=Math.PI+Math.PI*f;c.save();c.shadowColor="#fff";c.shadowBlur=14;c.fillStyle="#fff";c.beginPath();c.arc(cx+Math.cos(a)*R,cy+Math.sin(a)*R,6,0,6.3);c.fill();c.restore()}
 c.fillStyle="#7d8aa0";c.font="18px "+FONTS;c.textAlign="center";c.fillText("0",cx-R,cy+26);c.fillText(S.speedMax,cx+R,cy+26)}
function setSpeed(v,final){S.speedTarget=v;gaugeWake();S.speedMax=[25,50,100,250,500,1000,2500].find(m=>m>=v*1.15)||5000;$("#gv").firstChild.textContent=(v>=100?Math.round(v):v.toFixed(1))+" ";
 if(final)$$(".chip").forEach(ch=>ch.classList.toggle("y",v>=+ch.dataset.m))}
/* ---------- world map ---------- */
const LAND="AAAAAAP/////wAAAAAAAAAAAAAAAAAAAB/////8AB/AEAAB8AAAAAAAAADM//P///wADQAAEAA+AAAAAAAAAb5/4A///AAAAAHgD/+AHAAAAAAD/3/4B//4AAAABg3///4PAAID/gV/u/8H//AAAfACH//////4Aw//////z4P/wAAH/2//////////3/////+P4/4fAB////////////wn/////9+B8A4Af////////////A/////4HgDgAAD9///////////wB/H///AfwAAAAPz/////////5gABwD///g/gAAAYff////////AeAAQAH///3/gAADx/////////4BwAAAAH///f/AAAPv/////////8GAAAAAf////8AAAP//////////wAAAAAA////94AAA//////////9AAAAAAB////4AAAB///9//////kAAAAAAP///4AAAA//+Hv/////84AAAAAA////gAAAD5///f/////CAAAAAAB///4AAAAPAX/9////+4IAAAAAAD///gAAAA/6b//////8zgAAAAAAP//8AAAAB/gB//////y8AAAAAAAP//gAAAAP/nH//////CAAAAAAAA//8AAAAB/////////8AAAAAAAAB/gYAAAAP////f////wAAAAAAAAD+AwAAAB////+/////AAAAAAAAAD4GAAAAH///3/j///0AAAAACAAAHjGAAAA/////8H+f8AAAAAAAAAAf4XgAAD///+/wPx+gAAAAAAAAAAf4AAAAP///98A+D8GAAAAAAAAAAHgAAAA/////ABwH4YAAAAAAAAAAGGAAAD////2AHAPgwAAAAAAAAAAP/gAAH////4AMBsLAAAAAAAAAAAf/AAAP////AAYCAOAAAAAAAAAAAf/gAAfP//8AAA8GAAAAAAAAAAAB//AAAAP//gAABx4AAAAAAAAAAAP/8AAAA//8AAADP6AAAAAAAAAAA//+AAAD//gAAAG9jQAAAAAAAAAD//+AAAP/8AAAAYW35AAAAAAAAAP//+AAAf/wAAAA8AH8AAAAAAAAAf//4AAB//AAAAA7QdDAAAAAAAAB///AAAD/8AAAAAAACAAAAAAAAAD//4AAAf/xAAAAAA5AAAAAAAAAAP//gAAB//OAAAAAfmAIAAAAAAAAP/+AAAH/5wAAAAD/4ABAAAAAAAA//wAAAf/HAAAAA//wAAAAAAAAAB//AAAA/8cAAAAP//gQAAAAAAAAP/wAAAD/xgAAAA///AAAAAAAAAA/+AAAAP+AAAAAD//8AAAAAAAAAD/wAAAAf4AAAAAH//4AAAAAAAAAP/AAAAA/AAAAAAf//AAAAAAAAAA/4AAAAD4AAAAAB8f8AAAAAAAAAH+AAAAAAAAAAAAAAfgBAAAAAAAAf4AAAAAAAAAAAAAA+AHAAAAAAAB+AAAAAAAAAAAAAAAAAYAAAAAAAHwAAAAAAAAAAAAAADADAAAAAAAAeAAAAAAAAAAAAAAAAA4AAAAAAAD4AAAAAAAAAAAAAAAADAAAAAAAAPAAAAAAAAAAgAAAAAAAAAAAAAAA8QAAAAAAAAAAAAAAAAAAAAAAAABwAAAAAAAAAAAAAAAAAAAAAAAAABgAAAAAAAAAAAAAAAAAA==",MC=160,MR=62,MLAT0=83,MSPAN=140;
const LB=(()=>{const b=atob(LAND),a=new Uint8Array(MC*MR);for(let i=0;i<a.length;i++)a[i]=(b.charCodeAt(i>>3)>>(7-(i&7)))&1;return a})();
/* Offline placement for servers whose endpoint has not been geolocated yet (or cannot be: offline, private IP).
   Understands names like "Frankfurt", "NewYork", "us-nyc-01", "de-fra", "Tokyo 2", "SG". */
const PLACE=(()=>{const g=t=>{const m={};t.split(",").forEach(e=>{const[k,a,b]=e.split(" ");m[k]=[+a,+b]});return m},al=t=>{const m={};t.split(",").forEach(e=>{const[k,v]=e.split("=");m[k]=v});return m};
 const city=g("newyork 40.71 -74.01,losangeles 34.05 -118.24,chicago 41.88 -87.63,dallas 32.78 -96.8,miami 25.76 -80.19,seattle 47.61 -122.33,sanfrancisco 37.77 -122.42,sanjose 37.34 -121.89,siliconvalley 37.39 -122.03,denver 39.74 -104.99,atlanta 33.75 -84.39,phoenix 33.45 -112.07,lasvegas 36.17 -115.14,boston 42.36 -71.06,washington 38.9 -77.04,ashburn 39.04 -77.49,newjersey 40.06 -74.41,secaucus 40.79 -74.06,houston 29.76 -95.37,saltlakecity 40.76 -111.89,kansascity 39.1 -94.58,buffalo 42.89 -78.88,portland 45.52 -122.68,charlotte 35.23 -80.84,toronto 43.65 -79.38,montreal 45.5 -73.57,vancouver 49.28 -123.12,calgary 51.05 -114.07,mexicocity 19.43 -99.13,saopaulo -23.55 -46.63,riodejaneiro -22.91 -43.17,buenosaires -34.6 -58.38,santiago -33.45 -70.67,bogota 4.71 -74.07,lima -12.05 -77.04,london 51.51 -0.13,manchester 53.48 -2.24,dublin 53.35 -6.26,paris 48.86 2.35,marseille 43.3 5.37,amsterdam 52.37 4.9,rotterdam 51.92 4.48,brussels 50.85 4.35,frankfurt 50.11 8.68,berlin 52.52 13.4,munich 48.14 11.58,hamburg 53.55 9.99,dusseldorf 51.23 6.78,nuremberg 49.45 11.08,falkenstein 50.48 12.37,zurich 47.38 8.54,geneva 46.2 6.14,vienna 48.21 16.37,prague 50.08 14.44,warsaw 52.23 21.01,budapest 47.5 19.04,bucharest 44.43 26.1,sofia 42.7 23.32,belgrade 44.79 20.45,zagreb 45.81 15.98,athens 37.98 23.73,milan 45.46 9.19,rome 41.9 12.5,madrid 40.42 -3.7,barcelona 41.39 2.17,lisbon 38.72 -9.14,copenhagen 55.68 12.57,stockholm 59.33 18.07,oslo 59.91 10.75,helsinki 60.17 24.94,tallinn 59.44 24.75,riga 56.95 24.11,vilnius 54.69 25.28,kyiv 50.45 30.52,kiev 50.45 30.52,moscow 55.76 37.62,stpetersburg 59.93 30.34,istanbul 41.01 28.98,telaviv 32.09 34.78,dubai 25.2 55.27,abudhabi 24.45 54.38,doha 25.29 51.53,riyadh 24.71 46.68,cairo 30.04 31.24,johannesburg -26.2 28.05,capetown -33.92 18.42,lagos 6.52 3.38,nairobi -1.29 36.82,casablanca 33.57 -7.59,mumbai 19.08 72.88,bombay 19.08 72.88,newdelhi 28.61 77.21,delhi 28.61 77.21,bangalore 12.97 77.59,bengaluru 12.97 77.59,chennai 13.08 80.27,hyderabad 17.39 78.49,kolkata 22.57 88.36,pune 18.52 73.86,noida 28.54 77.39,karachi 24.86 67,lahore 31.55 74.34,dhaka 23.81 90.41,colombo 6.93 79.86,kathmandu 27.72 85.32,singapore 1.35 103.82,kualalumpur 3.14 101.69,jakarta -6.21 106.85,bangkok 13.76 100.5,hanoi 21.03 105.85,hochiminh 10.82 106.63,saigon 10.82 106.63,manila 14.6 120.98,hongkong 22.32 114.17,taipei 25.03 121.57,tokyo 35.68 139.69,osaka 34.69 135.5,seoul 37.57 126.98,beijing 39.9 116.4,shanghai 31.23 121.47,shenzhen 22.54 114.06,sydney -33.87 151.21,melbourne -37.81 144.96,brisbane -27.47 153.03,perth -31.95 115.86,auckland -36.85 174.76,almaty 43.24 76.89,tbilisi 41.72 44.78,yerevan 40.18 44.51,baku 40.41 49.87,reykjavik 64.15 -21.94,luxembourg 49.61 6.13,panamacity 8.98 -79.52"),
 country=g("usa 39 -98,unitedstates 39 -98,america 39 -98,uk 51.5 -0.1,unitedkingdom 51.5 -0.1,britain 51.5 -0.1,england 51.5 -0.1,germany 50.1 8.7,france 48.9 2.4,netherlands 52.4 4.9,holland 52.4 4.9,japan 35.7 139.7,india 19.1 72.9,australia -33.9 151.2,canada 43.7 -79.4,brazil -23.5 -46.6,korea 37.6 127,southkorea 37.6 127,switzerland 47.4 8.5,sweden 59.3 18.1,norway 59.9 10.75,finland 60.2 24.9,denmark 55.7 12.6,spain 40.4 -3.7,portugal 38.7 -9.1,italy 45.5 9.2,ireland 53.3 -6.3,belgium 50.85 4.35,austria 48.2 16.4,poland 52.2 21,czechia 50.1 14.4,czech 50.1 14.4,hungary 47.5 19,romania 44.4 26.1,bulgaria 42.7 23.3,greece 38 23.7,serbia 44.8 20.5,croatia 45.8 16,estonia 59.4 24.75,latvia 56.95 24.1,lithuania 54.7 25.3,iceland 64.1 -21.9,turkey 41 29,turkiye 41 29,israel 32.1 34.8,uae 25.2 55.3,emirates 25.2 55.3,saudiarabia 24.7 46.7,saudi 24.7 46.7,qatar 25.3 51.5,bahrain 26.1 50.6,egypt 30 31.2,southafrica -26.2 28.05,nigeria 6.5 3.4,kenya -1.3 36.8,morocco 33.6 -7.6,russia 55.8 37.6,ukraine 50.45 30.5,mexico 19.4 -99.1,argentina -34.6 -58.4,chile -33.45 -70.7,colombia 4.7 -74.1,peru -12 -77,china 31.2 121.5,taiwan 25 121.6,thailand 13.8 100.5,vietnam 21 105.85,malaysia 3.1 101.7,indonesia -6.2 106.85,philippines 14.6 121,pakistan 24.9 67,bangladesh 23.8 90.4,srilanka 6.9 79.9,nepal 27.7 85.3,newzealand -36.85 174.8,kazakhstan 43.2 76.9,armenia 40.2 44.5,azerbaijan 40.4 49.9,panama 8.98 -79.5,hongkong 22.3 114.2,singapore 1.35 103.8"),
 air=al("nyc=newyork,jfk=newyork,ewr=newyork,lax=losangeles,sfo=sanfrancisco,sjc=sanjose,sea=seattle,ord=chicago,chi=chicago,dfw=dallas,dal=dallas,mia=miami,atl=atlanta,iad=ashburn,was=washington,den=denver,phx=phoenix,las=lasvegas,bos=boston,iah=houston,slc=saltlakecity,yyz=toronto,yul=montreal,yvr=vancouver,yyc=calgary,mex=mexicocity,gru=saopaulo,sao=saopaulo,gig=riodejaneiro,eze=buenosaires,scl=santiago,bog=bogota,lim=lima,lhr=london,lon=london,man=manchester,dub=dublin,cdg=paris,par=paris,mrs=marseille,ams=amsterdam,rtm=rotterdam,bru=brussels,fra=frankfurt,ber=berlin,muc=munich,ham=hamburg,dus=dusseldorf,nue=nuremberg,zrh=zurich,gva=geneva,vie=vienna,prg=prague,waw=warsaw,bud=budapest,otp=bucharest,buh=bucharest,sof=sofia,beg=belgrade,zag=zagreb,ath=athens,mxp=milan,mil=milan,fco=rome,rom=rome,mad=madrid,bcn=barcelona,lis=lisbon,cph=copenhagen,arn=stockholm,sto=stockholm,osl=oslo,hel=helsinki,tll=tallinn,rix=riga,vno=vilnius,kbp=kyiv,iev=kyiv,svo=moscow,mow=moscow,led=stpetersburg,ist=istanbul,tlv=telaviv,dxb=dubai,auh=abudhabi,doh=doha,ruh=riyadh,cai=cairo,jnb=johannesburg,cpt=capetown,los=lagos,nbo=nairobi,cmn=casablanca,bom=mumbai,del=delhi,blr=bangalore,maa=chennai,hyd=hyderabad,ccu=kolkata,pnq=pune,khi=karachi,lhe=lahore,dac=dhaka,cmb=colombo,ktm=kathmandu,sin=singapore,kul=kualalumpur,cgk=jakarta,jkt=jakarta,bkk=bangkok,han=hanoi,sgn=hochiminh,mnl=manila,hkg=hongkong,tpe=taipei,nrt=tokyo,hnd=tokyo,tyo=tokyo,kix=osaka,osa=osaka,icn=seoul,sel=seoul,pek=beijing,bjs=beijing,pvg=shanghai,sha=shanghai,szx=shenzhen,syd=sydney,mel=melbourne,bne=brisbane,per=perth,akl=auckland,ala=almaty,tbs=tbilisi,evn=yerevan,gyd=baku,kef=reykjavik,lux=luxembourg,pty=panamacity"),iso=al("us=usa,gb=uk,de=germany,fr=france,nl=netherlands,jp=japan,in=india,sg=singapore,au=australia,ca=canada,br=brazil,kr=korea,hk=hongkong,ch=switzerland,se=sweden,no=norway,fi=finland,dk=denmark,es=spain,pt=portugal,it=italy,ie=ireland,be=belgium,at=austria,pl=poland,cz=czechia,hu=hungary,ro=romania,bg=bulgaria,gr=greece,rs=serbia,hr=croatia,ee=estonia,lv=latvia,lt=lithuania,is=iceland,tr=turkey,il=israel,ae=uae,sa=saudiarabia,qa=qatar,bh=bahrain,eg=egypt,za=southafrica,ng=nigeria,ke=kenya,ma=morocco,ru=russia,ua=ukraine,mx=mexico,ar=argentina,cl=chile,co=colombia,pe=peru,cn=china,tw=taiwan,th=thailand,vn=vietnam,my=malaysia,id=indonesia,ph=philippines,pk=pakistan,bd=bangladesh,lk=srilanka,np=nepal,nz=newzealand,kz=kazakhstan,am=armenia,az=azerbaijan,pa=panama,lu=luxembourg");
 const byLen=o=>Object.keys(o).filter(k=>k.length>5).sort((a,b)=>b.length-a.length);return{city,country,air,iso,cityK:byLen(city),countryK:byLen(country)}})();
function guessPlace(name){const toks=String(name||"").replace(/([a-z])([A-Z])/g,"$1 $2").toLowerCase().split(/[^a-z]+/).filter(Boolean),joined=toks.join("");
 for(const k of PLACE.cityK)if(joined.includes(k))return PLACE.city[k];
 for(const t of toks)if(PLACE.city[t])return PLACE.city[t];
 for(const t of toks)if(PLACE.air[t])return PLACE.city[PLACE.air[t]];
 for(const k of PLACE.countryK)if(joined.includes(k))return PLACE.country[k];
 for(const t of toks)if(PLACE.country[t])return PLACE.country[t];
 /* 2-letter country codes only as the leading part ("us-nyc", "de-1"); ones that are also English words count only alone */
 const c2=toks[0];if(c2&&c2.length===2&&PLACE.iso[c2]&&(toks.length===1||!/^(is|it|no|be|am|at|my|me|id|co|ma|pe|ar|in)$/.test(c2)))return PLACE.country[PLACE.iso[c2]];
 return null}
let BOX={x:0,y:0,w:1,h:1},MAPC=null,MAPKEY="",TW=[],SUNP=null;
const cv=$("#orbit"),cx=cv.getContext("2d");let W=0,H=0,dpr=1;
function mapBox(){const pad=22,top=78,bot=84,aw=W-pad*2,ah=Math.max(60,H-top-bot),asp=MC/MR;let w=aw,h=Math.min(ah,w/asp*1.24);return{x:(W-w)/2,y:top+(ah-h)/2,w,h}}
function proj(lat,lon){return{x:BOX.x+(lon+180)/360*BOX.w,y:BOX.y+(MLAT0-lat)/MSPAN*BOX.h}}
const isLight=()=>document.documentElement.dataset.theme==="light";
/* smoothed land field: lightly blurred copy of the coarse mask, sampled bilinearly at a much finer pitch */
const LF=(()=>{const a=new Float32Array(MC*MR);
 for(let y=0;y<MR;y++)for(let x=0;x<MC;x++){let sum=0,wt=0;for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const yy=y+dy;if(yy<0||yy>=MR)continue;const xx=(x+dx+MC)%MC,w=(dx&&dy)?1:(dx||dy)?2:10;sum+=LB[yy*MC+xx]*w;wt+=w}a[y*MC+x]=sum/wt}return a})();
function land(u,v){const x=u-.5,y=v-.5,x0=Math.floor(x),y0=Math.floor(y),fx=x-x0,fy=y-y0;
 const g=(xx,yy)=>(yy<0||yy>=MR)?0:LF[yy*MC+(((xx%MC)+MC)%MC)];
 return(g(x0,y0)*(1-fx)+g(x0+1,y0)*fx)*(1-fy)+(g(x0,y0+1)*(1-fx)+g(x0+1,y0+1)*fx)*fy}
let GLOWC=null,BASEC=null,WARM=null,HALO=null,HALOKEY="";
/* Soft edges. Only a thin band at the very top (above the Arctic coast) and bottom dissolves into the background,
   so the continents keep their full brightness: the map blends in instead of looking cut off or dimmed. */
const MFADE_TOP=.09,MFADE_BOT=.06,DOT_TOP=.24,DOT_BOT=.12,smooth=x=>x<=0?0:x>=1?1:x*x*(3-2*x);
/* stipple dissolve: near the top/bottom edge the dots shrink (not dim), so the map feathers into the background */
const hash01=(i,j)=>{let h=Math.imul(i,73856093)^Math.imul(j,19349663);h=Math.imul(h^(h>>>13),1274126177);return((h^(h>>>16))>>>0)/4294967296};
const dotScale=u=>Math.min(smooth(u/DOT_TOP),smooth((1-u)/DOT_BOT))*.82+.18;
function fadeAt(y){const u=(y-BOX.y)/BOX.h;if(u<=0||u>=1)return 0;return smooth(u/MFADE_TOP)*smooth((1-u)/MFADE_BOT)}
function fadeMask(g){g.save();g.setTransform(dpr,0,0,dpr,0,0);g.globalCompositeOperation="destination-in";
 const fg=g.createLinearGradient(0,BOX.y,0,BOX.y+BOX.h);
 for(let k=0;k<=10;k++){const p=k/10;fg.addColorStop(p*MFADE_TOP,"rgba(0,0,0,"+smooth(p).toFixed(3)+")");fg.addColorStop(1-p*MFADE_BOT,"rgba(0,0,0,"+smooth(p).toFixed(3)+")")}
 g.fillStyle=fg;g.fillRect(0,0,W,H);g.restore()}
function mkCanvas(){const c=document.createElement("canvas");c.width=Math.max(1,Math.round(W*dpr));c.height=Math.max(1,Math.round(H*dpr));const g=c.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);return[c,g]}
/* ---------- live day / night: the world as it is right now (sun position from the UTC date and time) ---------- */
function sunPos(d){const t=d.getTime()/864e5-10957.5,rad=Math.PI/180,g=(357.529+.98560028*t)*rad,q=280.459+.98564736*t,
 L=(q+1.915*Math.sin(g)+.02*Math.sin(2*g))*rad,e=(23.439-3.6e-7*t)*rad,dec=Math.asin(Math.sin(e)*Math.sin(L)),
 ra=Math.atan2(Math.cos(e)*Math.sin(L),Math.cos(L))/rad,gmst=(280.46061837+360.98564736629*t)%360;
 return{lat:dec/rad,lon:((ra-gmst)%360+540)%360-180}}
function nightMask(sun){const w=192,h=Math.max(24,Math.round(w*BOX.h/BOX.w)),c=document.createElement("canvas");c.width=w;c.height=h;
 const g=c.getContext("2d"),im=g.createImageData(w,h),d=im.data,rad=Math.PI/180,sd=Math.sin(sun.lat*rad),cd=Math.cos(sun.lat*rad),
 light=isLight(),col=light?[38,50,92]:[6,10,28],A=light?.46:.66;
 for(let y=0;y<h;y++){const la=(MLAT0-(y+.5)/h*MSPAN)*rad,sl=Math.sin(la),cl=Math.cos(la);
  for(let x=0;x<w;x++){const lo=(-180+(x+.5)/w*360-sun.lon)*rad,alt=Math.asin(sl*sd+cl*cd*Math.cos(lo))/rad,
   n=smooth(Math.min(1,Math.max(0,(4-alt)/14))),k=(y*w+x)*4;d[k]=col[0];d[k+1]=col[1];d[k+2]=col[2];d[k+3]=Math.round(n*A*255)}}
 g.putImageData(im,0,0);return c}
setInterval(()=>{if(!document.hidden)invalidate()},300000);          /* the terminator moves ~1.25 deg per 5 min */
function buildMap(){BOX=mapBox();const key=[W,H,dpr,document.documentElement.dataset.theme,Math.floor(Date.now()/3e5)].join();if(key===MAPKEY)return;MAPKEY=key;
 const light=isLight(),[c1,g1]=mkCanvas(),[c2,g2]=mkCanvas();MAPC=c1;WARM=c2;HALOKEY="";
 const base=light?"58,64,84":"214,198,208",hi=light?"201,65,0":"255,122,51";
 const pitch=Math.max(2.5,BOX.w/320),nx=Math.max(1,Math.floor(BOX.w/pitch)),ny=Math.max(1,Math.floor(BOX.h/pitch)),px=BOX.w/nx,py=BOX.h/ny;
 g1.save();g1.lineWidth=1;g1.strokeStyle="rgba("+base+",.08)";g1.setLineDash([2,6]);
 for(let lo=-150;lo<=180;lo+=30){const x=BOX.x+(lo+180)/360*BOX.w;g1.beginPath();g1.moveTo(x,BOX.y);g1.lineTo(x,BOX.y+BOX.h);g1.stroke()}
 for(let la=-40;la<=80;la+=20){const y=BOX.y+(MLAT0-la)/MSPAN*BOX.h;g1.beginPath();g1.moveTo(BOX.x,y);g1.lineTo(BOX.x+BOX.w,y);g1.stroke()}
 g1.restore();
 for(let j=0;j<ny;j++)for(let i=0;i<nx;i++){
  const f=land((i+.5)/nx*MC,(j+.5)/ny*MR);if(f<.38)continue;
  const x=BOX.x+(i+.5)*px,y=BOX.y+(j+.5)*py,rim=f<.62,n=((i*7+j*13)%5)*.012,ds=dotScale((j+.5)/ny),r=Math.min(px,py)*(rim?.30:.40)*ds;
  if(ds<.999&&(hash01(i>>3,j>>2)*.5+hash01(i>>1,j>>1)*.3+hash01(i,j)*.2)>ds*1.1)continue;   /* clumpy, organic thinning: the coast dissolves in patches, never in a straight line */
  g1.fillStyle="rgba("+base+","+(rim?.62:.24+n).toFixed(3)+")";g1.beginPath();g1.arc(x,y,r,0,6.3);g1.fill();
  g2.fillStyle="rgba("+hi+","+(rim?.95:.75)+")";g2.beginPath();g2.arc(x,y,r*1.1,0,6.3);g2.fill()}
 const SUN=sunPos(new Date());SUNP=SUN;{const nm=nightMask(SUN);g1.save();g1.globalCompositeOperation="source-atop";
  g1.imageSmoothingEnabled=true;g1.imageSmoothingQuality="high";g1.drawImage(nm,BOX.x,BOX.y,BOX.w,BOX.h);g1.restore()}
 /* soft glow without a GPU blur filter: shrink the dots to 1/5 size and stretch them back (bilinear = free blur) */
 const[c3,g3]=mkCanvas();GLOWC=c3;const sm=document.createElement("canvas");sm.width=Math.max(1,Math.round(W/5));sm.height=Math.max(1,Math.round(H/5));
 const sg=sm.getContext("2d");sg.imageSmoothingQuality="high";sg.drawImage(c1,0,0,sm.width,sm.height);g3.imageSmoothingQuality="high";g3.drawImage(sm,0,0,W,H);
 [g1,g2,g3].forEach(fadeMask);
 const[c4,g4]=mkCanvas();
 /* atmosphere: a wide, very soft glow behind the map that is NOT clipped to the map box, so the map melts into the
    background above and below instead of ending at a hard line */
 const cxm=W/2,cym=BOX.y+BOX.h*.42,rr=Math.max(BOX.w*.62,BOX.h*1.05),sky=g4.createRadialGradient(cxm,cym,0,cxm,cym,rr),tint=light?"201,65,0":"255,122,51";
 [[0,light?.05:.075],[.35,light?.032:.05],[.62,light?.014:.022],[.82,light?.004:.007],[1,0]].forEach(([p,a])=>sky.addColorStop(p,"rgba("+tint+","+a+")"));
 g4.save();g4.translate(cxm,cym);g4.scale(1,.62);g4.translate(-cxm,-cym);g4.fillStyle=sky;g4.fillRect(-W,-H*3,W*3,H*7);g4.restore();
 if(SUN.lat<=MLAT0&&SUN.lat>=MLAT0-MSPAN){const sp=proj(SUN.lat,SUN.lon),sr=BOX.h*.42,sg=g4.createRadialGradient(sp.x,sp.y,0,sp.x,sp.y,sr);
  [[0,light?.10:.13],[.4,light?.04:.05],[1,0]].forEach(([p,a])=>sg.addColorStop(p,"rgba(255,196,120,"+a+")"));g4.fillStyle=sg;g4.fillRect(sp.x-sr,sp.y-sr,sr*2,sr*2)}
 g4.globalAlpha=.55;g4.drawImage(c3,0,0,W,H);g4.globalAlpha=1;g4.drawImage(c1,0,0,W,H);BASEC=c4}
function regLoc(r,i){const q=r.geo;if(q&&q.lat!=null)return[q.lat,q.lon];return guessPlace(r.name)||[15,-160+i*45]}
function homeLoc(){const h=S.home;if(h&&h.lat!=null)return[h.lat,h.lon];return[25,-new Date().getTimezoneOffset()/60*15]}
function resize(){const r=cv.parentElement.getBoundingClientRect();dpr=Math.min(devicePixelRatio||1,3);W=r.width;H=r.height;for(const c of [cv,fxc]){c.width=W*dpr;c.height=H*dpr}cx.setTransform(dpr,0,0,dpr,0,0);fx.setTransform(dpr,0,0,dpr,0,0);MAPKEY="";drawMap();draw2()}
addEventListener("resize",resize);
let HIT=[],MG={hp:null,p:null,k:null,col:ACC};
function bez(a,b,c,t){const u=1-t;return{x:u*u*a.x+2*u*t*b.x+t*t*c.x,y:u*u*a.y+2*u*t*b.y+t*t*c.y}}
function arcCtl(a,b){const d=Math.hypot(b.x-a.x,b.y-a.y);return{x:(a.x+b.x)/2,y:Math.min(a.y,b.y)-d*.3-10}}
const CSSV={};function cssv(n,f){const k=(document.documentElement.dataset.theme||"")+n;return CSSV[k]||(CSSV[k]=getComputedStyle(document.documentElement).getPropertyValue(n).trim()||f)}
/* ---------- Map rendering: lightweight by design ----------
   Every animated frame costs CPU/GPU whatever it shows, so the map does not animate all the time:
   * #orbit is a STILL layer, redrawn only when something changes (state, ping, hover, theme, resize);
   * #fx holds short animation bursts (signature pulse, hover pop, connect ripples, connecting comet, traffic
     waves). Its frame loop runs only while a burst plays, at full display rate, then stops completely;
   * ambient motion (signature pulse, traffic waves) plays only while the window is focused and visible. */
const fxc=document.createElement("canvas");fxc.id="fx";fxc.setAttribute("aria-hidden","true");cv.after(fxc);const fx=fxc.getContext("2d");
const ease=u=>u<.5?2*u*u:1-Math.pow(-2*u+2,2)/2,easeOut=u=>1-Math.pow(1-u,3);
const FX={raf:0,until:0,pulses:[],waves:[],drawn:false};
let DIRTY=false;
function invalidate(){if(DIRTY)return;DIRTY=true;requestAnimationFrame(()=>{DIRTY=false;if(!document.hidden)drawMap()})}
function wake(ms){FX.until=Math.max(FX.until,performance.now()+ms);if(!FX.raf&&!document.hidden)FX.raf=requestAnimationFrame(fxFrame)}
function fxFrame(t){FX.raf=0;if(document.hidden)return;drawFx(t);
 if(t<FX.until)FX.raf=requestAnimationFrame(fxFrame);else if(FX.drawn){fx.clearRect(0,0,W,H);FX.drawn=false}}
function pulse(x,y,o){const d=o.delay||0;FX.pulses.push({x,y,t0:performance.now()+d,dur:o.dur,r0:o.r0,r1:o.r1,c:o.c,a:o.a,w:o.w||1.2});wake(d+o.dur+20)}
const ambientOk=()=>!document.hidden&&document.hasFocus();
/* signature: one calm breath from "You" (and the server you're on) every few seconds; nothing in between */
function signature(){if(!ambientOk()||!MG.hp||S.connecting||S.connected)return;const F=isLight()?"rgb(30,34,48)":"#fff";
 pulse(MG.hp.x,MG.hp.y,{c:F,a:.44,r0:5,r1:46,dur:1900});pulse(MG.hp.x,MG.hp.y,{c:F,a:.24,r0:5,r1:46,dur:1900,delay:380})}
setInterval(signature,9000);setTimeout(signature,2600);
/* traffic: one wave per 2 s sample at most. Busy tunnel = a fast wave every sample, light use = every 2nd,
   idle tunnel = every 3rd. Uploads ride along as a small counter-wave in the same burst (no extra frames).
   The server you're on breathes with each wave, so being connected never adds a separate animation. */
let TWN=0;function trafficWave(p){if(!S.connected||!ambientOk()||!MG.p)return;const rx=p.rx_bps||0,tx=p.tx_bps||0,r=rx+tx;TWN++;
 if(TWN%(r>=1e6?1:r>=16e3?2:3))return;const dur=1250-Math.min(1,r/8e6)*400,t=performance.now();
 FX.waves.push({t0:t,dur,dir:-1});if(tx>1.5e5)FX.waves.push({t0:t+dur*.1,dur:dur*.9,dir:1,small:1});
 pulse(MG.p.x,MG.p.y,{c:MG.col,a:.6,r0:8,r1:28,dur:dur*.9,delay:dur*.1})}
addEventListener("focus",()=>invalidate());
document.addEventListener("visibilitychange",()=>{if(!document.hidden){invalidate();if(FX.until>performance.now())wake(0)}});
new MutationObserver(()=>{MAPKEY="";invalidate()}).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
/* greedy label placement: first side (above, below, right, left) that overlaps no pin / earlier label */
function placeLabel(p,nw,two,taken){const lh=two?28:14,opts=[
  {align:"center",x:p.x,y:p.y-14,y2:p.y+24,box:{x:p.x-nw/2,y:p.y-26,w:nw,h:14},box2:{x:p.x-22,y:p.y+13,w:44,h:13}},
  {align:"center",x:p.x,y:p.y+24,y2:p.y+38,box:{x:p.x-nw/2,y:p.y+13,w:nw,h:lh}},
  {align:"left",x:p.x+13,y:p.y+4,y2:p.y+18,box:{x:p.x+12,y:p.y-8,w:Math.max(nw,44),h:lh}},
  {align:"right",x:p.x-13,y:p.y+4,y2:p.y+18,box:{x:p.x-12-Math.max(nw,44),y:p.y-8,w:Math.max(nw,44),h:lh}}];
 const hit=b=>taken.some(t=>b.x<t.x+t.w&&b.x+b.w>t.x&&b.y<t.y+t.h&&b.y+b.h>t.y),ok=o=>!hit(o.box)&&!(two&&o.box2&&hit(o.box2));
 const o=opts.find(ok)||opts[0];taken.push(o.box);if(two&&o.box2)taken.push(o.box2);return o}
function drawMap(){const g=cx;g.clearRect(0,0,W,H);buildMap();if(BASEC)g.drawImage(BASEC,0,0,W,H);
 const col=S.connected?"#3dffb0":S.connecting?"#ff9a7c":ACC,act=S.connected?S.active:S.connecting;
 const hl=homeLoc(),hp=proj(hl[0],hl[1]);S.pos={};HIT=[];MG={hp,p:null,k:null,col};
 S.regions.forEach((r,i)=>{const l=regLoc(r,i);S.pos[r.name]=proj(l[0],l[1])});
 const hk=MAPKEY+"|"+Math.round(hp.x)+","+Math.round(hp.y);
 if(WARM&&hk!==HALOKEY){HALOKEY=hk;const[c,h]=mkCanvas();h.drawImage(WARM,0,0,W,H);h.globalCompositeOperation="destination-in";
  const R=Math.max(W,H)*.42,rg=h.createRadialGradient(hp.x,hp.y,0,hp.x,hp.y,R);const L=isLight();rg.addColorStop(0,"rgba(0,0,0,"+(L?.34:.55)+")");rg.addColorStop(.45,"rgba(0,0,0,"+(L?.12:.22)+")");rg.addColorStop(1,"rgba(0,0,0,0)");
  h.fillStyle=rg;h.fillRect(0,0,W,H);HALO=c}
 if(HALO)g.drawImage(HALO,0,0,W,H);
 const arc=(p,c,w,a)=>{const k=arcCtl(hp,p);g.strokeStyle=c;g.globalAlpha=a;g.lineWidth=w;g.beginPath();g.moveTo(hp.x,hp.y);g.quadraticCurveTo(k.x,k.y,p.x,p.y);g.stroke();g.globalAlpha=1;return k};
 S.regions.forEach(r=>{if(r.name!==act){g.setLineDash([2,5]);arc(S.pos[r.name],"#9fb4d8",1,.10);g.setLineDash([])}});
 if(S.hover&&S.hover.t==="n"&&S.hover.name!==act)arc(S.pos[S.hover.name],isLight()?"#202436":"#fff",1.2,.30);
 if(act&&S.pos[act]){const p=S.pos[act],hg=g.createRadialGradient(p.x,p.y,0,p.x,p.y,46);hg.addColorStop(0,col+"55");hg.addColorStop(1,col+"00");g.fillStyle=hg;g.fillRect(p.x-46,p.y-46,92,92);
  const lg=g.createLinearGradient(hp.x,hp.y,p.x,p.y);lg.addColorStop(0,col+"66");lg.addColorStop(1,col);
  g.shadowColor=col;g.shadowBlur=12;const k=arc(p,lg,2,.95);g.shadowBlur=0;g.setLineDash([5,9]);arc(p,"#fff",1,S.connected?.35:.5);g.setLineDash([]);MG.p=p;MG.k=k}
 const FGC=isLight()?"30,34,48":"255,255,255";
 const hgl=g.createRadialGradient(hp.x,hp.y,0,hp.x,hp.y,26);hgl.addColorStop(0,"rgba("+FGC+",.16)");hgl.addColorStop(1,"rgba("+FGC+",0)");g.fillStyle=hgl;g.fillRect(hp.x-26,hp.y-26,52,52);
 g.fillStyle="rgb("+FGC+")";g.beginPath();g.arc(hp.x,hp.y,3.4,0,6.3);g.fill();g.strokeStyle="rgba("+FGC+",.45)";g.lineWidth=1;g.beginPath();g.arc(hp.x,hp.y,8,0,6.3);g.stroke();
 g.strokeStyle="rgba("+FGC+",.14)";g.beginPath();g.arc(hp.x,hp.y,15,0,6.3);g.stroke();
 g.fillStyle=cssv("--canvas-muted","#9aa7bd");g.font="11px "+FONTS;g.textAlign="center";g.fillText("You",hp.x,hp.y+23);
 const LBL=[{x:hp.x-14,y:hp.y+12,w:28,h:14},{x:hp.x-9,y:hp.y-9,w:18,h:18}];   /* keep "You" and its dot clear */
 S.regions.forEach(r=>{const q=S.pos[r.name];LBL.push({x:q.x-9,y:q.y-9,w:18,h:18})});   /* and every pin */
 S.regions.forEach(r=>{const p=S.pos[r.name],isA=r.name===act,isS=r.name===S.selected,isH=S.hover&&S.hover.name===r.name,pcol=isA?col:pc(r.ping),rad=isA?7:5.5;
  if(isA){g.strokeStyle=col;g.globalAlpha=.35;g.lineWidth=1.4;g.beginPath();g.arc(p.x,p.y,rad+9,0,6.3);g.stroke();g.globalAlpha=1;g.shadowColor=col;g.shadowBlur=18}
  g.fillStyle=pcol;g.beginPath();g.arc(p.x,p.y,rad+(isH?1.5:0),0,6.3);g.fill();g.shadowBlur=0;g.strokeStyle="rgba(5,8,16,.9)";g.lineWidth=2;g.stroke();if(r.ping&&r.ping.rtt!=null){const qv=Math.max(.08,Math.min(1,1-r.ping.rtt/300));g.strokeStyle=pcol;g.globalAlpha=.6;g.lineWidth=1.6;g.beginPath();g.arc(p.x,p.y,rad+4.5,-Math.PI/2,-Math.PI/2+qv*6.283);g.stroke();g.globalAlpha=1}
  if(isS&&!isA){g.setLineDash([3,3]);g.strokeStyle=isLight()?"rgba(30,34,48,.7)":"rgba(255,255,255,.7)";g.lineWidth=1.2;g.beginPath();g.arc(p.x,p.y,rad+6,0,6.3);g.stroke();g.setLineDash([])}
  const nm=r.name.length>14?r.name.slice(0,13)+"…":r.name,ms=r.ping&&r.ping.rtt!=null?(r.ping.est?"~":"")+r.ping.rtt+" ms":"";
  g.font="600 12px "+FONTS;const nw=g.measureText(nm).width,L=placeLabel(p,nw,!!ms,LBL);
  g.textAlign=L.align;g.fillStyle=cssv("--canvas-label","#eaf1fb");g.fillText(nm,L.x,L.y);
  if(ms){g.font="11px "+FONTS;g.fillStyle=pcol;g.fillText(ms,L.x,L.y2)}
  HIT.push({t:"n",name:r.name,x:p.x,y:p.y,r:18,r2:r})});
 if(!S.regions.length){g.fillStyle="#7d8aa0";g.font="13px "+FONTS;g.textAlign="center";g.fillText("No servers yet — import a WireGuard .conf (Servers tab)",W/2,H/2)}
 if(S.hover&&S.hover.t==="n"){const r=S.hover.r2,q=r.geo,lines=[r.name+(q&&q.city?" · "+q.city+(q.country?", "+q.country:""):""),(r.host||"?")+(r.port?":"+r.port:""),r.ping&&r.ping.rtt!=null?r.ping.rtt+" ms · "+r.ping.loss+"% loss · "+r.ping.src:"not measured yet","click to connect"];
  g.font="12px "+FONTS;const tw=Math.max(...lines.map(l=>g.measureText(l).width))+22;let tx=Math.min(S.mouse.x+14,W-tw-8),ty=Math.min(S.mouse.y+14,H-84);
  g.fillStyle=isLight()?"rgba(255,255,255,.88)":"rgba(18,20,28,.78)";g.strokeStyle=isLight()?"rgba(30,30,40,.18)":"rgba(255,255,255,.16)";g.lineWidth=1;g.beginPath();g.roundRect(tx,ty,tw,72,10);g.fill();g.stroke();g.textAlign="left";lines.forEach((l,i)=>{g.fillStyle=i===0?(cssv("--canvas-label","#eaf1fb")):i===3?ACC:cssv("--canvas-muted","#9aa7bd");g.fillText(l,tx+11,ty+19+i*15)})}
 if(S.connecting)wake(400)}
function drawFx(t){const g=fx;g.clearRect(0,0,W,H);FX.drawn=true;
 FX.pulses=FX.pulses.filter(p=>t-p.t0<p.dur);
 for(const p of FX.pulses){const u=(t-p.t0)/p.dur;if(u<0)continue;g.strokeStyle=p.c;g.globalAlpha=(1-u)*(1-u)*p.a;g.lineWidth=p.w;g.beginPath();g.arc(p.x,p.y,p.r0+(p.r1-p.r0)*easeOut(u),0,6.3);g.stroke()}
 S.ripples=S.ripples.filter(r=>t-r.t0<(r.big?1600:900));S.ripples.forEach(r=>{const u=(t-r.t0)/(r.big?1600:900);if(u<0)return;g.strokeStyle=r.c;g.globalAlpha=(1-u)*(r.big?.7:1);g.lineWidth=r.big?1.5:2;g.beginPath();g.arc(r.x,r.y,r.big?10+u*230:8+u*34,0,6.3);g.stroke()});
 if(S.ripples.length)FX.until=Math.max(FX.until,t+50);
 const {hp,p,k,col}=MG;
 if(S.connecting&&p&&hp){const u=ease((t%1300)/1300);for(let i=0;i<7;i++){const uu=u-i*.03;if(uu<0)continue;const b=bez(hp,k,p,uu);g.fillStyle=col;g.globalAlpha=(1-i/7)*.95;g.beginPath();g.arc(b.x,b.y,3-i*.3,0,6.3);g.fill()}
  const v=(t%1300)/1300;g.strokeStyle=col;g.globalAlpha=(1-v)*.6;g.lineWidth=1.6;g.beginPath();g.arc(p.x,p.y,8+v*20,0,6.3);g.stroke();FX.until=Math.max(FX.until,t+120)}
 if(S.connected&&p&&hp){FX.waves=FX.waves.filter(w=>t-w.t0<w.dur);
  for(const w of FX.waves){const u=(t-w.t0)/w.dur;if(u<0)continue;const n=w.small?3:5,r0=w.small?1.8:2.6;
   for(let i=0;i<n;i++){let uu=ease(u)*1.12-i*.035;if(uu<0||uu>1)continue;if(w.dir<0)uu=1-uu;const b=bez(hp,k,p,uu);g.fillStyle=w.small?(isLight()?"#202436":"#fff"):col;g.globalAlpha=(w.small?.55:.95)*Math.sin(uu*Math.PI)*(1-i/n*.6);g.beginPath();g.arc(b.x,b.y,r0-i*.3,0,6.3);g.fill()}}}
 else FX.waves.length=0;
 g.globalAlpha=1}
function hit(e){const r=cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;S.mouse={x,y};for(const h of HIT){if(Math.hypot(h.x-x,h.y-y)<=h.r)return h}return null}
cv.addEventListener("mousemove",e=>{const prev=S.hover&&S.hover.name,h=hit(e);S.hover=h;cv.style.cursor=h?"pointer":"default";
 if(h&&h.name!==prev)pulse(h.x,h.y,{c:pc(h.r2.ping),a:.8,r0:6,r1:20,dur:460});if(h||prev)invalidate()});
cv.addEventListener("mouseleave",()=>{if(S.hover){S.hover=null;invalidate()}});
cv.addEventListener("click",e=>{const h=hit(e);if(!h)return;S.selected=h.name;if(!(S.connected&&S.active===h.name)&&!S.connecting&&!S.pendingMain){beginMainAction("Connecting to "+h.name+"…");api("connect",{name:h.name}).then(r=>{if(!r.ok){S.pendingMain="";render();toast(r.error||"Could not connect")}})}render()});
function mainAction(){if(S.pendingMain||S.connecting)return;if(S.connected){beginMainAction("Disconnecting…");api("disconnect",{}).then(r=>{if(!r.ok){S.pendingMain="";render();toast(r.error||"Could not disconnect")}})}else if(S.selected){beginMainAction("Connecting…");api("connect",{name:S.selected}).then(r=>{if(!r.ok){S.pendingMain="";render();toast(r.error||"Could not connect")}})}else{sendTask("#bFast","Comparing servers…","fastest",{},"fastest")}}
document.addEventListener("pointermove",e=>{const c=e.target.closest&&e.target.closest(".card,.m");if(c){const r=c.getBoundingClientRect();c.style.setProperty("--mx",(e.clientX-r.left)+"px");c.style.setProperty("--my",(e.clientY-r.top)+"px")}
 const v=$("#view");if(v){const r=v.getBoundingClientRect();v.style.setProperty("--gx",(e.clientX-r.left)+"px");v.style.setProperty("--gy",(e.clientY-r.top)+"px")}});
document.addEventListener("pointermove",e=>{const b=e.target.closest&&e.target.closest("button");if(b){const r=b.getBoundingClientRect();b.style.setProperty("--bx",(e.clientX-r.left)+"px");b.style.setProperty("--by",(e.clientY-r.top)+"px")}});
document.addEventListener("pointerdown",e=>{const b=e.target.closest&&e.target.closest("button");if(!b||b.disabled||b.classList.contains("sw2"))return;const r=b.getBoundingClientRect(),s=document.createElement("i"),d=Math.max(r.width,r.height)*2;s.className="rip";s.style.cssText="width:"+d+"px;height:"+d+"px;left:"+(e.clientX-r.left-d/2)+"px;top:"+(e.clientY-r.top-d/2)+"px";b.appendChild(s);setTimeout(()=>s.remove(),600)});
/* ---------- instantaneous action feedback ---------- */
const TASK_BUTTONS={fastest:["#bFast","↗ Fastest"],probe:["#bProbe","Probe all"],speed:["#bSpeed","Run speed test"],stream:["#bStream","Check"],network_diagnose:["#bNetCheck","Run network check"],valorant_manual:["#bValorant","Refresh all"],gaming:["#bGameCheck","Test custom"],ipinfo:["#bIp","Refresh"],flush_dns:["#bFlushDns","Clear DNS cache"],rescan:["#bRescan","Rescan"]};
function actionBusy(selector,label){const b=$(selector);if(!b||b.disabled)return false;b.disabled=true;b.classList.add("is-busy");b.setAttribute("aria-busy","true");b.dataset.idleText=b.dataset.idleText||b.textContent.trim();b.textContent=label;return true}
function actionIdle(key){const item=TASK_BUTTONS[key];if(!item)return;const b=$(item[0]);if(!b)return;b.disabled=(key==="fastest"&&(!!S.connecting||!!S.pendingMain||!S.regions.length));b.classList.remove("is-busy");b.removeAttribute("aria-busy");b.textContent=item[1]}
function sendTask(selector,label,path,body,key){if(!actionBusy(selector,label))return;requestAnimationFrame(()=>api(path,body).then(r=>{if(!r.ok){actionIdle(key);toast(r.error||"Could not start task")}}))}
function taskDone(key){actionIdle(key)}
function setMainLabel(t){const l=document.querySelector("#bMain .lbl");if(l)l.textContent=t}
function beginMainAction(label){S.pendingMain=label;const b=$("#bMain");if(b){b.disabled=true;b.classList.add("is-busy");setMainLabel(label)}const d=$("#dPow");if(d)d.classList.add("wait");renderDeck()}
$("#bMain").onclick=mainAction;$("#bCp").onclick=()=>{const e=S.exit;if(e&&e.ip){if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(e.ip).then(()=>toast("Copied "+e.ip,true)).catch(()=>toast("Clipboard access was blocked"));else{const x=document.createElement("textarea");x.value=e.ip;document.body.appendChild(x);x.select();try{document.execCommand("copy");toast("Copied "+e.ip,true)}catch(_){toast("Could not copy address")}x.remove()}}};
$("#bFast").onclick=()=>sendTask("#bFast","Comparing servers…","fastest",{},"fastest");$("#bIp").onclick=()=>sendTask("#bIp","Refreshing IP…","ipinfo",{},"ipinfo");
$("#bSpeed").onclick=()=>{setSpeed(0);sendTask("#bSpeed","Measuring speed…","speedtest",{},"speed")};$("#bStream").onclick=()=>sendTask("#bStream","Checking services…","streamcheck",{},"stream");
$("#bNetCheck").onclick=()=>{$("#netResults").innerHTML='<div class="empty-state">Checking router, internet and DNS…</div>';sendTask("#bNetCheck","Checking network…","network_diagnose",{},"network_diagnose")};
$("#bFlushDns").onclick=()=>{if(confirm("Clear Windows' saved website lookups? This does not change your DNS settings."))sendTask("#bFlushDns","Clearing DNS…","flush_dns",{},"flush_dns")};
$("#bValorant").onclick=()=>sendTask("#bValorant","Scanning VALORANT…","valorant_probe",{},"valorant_manual");
$("#bGameCheck").onclick=()=>{const host=$("#gameHost").value.trim();$("#gameResults").innerHTML='<div class="empty-state">Testing endpoint reachability…</div>';sendTask("#bGameCheck","Testing endpoint…","gaming_probe",{host},"gaming")};
$("#bProbe").onclick=()=>sendTask("#bProbe","Probing servers…","probe",{},"probe");$("#bFolder").onclick=()=>api("open_configs",{});$("#bRescan").onclick=()=>{actionBusy("#bRescan","Scanning configs…");api("rescan",{}).then(r=>{actionIdle("rescan");if(!r.ok)toast(r.error||"Rescan failed")})};
$("#bImp").onclick=()=>$("#file").click();
$("#file").onchange=async e=>{const f=e.target.files[0];if(!f)return;const txt=await f.text();const r=await api("import",{name:f.name,content:txt});if(!r.ok)toast(r.error||"import failed");e.target.value=""};
const quit=async d=>{await api("quit",{disconnect:d});if(window.pywebview&&pywebview.api)pywebview.api.close()};
$("#bQuit").onclick=()=>quit(false);$("#bQuitD").onclick=()=>quit(true);
/* The side column shows the status cards first and the selected tab below them: bring the tab into view, or a click
   on Settings/Servers/... seems to do nothing when the cards fill the column. */
function showTabPanel(id){const p=document.getElementById(id),side=p&&p.closest("aside");if(!side)return;
 const top=Math.max(0,side.scrollTop+p.getBoundingClientRect().top-side.getBoundingClientRect().top-8);if(Math.abs(side.scrollTop-top)<4)return;
 side.scrollTo({top,behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"})}
$$("#dock [data-tab]").forEach(b=>b.onclick=()=>{$$("#dock [data-tab]").forEach(x=>x.classList.toggle("a",x===b));$$(".tab").forEach(t=>t.classList.toggle("a",t.id===b.dataset.tab));draw2();renderDet();requestAnimationFrame(()=>showTabPanel(b.dataset.tab))});
$("#serverSearch").oninput=()=>{if(S.regions.length)render()};
$("#serverSort").onchange=()=>render();
$("#onlyFav").onchange=()=>render();
$("#srv").onclick=e=>{const f=e.target.closest("[data-f]");if(f){api("favorite",{name:f.dataset.f});return}const b=e.target.closest("[data-c]");if(b&&!S.pendingMain&&!S.connecting){S.selected=b.dataset.c;beginMainAction("Connecting to "+b.dataset.c+"…");api("connect",{name:b.dataset.c}).then(r=>{if(!r.ok){S.pendingMain="";render();toast(r.error||"Could not connect")}})}};
$("#lastlog").onclick=()=>$("#loglist").classList.toggle("o");
addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();palToggle();return}if(PAL.open||e.target!==document.body)return;if(e.code==="Space"){e.preventDefault();mainAction()}else if("1234".includes(e.key)&&e.key){const b=$$("#dock [data-tab]")[+e.key-1];if(b)b.click()}});
function addLog(l){$("#ll").textContent=l.ts+"  "+l.msg;const d=document.createElement("div");d.className="l-"+l.level;d.textContent=l.ts+"  "+l.msg;const ll=$("#loglist");ll.appendChild(d);while(ll.children.length>150)ll.removeChild(ll.firstChild);ll.scrollTop=ll.scrollHeight;if(l.level==="bad")toast(l.msg)}
const SV={};
function bootMark(id,status,detail){const el=$("#boot"+id);if(!el)return;el.classList.remove("ok","warn","bad","running","off");if(status)el.classList.add(status);el.querySelector("span").textContent=detail||status||"Waiting…";const all=["IP","Speed","Services","Network","Valorant"].map(k=>$("#boot"+k)).filter(Boolean);const finished=all.filter(x=>!x.classList.contains("running")&&(x.classList.contains("ok")||x.classList.contains("warn")||x.classList.contains("bad")||x.classList.contains("off"))).length;$("#bootState").textContent=finished===all.length?"Scan complete":finished+" / "+all.length+" complete"}
function svRender(){$("#svs").innerHTML=Object.values(SV).map(s=>`<div class="sv ${s.level}"><span class="d"></span><span class="n">${esc(s.name)}<div class="t">${esc(s.note)}</div></span><span class="t">${s.ms!=null?s.ms+" ms":""}</span></div>`).join("")||'<div class="note">Press Check to test streaming sites through your current connection.</div>'}
svRender();
applyTheme(getSavedTheme());
function handle(type,p){if(window.NX&&NX.handle(type,p))return;switch(type){
 case"state":applyState(p);break;
 case"log":addLog(p);break;
 case"task_done":taskDone(p.key);break;
 case"health":S.health=p;qbadge();renderDeck();S.rtt.push(p.rtt);if(S.rtt.length>60)S.rtt.shift();$("#mRtt").textContent=p.rtt!=null?p.rtt+" ms":"—";$("#mJit").textContent=p.jitter!=null?p.jitter+" ms":"—";$("#mLoss").textContent=p.loss+"%";draw2();break;
 case"traffic":S.det=p;renderDeck();S.rate=p.rx_bps+p.tx_bps;S.rx.push(p.rx_bps);S.tx.push(p.tx_bps);if(S.rx.length>60){S.rx.shift();S.tx.shift()}$("#mRx").textContent=fmtRate(p.rx_bps);$("#mTx").textContent=fmtRate(p.tx_bps);$("#hRx").textContent="↓ "+fmtRate(p.rx_bps);$("#hTx").textContent="↑ "+fmtRate(p.tx_bps);draw2();trafficWave(p);break;
 case"probe":{const r=S.regions.find(x=>x.name===p.name);if(r)r.ping=p.ping;(S.hist[p.name]=S.hist[p.name]||[]).push(p.ping.rtt);if(S.hist[p.name].length>20)S.hist[p.name].shift();const q=S.pos[p.name];if(q&&ambientOk()){S.ripples.push({x:q.x,y:q.y,t0:performance.now(),c:pc(p.ping)});wake(950)}render();break}
 case"ipinfo":S.exit=p;render();bootMark("IP",p&&p.ip?"ok":"warn",p&&p.ip?p.ip:(p&&p.error?"Lookup unavailable":"Not available"));break;
 case"speed":setSpeed(p.mbps,false);actionBusy("#bSpeed","Measuring speed…");bootMark("Speed","running","Testing…");break;
 case"speed_done":actionIdle("speed");if(p.error){toast("Speed test failed: "+p.error);bootMark("Speed","bad","Test failed")}else{setSpeed(p.mbps,true);bootMark("Speed","ok",p.mbps+" Mbps")}break;
 case"network_diagnose":{const report=p;const bad=(report.issues||[]).some(x=>x.level==="bad"),warn=(report.issues||[]).some(x=>x.level==="warn");bootMark("Network",bad?"bad":warn?"warn":"ok",bad?"Needs attention":warn?"Review suggested":"Looks healthy");$("#netMetrics").innerHTML=[['Router ping',report.gateway_ping&&report.gateway_ping.rtt!=null?report.gateway_ping.rtt+' ms':(report.gateway?'No reply':'Not found')],['Internet ping',report.internet_ping&&report.internet_ping.rtt!=null?report.internet_ping.rtt+' ms':'No reply'],['DNS lookup',report.dns_ok?report.dns_ms+' ms':'Failed']].map(x=>'<div class="m"><small>'+esc(x[0])+'</small><span>'+esc(x[1])+'</span></div>').join('');$("#netResults").innerHTML=(report.issues||[]).map(x=>'<div class="net-issue '+esc(x.level)+'"><b>'+esc(x.title)+'</b><p>'+esc(x.simple)+'</p><p>'+esc(x.impact)+'</p><p class="next"><b>Try this:</b> '+esc(x.suggestion)+'</p></div>').join('');break}
 case"valorant_start":{bootMark("Valorant","running","Scanning regions…");$("#bValorant").disabled=true;$("#valoRows").innerHTML="<div class='empty-state'>Checking all VALORANT regions…</div>";$("#valoSummary").innerHTML="<div class='m'><small>Locations</small><span>"+esc(p.total)+"</span></div><div class='m'><small>Reachable</small><span>Checking…</span></div><div class='m'><small>Best estimate</small><span>—</span></div>";break}
 case"valorant_result":{const q=p;const row=document.createElement("div");row.className="valo-row "+(q.kind==="riot-edge"?"good":"estimate");row.innerHTML="<div><div class='vn'>"+esc(q.region)+" · "+esc(q.name)+"</div><div class='note'>"+esc(q.method||"Pending")+" · "+esc(q.target||"")+"</div></div><div class='vm'>"+(q.rtt==null?"—":esc(q.rtt)+" ms")+"</div><div class='vd'>"+esc(q.note||"")+"</div>";$("#valoRows").appendChild(row);break}
 case"valorant_done":{actionIdle("valorant_manual");const b=p.best;$("#valoSummary").innerHTML="<div class='m'><small>Locations</small><span>"+esc(p.count)+"</span></div><div class='m'><small>Reachable</small><span>"+esc(p.reachable)+"</span></div><div class='m'><small>Best estimate</small><span>"+(b&&b.rtt!=null?esc(b.rtt)+" ms":"—")+"</span></div>";$("#valoFoot").textContent=p.note||"Actual in-game ping can differ.";break}
 case"gaming_probe":{const q=p;$("#gameResults").innerHTML=q.ok?'<div class="net-issue '+(q.loss>=20?'warn':'good')+'"><b>'+esc(q.host)+' · '+(q.rtt==null?'No ping reply':q.rtt+' ms')+'</b><p>Packet loss: '+esc(q.loss)+'%'+(q.jitter!=null?' · Jitter: '+esc(q.jitter)+' ms':'')+'</p><p>'+esc(q.verdict)+'</p><p>Test address: '+esc(q.resolved_ip)+'</p></div>':'<div class="net-issue warn"><b>Could not test this address</b><p>'+esc(q.error||'Check the address')+'</p></div>';break}
 case"fix_result":toast(p.message||'Fix finished',!!p.ok);break;
 case"stream_start":bootMark("Services","running","Checking sites…");Object.keys(SV).forEach(k=>delete SV[k]);SV._=({name:"Testing…",note:"",level:"warn"});svRender();break;
 case"stream":delete SV._;SV[p.id]=p;svRender();break;
 case"stream_done":{const a=Object.values(SV),ok=a.filter(x=>x.level==="ok").length;bootMark("Services",ok===a.length?"ok":ok?"warn":"bad",ok+" / "+a.length+" reachable")}break}}
let startupRequested=false;
function connectSSE(){const es=new EventSource("/events");es.onmessage=e=>{try{const m=JSON.parse(e.data);handle(m.type,m.payload)}catch(_){}};
 es.onopen=()=>api("state").then(s=>{if(s&&s.regions)applyState(s);if(!startupRequested){startupRequested=true;const full=!!(s&&s.settings&&s.settings.startup_checks);(full?["IP","Speed","Services","Network","Valorant"]:["IP","Network"]).forEach(k=>bootMark(k,"running","Starting…"));if(!full)["Speed","Services","Valorant"].forEach(k=>bootMark(k,"off","Off · run it from its tab"));$("#bootState").textContent="Running checks";setTimeout(()=>api("startup_checks",{}),2500)}});
 es.onerror=()=>{$("#pillt").textContent="app offline"}}
let GAUGE_KEY="",GRAF=0;
function gaugeWake(){if(!GRAF)GRAF=requestAnimationFrame(gaugeLoop)}
function gaugeLoop(){GRAF=0;if(document.hidden)return;
 S.speed+=(S.speedTarget-S.speed)*.18;if(Math.abs(S.speedTarget-S.speed)<.05)S.speed=S.speedTarget;
 if(S.speed!==S.speedTarget)gaugeWake();      /* keep going only while the needle moves */
 if(!$("#t1").classList.contains("a"))return;
 const k=S.speed.toFixed(2)+"|"+S.speedMax+"|"+(document.documentElement.dataset.theme||"");if(k===GAUGE_KEY)return;GAUGE_KEY=k;gauge()}
gaugeWake();$$("#dock [data-tab]").forEach(b=>b.addEventListener("click",()=>{GAUGE_KEY="";gaugeWake()}));
document.addEventListener("visibilitychange",()=>{if(!document.hidden){GAUGE_KEY="";gaugeWake()}});
new MutationObserver(()=>{GAUGE_KEY="";gaugeWake()}).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});

function mapStat(){const el=$("#mapStat");
 if(el){const ranked=S.regions.filter(r=>r.ping&&r.ping.rtt!=null).slice().sort((a,b)=>a.ping.rtt-b.ping.rtt);
  el.innerHTML=S.regions.length?"<b>"+S.regions.length+"</b> locations"+(ranked.length?" · best <b>"+esc(ranked[0].name)+"</b> "+ranked[0].ping.rtt+" ms":" · press Fastest to rank"):"No locations yet"}
 const dl=$("#deckLat");if(dl){const h=S.health;dl.textContent=S.connected&&h&&h.rtt!=null?h.rtt+" ms":"";dl.className="deck-lat"+(S.connected&&h&&h.q?" q-"+h.q:"")}}
const _rd=renderDeck;renderDeck=function(){_rd();mapStat()};
function lens(){const a=document.querySelector("#dock [data-tab].a"),l=$("#dockLens");if(!a||!l)return;l.style.width=a.offsetWidth+"px";l.style.height=a.offsetHeight+"px";l.style.top=a.offsetTop+"px";l.style.transform="translateX("+a.offsetLeft+"px)"}
$$("#dock [data-tab]").forEach(b=>b.addEventListener("click",()=>setTimeout(lens,0)));
addEventListener("resize",lens);setTimeout(lens,150);setTimeout(lens,900);setTimeout(lens,2500);
(function(){const tabs=$$("#dock [data-tab]");$("#dock").setAttribute("role","tablist");
 const sync=()=>tabs.forEach(b=>{b.setAttribute("role","tab");b.setAttribute("aria-selected",b.classList.contains("a")?"true":"false")});sync();
 tabs.forEach(b=>b.addEventListener("click",()=>setTimeout(sync,0)));
 const L=(sel,t)=>{const e=$(sel);if(e)e.setAttribute("aria-label",t)};L("#bCp","Copy exit IP address");L("#bIp","Refresh exit IP address");L("#bFast","Connect to the fastest server");L("#bMain","Connect or disconnect")})();
resize();connectSSE();
