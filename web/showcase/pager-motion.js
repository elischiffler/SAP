'use strict';
// One visual travels between the existing layout anchors. Original images keep
// their accessible descriptions; the temporary, decorative layer has no controls.
(() => {
  const main = document.getElementById('main');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const flight = document.createElement('div');
  flight.className = 'pager-flight';
  flight.hidden = true;
  flight.setAttribute('aria-hidden', 'true');
  const image = document.createElement('img');
  image.src = document.querySelector('[data-pager]').src;
  image.alt = '';
  image.width = image.height = 1254;
  const phoneAnchor = main.querySelector('[data-phone-transition]');
  const phone = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  phone.classList.add('flight-phone');
  phone.setAttribute('aria-hidden', 'true');
  // Use the exact illustration geometry, isolated in a square flight layer.
  // Source geometry is measured only while its slide is visible (Safari-safe).
  function preparePhone() {
    const box = phoneAnchor.getBBox();
    if (!box.width || !box.height) return;
    const size = Math.max(box.width, box.height);
    phone.setAttribute('viewBox', `${box.x + (box.width-size)/2} ${box.y + (box.height-size)/2} ${size} ${size}`);
    const copy = phoneAnchor.cloneNode(true);
    copy.removeAttribute('transform');
    copy.removeAttribute('data-phone-transition');
    copy.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    phone.replaceChildren(copy);
  }
  flight.append(phone, image);
  main.append(flight);
  const axes = ['x', 'y', 'size', 'angle', 'mix'];
  let state, target, velocity, frame = 0, lastTime = 0, settleAfter = 0, start;
  function measure() {
    const anchor = main.querySelector('.slide:not([hidden]) [data-pager]');
    if (!anchor) {
      if (phoneAnchor.closest('.slide').hidden) return null;
      preparePhone();
      const box = phoneAnchor.getBBox(), matrix = phoneAnchor.getScreenCTM();
      if (!matrix || !box.height) return null;
      const center = new DOMPoint(box.x + box.width/2, box.y + box.height/2).matrixTransform(matrix);
      const stage = main.getBoundingClientRect();
      return {x:center.x-stage.left,y:center.y-stage.top,
        size:Math.max(box.width,box.height)*Math.hypot(matrix.a,matrix.b),
        angle:Math.atan2(matrix.b,matrix.a)*180/Math.PI,mix:0};
    }
    const box = anchor.getBoundingClientRect(), stage = main.getBoundingClientRect();
    const style = getComputedStyle(anchor);
    // Object-fit: contain centers the square asset inside potentially rectangular
    // image boxes. Measure its actual painted square, not a rotated bounding box.
    return {x:box.left + box.width / 2 - stage.left,
      y:box.top + box.height / 2 - stage.top,
      size:Math.min(parseFloat(style.width), parseFloat(style.height)),
      angle:Number(anchor.dataset.pagerAngle || 0),mix:1};
  }
  function paint() {
    const blend = Math.max(0, Math.min(1, state.mix));
    image.style.opacity = blend;
    phone.style.opacity = 1 - blend;
    flight.style.transform = `translate3d(${state.x}px,${state.y}px,0) rotate(${state.angle}deg) scale(${Math.max(1,state.size)/1000}) translate(-50%,-50%)`;
  }
  function finish() {
    cancelAnimationFrame(frame);
    frame = 0;
    flight.hidden = true;
    main.classList.remove('pager-in-transit');
    state = target = velocity = null;
  }
  function tick(time) {
    const dt = Math.min((time - lastTime) / 1000, 0.04);
    lastTime = time;
    const omega = target.mix !== start?.mix ? 11 : 18, decay = Math.exp(-omega * dt);
    let settled = true;
    for (const axis of axes) {
      const offset = state[axis] - target[axis];
      const impulse = velocity[axis] + omega * offset;
      state[axis] = target[axis] + (offset + impulse * dt) * decay;
      velocity[axis] = (velocity[axis] - omega * impulse * dt) * decay;
      if (Math.abs(state[axis] - target[axis]) > 0.08 || Math.abs(velocity[axis]) > 0.5) settled = false;
    }
    paint();
    if (settled && time >= settleAfter) finish();
    else frame = requestAnimationFrame(tick);
  }
  document.addEventListener('sap:slidewillchange', event => {
    start = event.detail.animate && !reduced.matches ? (state || measure()) : null;
  });
  document.addEventListener('sap:slidechange', event => {
    if (!event.detail.animate || reduced.matches || document.hidden || !start) { finish(); return; }
    target = measure();
    settleAfter = performance.now() + 650;
    if (!target || target.size <= 0) { finish(); return; }
    if (!state) {
      state = {...start};
      velocity = {x:0,y:0,size:0,angle:0,mix:0};
    }
    main.classList.add('pager-in-transit');
    flight.hidden = false;
    paint();
    // Retarget in place: preserve current position AND velocity, including when
    // arrow keys reverse or skip slides. Navigation never waits for this loop.
    if (!frame) { lastTime = performance.now(); frame = requestAnimationFrame(tick); }
  });
  // Layout or scroll changes should restore the real, correctly clipped image.
  window.addEventListener('resize', finish);
  main.addEventListener('scroll', () => {
    if (!frame) return;
    const now = measure();
    if (!now || axes.some(axis => Math.abs(now[axis] - target[axis]) > 1)) finish();
  }, true);
  reduced.addEventListener('change', () => { if (reduced.matches) finish(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) finish(); });
  window.addEventListener('pagehide', finish);
})();
