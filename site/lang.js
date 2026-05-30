// TraceSchema — language toggle (TR / EN)
// Sets data-lang on <html> and persists to localStorage.
function setLang(lang) {
  document.documentElement.setAttribute('data-lang', lang);
  localStorage.setItem('ts-lang', lang);
  document.querySelectorAll('.lang-btn').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });
}

(function () {
  var saved = localStorage.getItem('ts-lang') || 'tr';
  document.documentElement.setAttribute('data-lang', saved);
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.lang === saved);
    });
  });
})();
