'use strict';
// Randomized illustrative routing, active only on the focused product slide.
// No APIs, audio, or claims of live device state.
(() => {
 const slide = document.getElementById('product');
 const diagram = slide.querySelector('.product-flow');
 const reduced = matchMedia('(prefers-reduced-motion: reduce)');
 let animations = [], timer;
 const random = (min,max) => min + Math.random()*(max-min);
 const allowed = () => !slide.hidden && !document.hidden && document.hasFocus() && !reduced.matches && document.documentElement.dataset.motionPaused !== 'true';
 function stop() { clearTimeout(timer); animations.forEach(a=>a.cancel()); animations=[]; }
 function cycle() {
  stop();
  if (!allowed()) return;
  const animate = (selector,frames,duration,delay) => animations.push((typeof selector === 'string' ? diagram.querySelector(selector) : selector).animate(frames,
   {duration,delay,easing:'cubic-bezier(.3,.1,.3,1)',fill:'none'}));
  let incomingEnd = 0;
  for (const [selector,y] of [['.flow-noise-a',25],['.flow-important',0],['.flow-noise-b',-25]]) {
   const duration=random(800,1300),delay=random(0,550);
   incomingEnd=Math.max(incomingEnd,duration+delay);
   animate(selector,[{opacity:0,transform:'translate(0,0)',offset:0},
    {opacity:1,transform:'translate(10px,0)',offset:.12},
    {opacity:1,transform:`translate(102px,${y}px)`,offset:.78},
    {opacity:0,transform:`translate(122px,${y}px)`,offset:1}],duration,delay);
  }
  const outputDelay=incomingEnd+random(150,400),outputDuration=random(800,1200);
  animate('.flow-selected',[{opacity:0,transform:'translateX(0)',offset:0},
   {opacity:1,transform:'translateX(10px)',offset:.15},
   {opacity:1,transform:'translateX(70px)',offset:.85},
   {opacity:0,transform:'translateX(80px)',offset:1}],outputDuration,outputDelay);
  const arrivalTime=outputDelay+outputDuration;
  const pressTime=arrivalTime+450;
  animate('.flow-button',[{transform:'scale(1)',fill:'#41493b',offset:0},
   {transform:'translateY(1px) scale(.83)',fill:'#252b23',offset:.4},
   {transform:'translateY(1px) scale(.83)',fill:'#252b23',offset:.65},
   {transform:'scale(1)',fill:'#41493b',offset:1}],460,pressTime);
  animate('.flow-press',[{opacity:0,transform:'scale(1.15)',offset:0},
   {opacity:.85,transform:'scale(.9)',offset:.4},
   {opacity:0,transform:'scale(1.18)',offset:1}],600,pressTime);
  const playbackTime=pressTime+460;
  for(let pulse=0;pulse<3;pulse++) {
   diagram.querySelectorAll('.flow-sound path').forEach((wave,index)=>{
    animate(wave,[{opacity:0},{opacity:.9,offset:.3},{opacity:0}],750,
     playbackTime+pulse*650+index*130);
   });
  }
  timer=setTimeout(cycle,playbackTime+2400+random(600,1400));
 }
 function resume(delay=0) {stop();if(allowed())timer=setTimeout(cycle,delay);}
 document.addEventListener('sap:slidewillchange',stop);
 document.addEventListener('sap:slidechange',()=>resume(700));
 document.addEventListener('paiger:motionchange',()=>resume());
 reduced.addEventListener('change',()=>resume());
 window.addEventListener('pagehide',stop);
 resume(700);
})();
