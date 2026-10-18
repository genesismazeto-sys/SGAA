// Indeferir decision dialog (templates/components/rejection_decision_dialog.html).
// window.chooseRejectionOutcome() opens it and resolves with the status the
// administrator chose -- 'Devolvida' (send back for correction) or
// 'Indeferida' (definitive) -- or null when the dialog is cancelled, in which
// case the caller sends nothing. Escape and the backdrop cancel; while it is
// open, Escape never reaches the page underneath (the Requisições modal closes
// itself on Escape).
(function(){
  let pending = null;

  function dialog(){ return document.getElementById('rejection-decision-dialog'); }

  function finish(choice){
    const overlay = dialog();
    if (!overlay || !pending) return;
    const { resolve, returnFocus } = pending;
    pending = null;
    overlay.hidden = true;
    window.removeEventListener('keydown', onKeydown, true);
    returnFocus?.focus?.();
    resolve(choice || null);
  }

  function onKeydown(event){
    if (event.key !== 'Escape' || !pending) return;
    event.preventDefault();
    event.stopPropagation();
    finish(null);
  }

  document.addEventListener('click', (event)=>{
    const overlay = dialog();
    if (!overlay || overlay.hidden || !pending) return;
    if (event.target === overlay){ finish(null); return; }
    const button = event.target.closest('#rejection-decision-dialog [data-rejection-choice]');
    if (button) finish(button.getAttribute('data-rejection-choice'));
  });

  window.chooseRejectionOutcome = function(){
    const overlay = dialog();
    if (!overlay) return Promise.resolve(null);
    if (pending) finish(null);
    return new Promise((resolve)=>{
      pending = { resolve, returnFocus: document.activeElement };
      overlay.hidden = false;
      window.lucide?.createIcons?.();
      window.addEventListener('keydown', onKeydown, true);
      overlay.querySelector('[data-rejection-choice=""]')?.focus();
    });
  };
})();
