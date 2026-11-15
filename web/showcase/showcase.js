'use strict';
// Local product preview and mock checkout. No API calls or persistence.
(() => {
 const $ = selector => document.querySelector(selector);
 // Native modal provides Escape dismissal, inert background, and focus containment.
 const dialog = $('#shop-dialog');
 let opener;
 const selection = () => ({ finish: 'Graphite', quantity: Number($('#quantity').value) });
 const unitPrice = 59;
 const money = (quantity) => `$${unitPrice * quantity} USD`;
 function showPane(id) {
  const heading = $(`#${id} h2`);
  heading.tabIndex = -1;
  dialog.setAttribute('aria-labelledby', heading.id || (heading.id = `${id}-heading`));
  heading.focus({preventScroll:true});
  dialog.scrollTop = 0;
 }
 document.querySelectorAll('[data-shop]').forEach(button => button.addEventListener('click', () => {
  opener = button;
  dialog.showModal();
  showPane('shop-selection');
 }));
 $('#shop-dialog .close-dialog').addEventListener('click', () => dialog.close());
 dialog.addEventListener('close', () => opener?.focus({preventScroll:true}));
 dialog.addEventListener('keydown', event => {
  if (event.key !== 'Tab') return;
  const focusable = [...dialog.querySelectorAll('button, a[href], input, select')].filter(el => el.getClientRects().length && !el.disabled && (el.type !== 'radio' || el.checked));
  const current = focusable.indexOf(document.activeElement);
  const next = event.shiftKey ? (current <= 0 ? focusable.length - 1 : current - 1) : (current + 1) % focusable.length;
  event.preventDefault();
  focusable[next].focus();
 });
 dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const r = dialog.getBoundingClientRect();
  if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
 });
 $('#quantity').addEventListener('change', () => { $('#order-total').textContent = money(selection().quantity); });
})();
