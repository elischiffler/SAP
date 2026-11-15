'use strict';
// Separate, interruptible flights let the stacked intro lockup become a header.
(() => {
 const reduced = matchMedia('(prefers-reduced-motion: reduce)');
 const header = [...document.querySelector('.site-header .wordmark').children];
 const intro = [document.querySelector('.intro-symbol'),document.getElementById('intro-title')];
 let items = [], source, frame, previous = 0;
 const bounds = el => {
  const r = el.getBoundingClientRect();
  return [r.x,r.y,r.width,r.height];
 };
 function finish() {
  cancelAnimationFrame(frame);
  items.forEach(item => item.node.remove());
  items = []; source = null; previous = 0;
  document.documentElement.classList.remove('brand-in-transit');
 }
 function paint(item) {
  const [x,y,w,h] = item.value;
  item.node.style.transform = `translate(${x}px,${y}px) scale(${w/item.width},${h/item.height})`;
 }
 function tick(now) {
  const dt = Math.min((now-previous)/1000 || 1/60, .032);
  previous = now;
  let settled = true;
  items.forEach(item => {
   // Exact critically damped spring integration preserves velocity on retarget.
   item.value.forEach((value,i) => {
    const delta = value-item.target[i], c = item.velocity[i]+12*delta;
    item.value[i] = item.target[i]+(delta+c*dt)*Math.exp(-12*dt);
    item.velocity[i] = (item.velocity[i]-12*c*dt)*Math.exp(-12*dt);
    if(Math.abs(item.value[i]-item.target[i])>.15 || Math.abs(item.velocity[i])>1) settled=false;
   });
   paint(item);
  });
  if(settled) finish(); else frame=requestAnimationFrame(tick);
 }
 document.addEventListener('sap:slidewillchange', event => {
  const {from,to,animate} = event.detail;
  if(!animate || reduced.matches) {finish();return;}
  if(from !== 'intro' && to !== 'intro' && !items.length) return;
  source = (from === 'intro' ? intro : header).map(bounds);
 });
 document.addEventListener('sap:slidechange', event => {
  if(!source) return;
  const destinations = (event.detail.id === 'intro' ? intro : header).map(bounds);
  if(!items.length) {
   items = header.map((original,i) => {
    const node = original.cloneNode(true), style = getComputedStyle(original);
    const [, ,width,height] = bounds(original);
    node.className='brand-traveler';
    node.setAttribute('aria-hidden','true');
    node.removeAttribute('id');
    for(const prop of ['font-family','font-size','font-weight','letter-spacing','line-height','color'])
     node.style.setProperty(prop,style.getPropertyValue(prop));
    Object.assign(node.style,{width:`${width}px`,height:`${height}px`,margin:'0',padding:'0',whiteSpace:'nowrap'});
    document.body.append(node);
    return {node,width,height,value:source[i],velocity:[0,0,0,0],target:destinations[i]};
   });
   document.documentElement.classList.add('brand-in-transit');
  }
  items.forEach((item,i)=>{item.target=destinations[i];paint(item);});
  source=null;
  cancelAnimationFrame(frame);previous=performance.now();frame=requestAnimationFrame(tick);
 });
 window.addEventListener('resize',finish);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)finish();});
 reduced.addEventListener('change',()=>{if(reduced.matches)finish();});
})();
