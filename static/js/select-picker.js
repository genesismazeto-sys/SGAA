/* Keys inside an open select picker stay inside it.

   components/select.css opens a single-choice <select> as an in-page picker
   where the customizable select exists. The browser's native popup swallows
   every key while it is open; the in-page picker lets the key event reach the
   page, so the Escape that closes the list also reached the modal and menu
   handlers listening on the document and closed the surface around it.

   While a picker is open its keys stop at the document, in the capture phase,
   before any page listener. The browser's own handling (close on Escape,
   arrows, Enter, type-ahead) is the event's default action and still runs.
   Without the customizable select there is no in-page picker and this does
   nothing. */
(function () {
  if (!window.CSS || !CSS.supports || !CSS.supports('appearance', 'base-select')) return;

  function insideOpenPicker(target) {
    var select = target && target.closest ? target.closest('select') : null;
    return !!select && select.matches(':open');
  }

  ['keydown', 'keypress', 'keyup'].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (insideOpenPicker(event.target)) event.stopPropagation();
    }, true);
  });
})();
