// Font previews are URL-local; no storage or network requests are needed.
(() => {
 const font = new URLSearchParams(location.search).get('font');
 if (['manrope', 'inter', 'space'].includes(font)) document.documentElement.dataset.brandFont = font;
})();
