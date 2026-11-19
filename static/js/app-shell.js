/* The shell's navigation drawer below 768px (MOBILE-01).

   The header's menu button opens and closes the sidebar, which the phone
   layout in modern-style.css turns into a drawer. While it is open the
   content behind it is inert; Escape, the scrim or the button close it and
   give the focus back to the button, and choosing a link closes it too.
   From 768px up the button is not displayed and nothing here changes the
   page: a drawer left open when the window widens is closed. */
(function(){
  const layout = document.querySelector('.app-layout');
  const toggle = document.getElementById('app-menu-toggle');
  const sidebar = document.getElementById('app-sidebar');
  if (!layout || !toggle || !sidebar) return;
  const backdrop = document.getElementById('app-nav-backdrop');
  const content = document.getElementById('conteudo');
  const narrow = window.matchMedia('(max-width: 767.98px)');

  const isOpen = () => layout.classList.contains('is-nav-open');

  function setOpen(open, focus){
    layout.classList.toggle('is-nav-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (content) content.inert = open;
    if (open && focus){
      const current = sidebar.querySelector('.sidebar-link.active, .sidebar-link[aria-current="page"]');
      (current || sidebar.querySelector('a, button'))?.focus({ preventScroll: true });
    }
  }

  function close(returnFocus){
    if (!isOpen()) return;
    setOpen(false, false);
    if (returnFocus) toggle.focus();
  }

  toggle.addEventListener('click', () => {
    if (isOpen()) close(true);
    else if (narrow.matches) setOpen(true, true);
  });
  backdrop?.addEventListener('click', () => close(true));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) close(true);
  });
  sidebar.addEventListener('click', (event) => {
    if (event.target.closest('a')) close(false);
  });
  const widened = () => { if (!narrow.matches) close(false); };
  if (narrow.addEventListener) narrow.addEventListener('change', widened);
  else if (narrow.addListener) narrow.addListener(widened);
  // A page restored from the back/forward cache comes back closed.
  window.addEventListener('pageshow', () => close(false));
})();
