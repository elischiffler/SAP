'use strict';
// Ambient motion follows window visibility and focus; reduced motion is honored.
(() => {
 function update() {
  document.documentElement.dataset.windowActive = String(!document.hidden && document.hasFocus());
  document.dispatchEvent(new CustomEvent('paiger:motionchange'));
 }
 document.addEventListener('visibilitychange',update);
 window.addEventListener('focus',update);
 window.addEventListener('blur',update);
 update();
})();
