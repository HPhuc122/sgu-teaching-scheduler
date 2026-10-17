// Apply before first paint; light is the default.
(() => {
  let theme = 'light';
  try { if (localStorage.getItem('uctp-theme') === 'dark') theme = 'dark'; } catch (_) {}
  document.documentElement.dataset.theme = theme;
})();
