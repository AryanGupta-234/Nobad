/* Moved out of products/vpn/index.html so the site's Content-Security-Policy needs no 'unsafe-inline'. */
(()=>{const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
const play=c=>{const ls=[...c.querySelectorAll('.ln')];ls.forEach((l,i)=>setTimeout(()=>l.classList.add('on'),reduce?0:i*420));const m=c.querySelector('.meter i');if(m)setTimeout(()=>{m.style.width=m.dataset.w},reduce?0:ls.length*420)};
if(!('IntersectionObserver' in window)){document.querySelectorAll('.rv').forEach(e=>e.classList.add('in'));const c=document.getElementById('niConsole');if(c)play(c);return}
const io=new IntersectionObserver(es=>es.forEach(e=>{if(!e.isIntersecting)return;e.target.classList.add('in');if(e.target.id==='niConsole')play(e.target);io.unobserve(e.target)}),{threshold:.18});
document.querySelectorAll('.rv').forEach(e=>io.observe(e));})();
