'use strict';
(() => {
 const opener = document.getElementById('view-survey');
 const dialog = document.getElementById('survey-dialog');
 opener.addEventListener('click', () => {
  dialog.showModal();
  dialog.scrollTop = 0;
  dialog.querySelector('.survey-close').focus({preventScroll:true});
 });
 dialog.querySelector('.survey-close').addEventListener('click', () => dialog.close());
 dialog.addEventListener('close', () => opener.focus({preventScroll:true}));
 dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const box = dialog.getBoundingClientRect();
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
 });
 dialog.addEventListener('keydown', event => {
  if (event.key !== 'Tab') return;
  const items = [...dialog.querySelectorAll('button,a[href]')].filter(el=>!el.disabled && el.getClientRects().length);
  const i = items.indexOf(document.activeElement);
  const next = event.shiftKey ? (i <= 0 ? items.length-1 : i-1) : (i+1)%items.length;
  event.preventDefault(); items[next].focus();
 });
})();
