(function () {
  const TOOLTIP_SELECTOR = '[title],[data-ui-tooltip],[data-ptip]';
  const tooltipId = 'ui-tooltip-root';
  let activeTrigger = null;
  let tooltipEl = null;

  function collectTriggers(root) {
    if (!root || !(root instanceof Element || root instanceof Document || root instanceof DocumentFragment)) {
      return [];
    }

    const triggers = [];
    if (root instanceof Element && root.matches(TOOLTIP_SELECTOR)) {
      triggers.push(root);
    }

    if ('querySelectorAll' in root) {
      triggers.push(...root.querySelectorAll(TOOLTIP_SELECTOR));
    }

    return triggers;
  }

  function ensureTooltip() {
    if (tooltipEl && document.body.contains(tooltipEl)) {
      return tooltipEl;
    }

    tooltipEl = document.getElementById(tooltipId);
    if (!tooltipEl) {
      tooltipEl = document.createElement('div');
      tooltipEl.id = tooltipId;
      tooltipEl.className = 'ui-tooltip';
      tooltipEl.hidden = true;
      tooltipEl.setAttribute('role', 'tooltip');
      document.body.appendChild(tooltipEl);
    }

    return tooltipEl;
  }

  function primeTrigger(trigger) {
    if (!trigger) {
      return;
    }

    const legacyTooltip = (trigger.dataset.ptip || '').trim();
    if (legacyTooltip && !trigger.dataset.uiTooltip) {
      trigger.dataset.uiTooltip = legacyTooltip;
    }

    const nativeTitle = trigger.getAttribute('title');
    if (nativeTitle) {
      if (!trigger.dataset.uiTooltip) {
        trigger.dataset.uiTooltip = nativeTitle;
      }
      trigger.removeAttribute('title');
    }
  }

  function getTooltipText(trigger) {
    if (!trigger) {
      return '';
    }

    primeTrigger(trigger);
    return (trigger.dataset.uiTooltip || trigger.dataset.ptip || '').trim();
  }

  function primeExistingTriggers(root) {
    collectTriggers(root).forEach(primeTrigger);
  }

  function findTrigger(target) {
    if (!(target instanceof Element)) {
      return null;
    }

    return target.closest(TOOLTIP_SELECTOR);
  }

  function positionTooltip(trigger) {
    const tooltip = ensureTooltip();
    if (!trigger || tooltip.hidden) {
      return;
    }

    const rect = trigger.getBoundingClientRect();
    const spacing = 6;
    const viewportPadding = 8;
    const tooltipRect = tooltip.getBoundingClientRect();

    let top = rect.top - tooltipRect.height - spacing;
    if (top < viewportPadding) {
      top = rect.bottom + spacing;
    }

    let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
    const maxLeft = window.innerWidth - tooltipRect.width - viewportPadding;
    left = Math.min(Math.max(left, viewportPadding), Math.max(viewportPadding, maxLeft));

    tooltip.style.top = `${Math.round(top)}px`;
    tooltip.style.left = `${Math.round(left)}px`;
  }

  function showTooltip(trigger) {
    const text = getTooltipText(trigger);
    if (!text) {
      hideTooltip();
      return;
    }

    const tooltip = ensureTooltip();
    activeTrigger = trigger;
    tooltip.textContent = text;
    tooltip.hidden = false;
    tooltip.classList.add('is-visible');
    positionTooltip(trigger);
  }

  function hideTooltip() {
    if (!tooltipEl) {
      activeTrigger = null;
      return;
    }

    activeTrigger = null;
    tooltipEl.hidden = true;
    tooltipEl.classList.remove('is-visible');
    tooltipEl.textContent = '';
  }

  function handleMouseOver(event) {
    const trigger = findTrigger(event.target);
    if (!trigger || trigger === activeTrigger) {
      return;
    }

    showTooltip(trigger);
  }

  function handleMouseOut(event) {
    if (!activeTrigger) {
      return;
    }

    const fromTrigger = findTrigger(event.target);
    if (fromTrigger !== activeTrigger) {
      return;
    }

    const nextTrigger = findTrigger(event.relatedTarget);
    if (nextTrigger === activeTrigger) {
      return;
    }

    hideTooltip();
  }

  function handleFocusIn(event) {
    const trigger = findTrigger(event.target);
    if (!trigger) {
      return;
    }

    showTooltip(trigger);
  }

  function handleFocusOut(event) {
    if (!activeTrigger) {
      return;
    }

    const nextTrigger = findTrigger(event.relatedTarget);
    if (nextTrigger === activeTrigger) {
      return;
    }

    hideTooltip();
  }

  function initTooltips() {
    ensureTooltip();
    primeExistingTriggers(document);

    document.addEventListener('mouseover', handleMouseOver);
    document.addEventListener('mouseout', handleMouseOut);
    document.addEventListener('focusin', handleFocusIn);
    document.addEventListener('focusout', handleFocusOut);
    document.addEventListener('mousedown', hideTooltip, true);
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        hideTooltip();
      }
    });
    window.addEventListener('scroll', function () {
      if (activeTrigger) {
        positionTooltip(activeTrigger);
      }
    }, true);
    window.addEventListener('resize', function () {
      if (activeTrigger) {
        positionTooltip(activeTrigger);
      }
    });

    if (typeof MutationObserver === 'function' && document.body) {
      const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          if (mutation.type === 'childList') {
            mutation.addedNodes.forEach(function (node) {
              primeExistingTriggers(node);
            });
            return;
          }

          if (mutation.type === 'attributes' && mutation.target instanceof Element) {
            primeTrigger(mutation.target);
          }
        });
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['title', 'data-ptip', 'data-ui-tooltip']
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTooltips, { once: true });
  } else {
    initTooltips();
  }
})();