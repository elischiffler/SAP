'use strict';
// Short editorial entrances, not simulated live device state. No loops or audio.
(() => {
 const reduced = matchMedia('(prefers-reduced-motion: reduce)');
 let animations = [];
 function stop() { animations.forEach(a => a.cancel()); animations = []; }
 function enter() {
  stop();
  if (reduced.matches || document.hidden) return;
  const active = document.querySelector('.slide:not([hidden])');
  const reveal = (el, delay = 0) => animations.push(el.animate(
   [{opacity:0,transform:'translateY(15px)'},{opacity:1,transform:'translateY(0)'}],
   {duration:650,delay,easing:'cubic-bezier(.16,1,.3,1)',fill:'backwards'}));
  active.querySelectorAll('.slide-copy h1,.slide-copy h2,.comparison-heading,.pricing-intro').forEach(el=>reveal(el,80));
  active.querySelectorAll('.product-steps li,.comparison-name,.comparison-action,.first-user-plan,.build-estimate').forEach((el,i)=>reveal(el,160+i*100));
  active.querySelectorAll('.screen-bars rect').forEach((el,i)=>{
   el.style.transformBox='fill-box'; el.style.transformOrigin='center bottom';
   animations.push(el.animate([{transform:'scaleY(.04)'},{transform:'scaleY(1)'}],
    {duration:850,delay:200+i*65,easing:'cubic-bezier(.16,1,.3,1)',fill:'backwards'}));
  });
  active.querySelectorAll('.survey-bar').forEach((el,i)=>{
   animations.push(el.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],
    {duration:850,delay:150+i*75,easing:'cubic-bezier(.16,1,.3,1)',fill:'backwards'}));
  });
 }
 document.addEventListener('sap:slidechange',enter);
 document.addEventListener('visibilitychange',stop);
 reduced.addEventListener('change',stop);
 window.addEventListener('pagehide',stop);
 enter();
})();
