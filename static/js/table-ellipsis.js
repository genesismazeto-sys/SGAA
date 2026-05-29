(function(){
  const TABLE_SELECTOR = 'table.table, table.table-progresso, table.db-table';
  const CELL_SELECTOR = 'th, td';
  const GENERIC_ELLIPSIS_SELECTOR = '.ellipsis';
  const SKIP_CELL_SELECTOR = '.actions, .table-empty';
  const HARD_SKIP_SELECTOR = 'input, select, textarea, button, form, .btn, .db-actions-cell';
  let scheduled = false;

  function isElementNode(node){
    return !!node && node.nodeType === Node.ELEMENT_NODE;
  }

  function getCellTarget(cell){
    return cell.querySelector(':scope > .table-cell-ellipsis, :scope > .table-cell-ellipsis-target');
  }

  function getGenericTarget(element){
    return element.querySelector(':scope > .ellipsis-content');
  }

  function shouldSkipCell(cell){
    if (!cell || cell.matches(SKIP_CELL_SELECTOR)) return true;
    if (cell.hasAttribute('colspan') || cell.hasAttribute('rowspan')) return true;
    if (cell.querySelector(HARD_SKIP_SELECTOR)) return true;
    return false;
  }

  function preparePlainTextCell(cell){
    const text = (cell.textContent || '').trim();
    if (!text) return null;

    const wrapper = document.createElement('span');
    wrapper.className = 'table-cell-ellipsis';
    wrapper.textContent = text;
    cell.textContent = '';
    cell.appendChild(wrapper);
    return wrapper;
  }

  function preparePlainTextElement(element){
    const text = (element.textContent || '').trim();
    if (!text) return null;

    const wrapper = document.createElement('span');
    wrapper.className = 'ellipsis-content';
    wrapper.textContent = text;
    element.textContent = '';
    element.appendChild(wrapper);
    return wrapper;
  }

  function prepareSingleChildCell(cell){
    const children = Array.from(cell.children).filter(Boolean);
    if (children.length !== 1) return null;

    const onlyChild = children[0];
    if (!isElementNode(onlyChild)) return null;
    if (onlyChild.matches(HARD_SKIP_SELECTOR)) return null;
    if (onlyChild.querySelector(HARD_SKIP_SELECTOR)) return null;

    onlyChild.classList.add('table-cell-ellipsis-target');
    return onlyChild;
  }

  function prepareCell(cell){
    if (!cell || cell.dataset.ellipsisPrepared === '1' || shouldSkipCell(cell)) return getCellTarget(cell);

    const hasOnlyTextNodes = Array.from(cell.childNodes).every((node) => {
      return node.nodeType === Node.TEXT_NODE || (node.nodeType === Node.COMMENT_NODE);
    });

    let target = null;
    if (hasOnlyTextNodes) {
      target = preparePlainTextCell(cell);
    } else {
      target = prepareSingleChildCell(cell);
    }

    if (target) {
      cell.classList.add('table-ellipsis-cell');
      cell.dataset.ellipsisPrepared = '1';
    }

    return target;
  }

  function shouldSkipGenericElement(element){
    if (!element) return true;
    if (element.dataset.ellipsisPrepared === '1') return false;
    if (element.querySelector(HARD_SKIP_SELECTOR)) return true;
    return false;
  }

  function prepareGenericEllipsisElement(element){
    if (!element || shouldSkipGenericElement(element)) return getGenericTarget(element);

    const hasOnlyTextNodes = Array.from(element.childNodes).every((node) => {
      return node.nodeType === Node.TEXT_NODE || node.nodeType === Node.COMMENT_NODE;
    });

    if (!hasOnlyTextNodes) return getGenericTarget(element);

    const target = preparePlainTextElement(element);
    if (target) {
      element.dataset.ellipsisPrepared = '1';
    }
    return target;
  }

  function hasCustomTooltip(element){
    return !!element && !!element.closest?.('[data-ptip], [data-ui-tooltip]');
  }

  function syncOverflowTitle(cell, target){
    if (!cell || !target) return;

    if (hasCustomTooltip(cell) || hasCustomTooltip(target)) {
      if (target.dataset.autoTitle === '1') {
        target.removeAttribute('title');
        delete target.dataset.autoTitle;
      }
      return;
    }

    if (cell.hasAttribute('title') || target.hasAttribute('title')) return;

    const text = (target.textContent || '').trim();
    if (!text) return;

    const isOverflowing = Math.ceil(target.scrollWidth) > Math.ceil(target.clientWidth + 1);
    if (isOverflowing) {
      target.title = text;
      target.dataset.autoTitle = '1';
      return;
    }

    if (target.dataset.autoTitle === '1') {
      target.removeAttribute('title');
      delete target.dataset.autoTitle;
    }
  }

  function applyTableEllipsis(root){
    const scope = root && root.querySelectorAll ? root : document;
    const cells = scope.querySelectorAll(`${TABLE_SELECTOR} ${CELL_SELECTOR}`);
    cells.forEach((cell) => {
      const target = prepareCell(cell);
      if (target) syncOverflowTitle(cell, target);
    });

    const genericElements = scope.querySelectorAll(GENERIC_ELLIPSIS_SELECTOR);
    genericElements.forEach((element) => {
      if (element.matches(CELL_SELECTOR)) return;
      const target = prepareGenericEllipsisElement(element);
      if (target) syncOverflowTitle(element, target);
    });
  }

  function scheduleApply(root){
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(() => {
      scheduled = false;
      applyTableEllipsis(root);
    });
  }

  window.applyTableEllipsis = scheduleApply;

  document.addEventListener('DOMContentLoaded', () => {
    scheduleApply(document);

    if (typeof MutationObserver !== 'function' || !document.body) return;
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!isElementNode(node)) continue;
          if (node.matches?.(TABLE_SELECTOR) || node.querySelector?.(TABLE_SELECTOR) || node.matches?.(CELL_SELECTOR)) {
            scheduleApply(node);
            return;
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', () => scheduleApply(document), { passive: true });
  });
})();