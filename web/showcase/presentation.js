'use strict';
(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const tabs = [...document.querySelectorAll('button[data-slide]')];
  const main = document.getElementById('main');
  const announcement = document.getElementById('slide-announcement');
  const product = document.getElementById('live-product');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let index = 0, transition, outgoing, departure;
  function clearTransition() {
    transition?.cancel(); departure?.cancel(); outgoing?.remove();
    transition = departure = outgoing = null;
  }
  function showSlide(requested, {announce = true, writeHash = true} = {}) {
    const target = Math.max(0, Math.min(slides.length - 1, requested));
    if (announce && target === index) return;
    const animate = announce && !reduced.matches;
    document.dispatchEvent(new CustomEvent('sap:slidewillchange', {detail:{animate,from:slides[index].id,to:slides[target].id}}));
    const old = slides[index];
    const direction = target > index ? 1 : -1;
    const paintedTransform = getComputedStyle(old).transform;
    const movingFocus = old.contains(document.activeElement) || (target === 0 && document.activeElement.closest('.wordmark'));
    clearTransition();
    if (animate) {
      outgoing = old.cloneNode(true);
      outgoing.classList.remove('slide');
      outgoing.classList.add('slide-departure');
      outgoing.removeAttribute('id');
      outgoing.removeAttribute('aria-labelledby');
      outgoing.removeAttribute('role');
      outgoing.removeAttribute('tabindex');
      outgoing.setAttribute('aria-hidden', 'true');
      outgoing.inert = true;
      // Preserve ID-specific typography without duplicate IDs or interactive copies.
      const originals = old.querySelectorAll('[id]');
      outgoing.querySelectorAll('[id]').forEach((el,i) => {
        if (/^H[1-6]$/.test(el.tagName)) el.style.fontSize = getComputedStyle(originals[i]).fontSize;
        el.removeAttribute('id');
      });
      outgoing.style.top = `${old.offsetTop}px`;
      outgoing.style.width = `${old.clientWidth}px`;
      outgoing.style.height = `${old.clientHeight}px`;
      outgoing.style.transform = paintedTransform;
      main.append(outgoing);
      outgoing.scrollTop = old.scrollTop;
    }
    index = target;
    const active = slides[index];
    slides.forEach(slide => { slide.hidden = slide !== active; });
    const slot = active.querySelector('.visual-slot');
    if (slot) slot.append(product);
    tabs.forEach(tab => {
      if (tab.dataset.slide === active.id) tab.setAttribute('aria-current', 'step');
      else tab.removeAttribute('aria-current');
    });
    active.scrollTop = 0;
    main.dataset.slide = active.id;
    document.getElementById('slide-topic').textContent = active.id === 'intro' ? '' : `${String(index).padStart(2, '0')} / ${active.dataset.kicker}`;
    if (writeHash) history.replaceState(null, '', `#${active.id}`);
    if (announce) announcement.textContent = `Slide ${index + 1} of ${slides.length}: ${active.dataset.title}`;
    if (movingFocus) active.querySelector('h1,h2').focus({preventScroll:true});
    document.dispatchEvent(new CustomEvent('sap:slidechange', {detail:{index,id:active.id,animate}}));
    if (animate) {
      const distance = main.clientWidth;
      const timing = {duration:650, easing:'cubic-bezier(.22,.8,.22,1)'};
      transition = active.animate([
        {transform:`translateX(${direction*distance}px)`}, {transform:'translateX(0)'}
      ], timing);
      const leaving = outgoing;
      departure = leaving.animate([
        {transform:paintedTransform === 'none' ? 'translateX(0)' : paintedTransform},
        {transform:`translateX(${-direction*distance}px)`}
      ], timing);
      departure.onfinish = () => { leaving.remove(); if(outgoing === leaving) outgoing = null; };
    }
  }
  document.querySelectorAll('[data-next]').forEach(button => button.addEventListener('click', () => showSlide(index + 1)));
  tabs.forEach(tab => tab.addEventListener('click', () => showSlide(slides.findIndex(slide => slide.id === tab.dataset.slide))));
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
        || document.querySelector('dialog[open]')
        || event.target.closest('input,select,textarea,[contenteditable="true"],[role="slider"],[role="textbox"]')) return;
    // Once presenting, the header logo is the only control that returns to Intro.
    const first = index === 0 ? 0 : 1;
    const target = {ArrowRight:index+1, ArrowLeft:Math.max(first,index-1), PageDown:index+1, PageUp:Math.max(first,index-1), Home:first, End:slides.length-1}[event.key];
    if (target === undefined) return;
    event.preventDefault();
    showSlide(target);
  });
  const aliases = {'#in-use':'#problem', '#prototype':'#product'};
  const routeHash = () => aliases[location.hash] || location.hash;
  function fromHash() {
    const requested = slides.findIndex(slide => `#${slide.id}` === routeHash());
    if (requested >= 0) showSlide(requested, {writeHash:Boolean(aliases[location.hash])});
  }
  window.addEventListener('hashchange', fromHash);
  reduced.addEventListener('change', () => { if (reduced.matches) clearTransition(); });
  window.addEventListener('resize', clearTransition);
  document.addEventListener('visibilitychange', () => { if(document.hidden) clearTransition(); });
  const initial = slides.findIndex(slide => `#${slide.id}` === routeHash());
  showSlide(initial >= 0 ? initial : 0, {announce:false,writeHash:Boolean(aliases[location.hash])});
})();
