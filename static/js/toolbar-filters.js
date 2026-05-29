(function(){
  function buildDeleteButton(){
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn toolbar-bulk-delete';
    button.hidden = true;
    button.innerHTML = '<i class="lucide" data-lucide="trash-2"></i><span class="btn-label">Excluir</span>';
    return button;
  }

  function buildSelectAllButton(){
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn toolbar-select-all';
    button.innerHTML = '<i class="lucide" data-lucide="check-check" style="margin-right:4px;"></i><span>Selecionar tudo</span>';
    return button;
  }

  function isAllRowsSelected(rows, selectedRows){
    return rows.length > 0 && selectedRows.size === rows.length;
  }

  function isInteractiveTarget(target){
    return !!target.closest('a, button, input, label, select, textarea');
  }

  function getSelectableRows(root){
    return Array.from(root.querySelectorAll('.impresso-card[role="listitem"]')).filter((row) => !row.classList.contains('header') && !row.classList.contains('toolbar-live-search-hidden') && !row.classList.contains('toolbar-filter-hidden'));
  }

  function normalizeSearchText(value){
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();
  }

  async function postDeleteUrls(urls){
    for (const url of urls){
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!response.ok){
        throw new Error('delete-failed');
      }
    }
  }

  function splitQueryValues(raw){
    return String(raw || '')
      .split(/[;,\n|]+/)
      .map((part) => part.trim())
      .filter(Boolean);
  }

  function getGroupType(group){
    const type = String(group?.type || 'multi_select').toLowerCase();
    if (type === 'text_contains') return 'text_contains';
    if (type === 'number_range') return 'number_range';
    if (type === 'date_range') return 'date_range';
    return 'multi_select';
  }

  function createEmptyStateForGroup(group){
    const type = getGroupType(group);
    if (type === 'text_contains') return '';
    if (type === 'number_range' || type === 'date_range') return { min: '', max: '' };
    return new Set();
  }

  function cloneGroupState(group, value){
    const type = getGroupType(group);
    if (type === 'text_contains') return String(value || '');
    if (type === 'number_range' || type === 'date_range'){
      return {
        min: String(value?.min || ''),
        max: String(value?.max || ''),
      };
    }
    return new Set(value || []);
  }

  function hasGroupSelection(group, value){
    const type = getGroupType(group);
    if (type === 'text_contains') return !!String(value || '').trim();
    if (type === 'number_range' || type === 'date_range') return !!String(value?.min || '').trim() || !!String(value?.max || '').trim();
    return (value?.size || 0) > 0;
  }

  function getGroupSelectionCount(group, value){
    const type = getGroupType(group);
    if (type === 'text_contains') return hasGroupSelection(group, value) ? 1 : 0;
    if (type === 'number_range' || type === 'date_range'){
      let total = 0;
      if (String(value?.min || '').trim()) total += 1;
      if (String(value?.max || '').trim()) total += 1;
      return total;
    }
    return value?.size || 0;
  }

  function buildState(searchParams, schema){
    const state = {};
    schema.forEach((group) => {
      const type = getGroupType(group);
      if (type === 'text_contains'){
        state[group.param] = String(searchParams.get(group.param) || '').trim();
        return;
      }
      if (type === 'number_range' || type === 'date_range'){
        state[group.param] = {
          min: String(searchParams.get(`${group.param}_min`) || '').trim(),
          max: String(searchParams.get(`${group.param}_max`) || '').trim(),
        };
        return;
      }

      const selected = new Set();
      const rawValues = searchParams.getAll(group.param);
      if (!rawValues.length){
        const single = searchParams.get(group.param);
        if (single) rawValues.push(single);
      }
      rawValues.forEach((raw) => {
        splitQueryValues(raw).forEach((value) => selected.add(value));
      });
      state[group.param] = selected;
    });
    return state;
  }

  function cloneState(state, schema){
    const next = {};
    schema.forEach((group) => {
      next[group.param] = cloneGroupState(group, state[group.param]);
    });
    return next;
  }

  function countSelections(state, schema){
    return schema.reduce((total, group) => total + getGroupSelectionCount(group, state[group.param]), 0);
  }

  window.createToolbarQueryHelpers = function createToolbarQueryHelpers(){
    const qs = () => new URLSearchParams(window.location.search);
    const setParams = (params) => {
      window.location.search = params.toString();
    };
    const openPopover = (button, menu) => {
      if (!button || !menu) return;
      const rect = button.getBoundingClientRect();
      menu.style.position = 'absolute';
      menu.style.top = `${Math.round(window.scrollY + rect.bottom + 6)}px`;
      menu.style.left = `${Math.round(window.scrollX + rect.left)}px`;
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
    };
    const closePopover = (button, menu) => {
      if (!button || !menu) return;
      menu.hidden = true;
      button.setAttribute('aria-expanded', 'false');
    };

    return { qs, setParams, openPopover, closePopover };
  };

  window.initToolbarSortMenu = function initToolbarSortMenu(config){
    const {
      qs,
      setParams,
      openPopover,
      closePopover,
      buttonSelector = '#sort-field',
      menuSelector = '#sort-menu',
      toggleSelector = '#sort-toggle',
      labelSelector = '#sort-label',
      dirLabelSelector = '#dir-label',
      dirValueSelector = '#sort-dir',
      listSelector = '#sort-fields-list',
      closeSelector = '#sort-close',
      applyButtonSelector = '#sort-apply',
      clearButtonSelector = '#sort-clear',
      groupSelector,
      sortParam = 's',
      dirParam = 'dir',
      pageParam = 'page',
      defaultField = '',
      defaultDirection = 'asc',
      defaultLabel = 'Organizar por',
      mode = 'instant',
      outsideCloseEvent = 'click',
      selectedClass = 'selected',
      formatLabel,
    } = config || {};

    if (typeof qs !== 'function' || typeof setParams !== 'function' || typeof openPopover !== 'function' || typeof closePopover !== 'function'){
      return;
    }

    const sortFieldBtn = document.querySelector(buttonSelector);
    const sortMenu = document.querySelector(menuSelector);
    const sortToggle = document.querySelector(toggleSelector);
    const sortLabel = document.querySelector(labelSelector);
    const dirLabel = dirLabelSelector ? document.querySelector(dirLabelSelector) : null;
    const dirValue = dirValueSelector ? document.querySelector(dirValueSelector) : null;
    const list = document.querySelector(listSelector);
    const closeButton = closeSelector ? document.querySelector(closeSelector) : null;
    const applyButton = applyButtonSelector ? document.querySelector(applyButtonSelector) : null;
    const clearButton = clearButtonSelector ? document.querySelector(clearButtonSelector) : null;

    const syncUi = () => {
      const params = qs();
      const currentField = (params.get(sortParam) || defaultField || '').toLowerCase();
      const currentDirection = (params.get(dirParam) || defaultDirection || 'asc').toLowerCase();
      const currentItem = currentField && list ? list.querySelector(`.menu-item[data-field="${currentField}"]`) : null;

      if (sortLabel) {
        const fieldText = currentItem ? (currentItem.textContent || '').trim() : defaultLabel;
        if (typeof formatLabel === 'function') {
          sortLabel.innerHTML = formatLabel(fieldText, !!currentItem);
        } else {
          sortLabel.textContent = fieldText;
        }
      }
      if (dirLabel) dirLabel.textContent = currentDirection === 'desc' ? 'DESC' : 'ASC';
      if (dirValue) dirValue.textContent = currentDirection === 'desc' ? '↓' : '↑';
      if (list){
        list.querySelectorAll('.menu-item').forEach((item) => item.classList.remove(selectedClass));
        if (currentItem) currentItem.classList.add(selectedClass);
      }
    };

    syncUi();

    if (sortFieldBtn && sortMenu){
      sortFieldBtn.addEventListener('click', () => {
        if (sortMenu.hidden) openPopover(sortFieldBtn, sortMenu);
        else closePopover(sortFieldBtn, sortMenu);
      });
    }

    if (list){
      list.addEventListener('click', (event) => {
        const item = event.target.closest('.menu-item');
        if (!item) return;

        if (mode === 'apply'){
          list.querySelectorAll('.menu-item').forEach((entry) => entry.classList.remove(selectedClass));
          item.classList.add(selectedClass);
          return;
        }

        const field = item.dataset.field;
        if (!field) return;
        const params = qs();
        params.set(sortParam, field);
        params.delete(pageParam);
        setParams(params);
      });
    }

    if (mode === 'apply'){
      applyButton?.addEventListener('click', () => {
        const selectedItem = list?.querySelector(`.menu-item.${selectedClass}`);
        const params = qs();
        if (selectedItem?.dataset.field) params.set(sortParam, selectedItem.dataset.field);
        else params.delete(sortParam);
        params.delete(pageParam);
        setParams(params);
        if (sortFieldBtn && sortMenu) closePopover(sortFieldBtn, sortMenu);
      });

      clearButton?.addEventListener('click', () => {
        const params = qs();
        params.delete(sortParam);
        params.delete(pageParam);
        setParams(params);
      });
    }

    closeButton?.addEventListener('click', () => {
      if (sortFieldBtn && sortMenu) closePopover(sortFieldBtn, sortMenu);
    });

    sortToggle?.addEventListener('click', () => {
      const params = qs();
      const currentDirection = (params.get(dirParam) || defaultDirection || 'asc').toLowerCase();
      params.set(dirParam, currentDirection === 'desc' ? 'asc' : 'desc');
      params.delete(pageParam);
      setParams(params);
    });

    document.addEventListener(outsideCloseEvent, (event) => {
      if (!sortFieldBtn || !sortMenu || sortMenu.hidden) return;
      const withinMenu = !!event.target.closest(menuSelector);
      const withinButton = !!event.target.closest(buttonSelector);
      const withinGroup = groupSelector ? !!event.target.closest(groupSelector) : false;
      if (!withinMenu && !withinButton && !withinGroup) closePopover(sortFieldBtn, sortMenu);
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sortFieldBtn && sortMenu && !sortMenu.hidden){
        closePopover(sortFieldBtn, sortMenu);
      }
    });

    return { sortFieldBtn, sortMenu, sortToggle, sortLabel, dirLabel, dirValue, list };
  };

  window.initToolbarPillFilter = function initToolbarPillFilter(config){
    const {
      qs,
      setParams,
      openPopover,
      closePopover,
      schema,
      buttonId = 'filter-btn',
      menuId = 'filter-menu',
      badgeId = 'filter-badge',
      aliasesToClear = [],
    } = config || {};

    if (typeof qs !== 'function' || typeof setParams !== 'function' || !Array.isArray(schema) || !schema.length){
      return;
    }

    const filterBtn = document.getElementById(buttonId);
    const filterMenu = document.getElementById(menuId);
    const filterBadge = document.getElementById(badgeId);
    const pillsRoot = filterMenu?.querySelector('.filter-pills');
    const valuesRoot = filterMenu?.querySelector('.filter-values');
    const applyBtn = filterMenu?.querySelector('#filter-apply');
    const clearBtn = filterMenu?.querySelector('#filter-clear-all');

    if (!filterBtn || !filterMenu || !pillsRoot || !valuesRoot){
      return;
    }

    let appliedState = buildState(qs(), schema);
    let draftState = cloneState(appliedState, schema);
    let activeParam = schema.find((group) => hasGroupSelection(group, appliedState[group.param]))?.param || schema[0].param;

    const ensureDraftEntry = (group) => {
      const current = draftState[group.param];
      if (current === undefined){
        draftState[group.param] = createEmptyStateForGroup(group);
        return draftState[group.param];
      }
      return current;
    };

    const updateBadge = () => {
      if (!filterBadge) return;
      const total = countSelections(appliedState, schema);
      filterBadge.textContent = String(total);
      filterBadge.style.display = total ? 'inline-flex' : 'none';
      filterBtn?.classList.toggle('is-active', total > 0);
    };

    const renderPills = () => {
      pillsRoot.innerHTML = '';
      schema.forEach((group) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'filter-pill';
        if (group.param === activeParam) button.classList.add('is-active');
        if (hasGroupSelection(group, draftState[group.param])) button.classList.add('has-selection');
        button.dataset.param = group.param;
        button.textContent = group.label;
        pillsRoot.appendChild(button);
      });
    };

    const renderValues = () => {
      const currentGroup = schema.find((group) => group.param === activeParam) || schema[0];
      const groupType = getGroupType(currentGroup);
      valuesRoot.innerHTML = '';

      if (groupType === 'text_contains'){
        const wrap = document.createElement('div');
        wrap.className = 'filter-text-wrap';

        const input = document.createElement('input');
        input.type = 'search';
        input.className = 'filter-text-input';
        input.dataset.param = currentGroup.param;
        input.placeholder = currentGroup.placeholder || 'Digite para filtrar';
        input.value = String(draftState[currentGroup.param] || '');

        wrap.appendChild(input);
        valuesRoot.appendChild(wrap);
        return;
      }

      if (groupType === 'number_range' || groupType === 'date_range'){
        const isDateRange = groupType === 'date_range';
        const wrap = document.createElement('div');
        wrap.className = 'filter-range-wrap';

        const minLabel = document.createElement('label');
        minLabel.className = 'filter-range-label';
        minLabel.textContent = currentGroup.min_label || 'Mínimo';

        const minInput = document.createElement('input');
        minInput.type = isDateRange ? 'date' : 'number';
        minInput.className = 'filter-range-input';
        minInput.dataset.param = currentGroup.param;
        minInput.dataset.bound = 'min';
        minInput.placeholder = currentGroup.min_placeholder || (isDateRange ? '' : 'Min');
        minInput.value = String(draftState[currentGroup.param]?.min || '');

        const maxLabel = document.createElement('label');
        maxLabel.className = 'filter-range-label';
        maxLabel.textContent = currentGroup.max_label || 'Máximo';

        const maxInput = document.createElement('input');
        maxInput.type = isDateRange ? 'date' : 'number';
        maxInput.className = 'filter-range-input';
        maxInput.dataset.param = currentGroup.param;
        maxInput.dataset.bound = 'max';
        maxInput.placeholder = currentGroup.max_placeholder || (isDateRange ? '' : 'Max');
        maxInput.value = String(draftState[currentGroup.param]?.max || '');

        wrap.appendChild(minLabel);
        wrap.appendChild(minInput);
        wrap.appendChild(maxLabel);
        wrap.appendChild(maxInput);
        valuesRoot.appendChild(wrap);
        return;
      }

      const selectedValues = draftState[currentGroup.param] || new Set();

      if (!currentGroup.values?.length){
        const empty = document.createElement('div');
        empty.className = 'filter-empty';
        empty.textContent = 'Nenhuma opcao disponivel.';
        valuesRoot.appendChild(empty);
        return;
      }

      currentGroup.values.forEach((entry) => {
        const row = document.createElement('label');
        row.className = 'check-row';
        row.title = entry.label;

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'filter-checkbox';
        checkbox.dataset.param = currentGroup.param;
        checkbox.value = entry.value;
        checkbox.checked = selectedValues.has(entry.value);

        const text = document.createElement('span');
        text.className = 'check-text';
        text.textContent = entry.label;

        row.appendChild(checkbox);
        row.appendChild(text);
        valuesRoot.appendChild(row);
      });
    };

    const resetDraftState = () => {
      appliedState = buildState(qs(), schema);
      draftState = cloneState(appliedState, schema);
      activeParam = schema.find((group) => hasGroupSelection(group, draftState[group.param]))?.param || schema[0].param;
    };

    const closeMenu = () => {
      closePopover(filterBtn, filterMenu);
      resetDraftState();
      updateBadge();
    };

    updateBadge();

    filterBtn.addEventListener('click', () => {
      if (filterMenu.hidden){
        resetDraftState();
        renderPills();
        renderValues();
        openPopover(filterBtn, filterMenu);
      } else {
        closeMenu();
      }
    });

    filterMenu.addEventListener('click', (event) => {
      event.stopPropagation();
    });

    pillsRoot.addEventListener('click', (event) => {
      event.stopPropagation();
      const pill = event.target.closest('.filter-pill');
      if (!pill) return;
      activeParam = pill.dataset.param || schema[0].param;
      renderPills();
      renderValues();
    });

    valuesRoot.addEventListener('change', (event) => {
      event.stopPropagation();
      const checkbox = event.target.closest('.filter-checkbox');
      if (checkbox){
        const param = checkbox.dataset.param;
        const group = schema.find((entry) => entry.param === param);
        if (!group || getGroupType(group) !== 'multi_select') return;
        const bucket = ensureDraftEntry(group);
        if (!(bucket instanceof Set)){
          draftState[param] = new Set();
        }
        if (checkbox.checked) draftState[param].add(checkbox.value);
        else draftState[param].delete(checkbox.value);
        renderPills();
        return;
      }

      const rangeInput = event.target.closest('.filter-range-input');
      if (rangeInput){
        const param = rangeInput.dataset.param;
        const group = schema.find((entry) => entry.param === param);
        const groupType = getGroupType(group);
        if (!group || (groupType !== 'number_range' && groupType !== 'date_range')) return;
        const bucket = ensureDraftEntry(group);
        const bound = rangeInput.dataset.bound === 'max' ? 'max' : 'min';
        bucket[bound] = String(rangeInput.value || '').trim();
        renderPills();
      }
    });

    valuesRoot.addEventListener('input', (event) => {
      event.stopPropagation();
      const textInput = event.target.closest('.filter-text-input');
      if (textInput){
        const param = textInput.dataset.param;
        const group = schema.find((entry) => entry.param === param);
        if (!group || getGroupType(group) !== 'text_contains') return;
        draftState[param] = String(textInput.value || '');
        renderPills();
        return;
      }

      const rangeInput = event.target.closest('.filter-range-input');
      if (rangeInput){
        const param = rangeInput.dataset.param;
        const group = schema.find((entry) => entry.param === param);
        const groupType = getGroupType(group);
        if (!group || (groupType !== 'number_range' && groupType !== 'date_range')) return;
        const bucket = ensureDraftEntry(group);
        const bound = rangeInput.dataset.bound === 'max' ? 'max' : 'min';
        bucket[bound] = String(rangeInput.value || '').trim();
        renderPills();
      }
    });

    applyBtn?.addEventListener('click', () => {
      const params = qs();
      schema.forEach((group) => {
        params.delete(group.param);
        const type = getGroupType(group);
        if (type === 'number_range' || type === 'date_range'){
          params.delete(`${group.param}_min`);
          params.delete(`${group.param}_max`);
        }
      });
      aliasesToClear.forEach((name) => params.delete(name));
      schema.forEach((group) => {
        const type = getGroupType(group);
        const value = draftState[group.param];
        if (type === 'text_contains'){
          const text = String(value || '').trim();
          if (text) params.set(group.param, text);
          return;
        }
        if (type === 'number_range' || type === 'date_range'){
          const min = String(value?.min || '').trim();
          const max = String(value?.max || '').trim();
          if (min) params.set(`${group.param}_min`, min);
          if (max) params.set(`${group.param}_max`, max);
          return;
        }
        Array.from(value || []).forEach((entry) => params.append(group.param, entry));
      });
      setParams(params);
    });

    clearBtn?.addEventListener('click', () => {
      draftState = {};
      schema.forEach((group) => {
        draftState[group.param] = createEmptyStateForGroup(group);
      });
      activeParam = schema[0].param;
      renderPills();
      renderValues();
    });

    document.addEventListener('click', (event) => {
      if (filterMenu.hidden) return;
      if (!event.target.closest(`#${menuId}`) && !event.target.closest(`#${buttonId}`)) closeMenu();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !filterMenu.hidden) closeMenu();
    });

    const closeOnViewportChange = () => {
      if (!filterMenu.hidden) closeMenu();
    };
    window.addEventListener('resize', closeOnViewportChange);
    document.addEventListener('scroll', closeOnViewportChange, true);
  };

  window.initToolbarFilterMenu = function initToolbarFilterMenu(config){
    const {
      qs,
      setParams,
      openPopover,
      closePopover,
      schema,
      schemaSelector = '#filter-schema-data',
      aliasesToClear = [],
      buttonId = 'filter-btn',
      menuId = 'filter-menu',
      badgeId = 'filter-badge',
    } = config || {};

    const resolvedSchema = Array.isArray(schema)
      ? schema
      : JSON.parse(document.querySelector(schemaSelector)?.textContent || '[]');

    if (!resolvedSchema.length) return;

    return window.initToolbarPillFilter?.({
      qs,
      setParams,
      openPopover,
      closePopover,
      schema: resolvedSchema,
      aliasesToClear,
      buttonId,
      menuId,
      badgeId,
    });
  };

  window.initToolbarLiveSearch = function initToolbarLiveSearch(config){
    const {
      inputSelector,
      rowsRootSelector,
      rowSelector = '.impresso-card[role="listitem"]',
      emptyMessage = 'Nenhum resultado encontrado.',
    } = config || {};

    if (!inputSelector || !rowsRootSelector) return;

    const input = document.querySelector(inputSelector);
    const rowsRoot = document.querySelector(rowsRootSelector);
    if (!input || !rowsRoot) return;

    const getRows = () => Array.from(rowsRoot.querySelectorAll(rowSelector)).filter((row) => !row.classList.contains('header'));

    let emptyState = rowsRoot.querySelector('.toolbar-live-search-empty');
    if (!emptyState){
      emptyState = document.createElement('div');
      emptyState.className = 'toolbar-live-search-empty';
      emptyState.style.padding = '1rem';
      emptyState.style.textAlign = 'center';
      emptyState.style.color = '#6b7280';
      emptyState.hidden = true;
      rowsRoot.appendChild(emptyState);
    }

    const applySearch = () => {
      const query = normalizeSearchText(input.value);
      const rows = getRows();
      let visibleCount = 0;

      rows.forEach((row) => {
        const haystack = row.dataset.searchText || normalizeSearchText(row.textContent);
        if (!row.dataset.searchText) row.dataset.searchText = haystack;
        const matches = !query || haystack.includes(query);
        row.classList.toggle('toolbar-live-search-hidden', !matches);
        row.setAttribute('aria-hidden', matches ? 'false' : 'true');
        if (matches && !row.classList.contains('toolbar-filter-hidden')) visibleCount += 1;
      });

      emptyState.textContent = emptyMessage;
      emptyState.hidden = !(rows.length && query && visibleCount === 0);
    };

    input.addEventListener('input', applySearch);
    input.addEventListener('search', applySearch);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') event.preventDefault();
    });

    applySearch();
  };

  window.initToolbarRowSelection = function initToolbarRowSelection(config){
    const {
      toolbarSelector = '#impressoes-toolbar',
      rowsRootSelector,
      filterGroupSelector = '#grp-filtro',
      addButtonSelector = '.btn.btn-nova-alinhado',
      enableSelectAllButton = true,
      enableBulkDelete = true,
      onSelectionChange,
    } = config || {};

    const toolbar = document.querySelector(toolbarSelector);
    if (!toolbar) return;

    const rowsRoot = rowsRootSelector ? document.querySelector(rowsRootSelector) : (toolbar.parentElement?.querySelector('.impressoes-cards') || document.querySelector('.impressoes-cards'));
    if (!rowsRoot) return;

    const rows = getSelectableRows(rowsRoot);
    if (!rows.length) return;

    const filterGroup = toolbar.querySelector(filterGroupSelector);
    const actions = toolbar.querySelector('.actions');
    const addButton = actions?.querySelector(addButtonSelector);
    if (!filterGroup || !actions || !addButton) return;

    let selectAllButton = toolbar.querySelector('.toolbar-select-all');
    if (enableSelectAllButton && !selectAllButton){
      selectAllButton = buildSelectAllButton();
      filterGroup.insertAdjacentElement('afterend', selectAllButton);
    }

    let bulkDeleteButton = actions.querySelector('.toolbar-bulk-delete');
    if (enableBulkDelete && !bulkDeleteButton){
      bulkDeleteButton = buildDeleteButton();
      addButton.insertAdjacentElement('beforebegin', bulkDeleteButton);
    }

    let anchorIndex = null;
    const selectedRows = new Set();

    const clearSelection = () => {
      selectedRows.clear();
      anchorIndex = null;
      syncRowState();
    };

    const updateSelectAllButton = () => {
      if (!selectAllButton) return;
      const label = selectAllButton.querySelector('span');
      const shouldClear = isAllRowsSelected(rows, selectedRows);
      if (label) label.textContent = shouldClear ? 'Desselecionar' : 'Selecionar tudo';
      selectAllButton.setAttribute('aria-label', shouldClear ? 'Desselecionar tudo' : 'Selecionar tudo');
      selectAllButton.setAttribute('title', shouldClear ? 'Desselecionar tudo' : 'Selecionar tudo');
    };

    const syncRowState = () => {
      rows.forEach((row) => {
        const isSelected = selectedRows.has(row);
        row.classList.toggle('selected', isSelected);
        row.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      });

      const selected = Array.from(selectedRows);
      const canDelete = selected.length > 0 && selected.every((row) => !!row.getAttribute('data-delete-url'));
      if (bulkDeleteButton){
        bulkDeleteButton.hidden = !selected.length || !canDelete;
      }
      updateSelectAllButton();
      if (typeof onSelectionChange === 'function'){
        onSelectionChange({
          selectedRows: selected,
          allRows: rows,
          canDelete,
          allSelected: isAllRowsSelected(rows, selectedRows),
        });
      }
    };

    const selectOnly = (row, index) => {
      selectedRows.clear();
      selectedRows.add(row);
      anchorIndex = index;
      syncRowState();
    };

    const addRange = (index) => {
      if (anchorIndex === null){
        anchorIndex = index;
      }
      const start = Math.min(anchorIndex, index);
      const end = Math.max(anchorIndex, index);
      for (let current = start; current <= end; current += 1){
        selectedRows.add(rows[current]);
      }
      syncRowState();
    };

    const selectAllRows = () => {
      selectedRows.clear();
      rows.forEach((row) => selectedRows.add(row));
      anchorIndex = rows.length ? 0 : null;
      syncRowState();
    };

    const toggleAllRows = () => {
      if (isAllRowsSelected(rows, selectedRows)){
        clearSelection();
        return;
      }
      selectAllRows();
    };

    rows.forEach((row, index) => {
      row.setAttribute('aria-selected', 'false');
      row.addEventListener('click', (event) => {
        if (isInteractiveTarget(event.target)) return;
        if (event.shiftKey){
          addRange(index);
          return;
        }
        if (selectedRows.has(row)){
          selectedRows.delete(row);
          anchorIndex = null;
          syncRowState();
          return;
        }
        selectOnly(row, index);
      });
    });

    selectAllButton?.addEventListener('click', () => {
      toggleAllRows();
    });

    document.addEventListener('click', (event) => {
      if (event.target.closest(toolbarSelector)) return;
      if (event.target.closest(rowsRootSelector || '.impressoes-cards')) return;
      if (!selectedRows.size) return;
      clearSelection();
    });

    bulkDeleteButton?.addEventListener('click', async () => {
      const selected = Array.from(selectedRows);
      const deleteUrls = selected.map((row) => row.getAttribute('data-delete-url')).filter(Boolean);
      if (!deleteUrls.length) return;

      const message = deleteUrls.length === 1
        ? 'Tem certeza que deseja excluir o item selecionado?'
        : `Tem certeza que deseja excluir os ${deleteUrls.length} itens selecionados?`;
      if (!window.confirm(message)) return;

      bulkDeleteButton.disabled = true;
      selectAllButton.disabled = true;
      try{
        await postDeleteUrls(deleteUrls);
        window.location.reload();
      }catch(_error){
        window.alert('Não foi possível concluir a exclusão em lote.');
        bulkDeleteButton.disabled = false;
        selectAllButton.disabled = false;
      }
    });

    syncRowState();
    window.lucide?.createIcons?.();

    return {
      getSelectedRows: () => Array.from(selectedRows),
      getAllRows: () => Array.from(rows),
      isAllSelected: () => isAllRowsSelected(rows, selectedRows),
      selectAllRows,
      toggleAllRows,
      clearSelection,
      selectAllButton,
      bulkDeleteButton,
    };
  };

  window.initToolbarSelectionActionsMenu = function initToolbarSelectionActionsMenu(config){
    const {
      buttonSelector,
      menuSelector,
      selectAllSelector,
      deleteSelector,
      hintSelector,
      rowSelectionApi,
      deleteMessageSingle = 'Tem certeza que deseja excluir o item selecionado?',
      deleteMessageMultiple = (count) => `Tem certeza que deseja excluir os ${count} itens selecionados?`,
      onDelete,
    } = config || {};

    const button = buttonSelector ? document.querySelector(buttonSelector) : null;
    const menu = menuSelector ? document.querySelector(menuSelector) : null;
    const selectAllAction = selectAllSelector ? document.querySelector(selectAllSelector) : null;
    const deleteAction = deleteSelector ? document.querySelector(deleteSelector) : null;
    const hint = hintSelector ? document.querySelector(hintSelector) : null;

    if (!button || !menu || !selectAllAction || !deleteAction || !rowSelectionApi) return null;

    const closeMenu = () => {
      menu.hidden = true;
      button.setAttribute('aria-expanded', 'false');
    };

    const openMenu = () => {
      const rect = button.getBoundingClientRect();
      const menuWidth = Math.max(menu.offsetWidth || 190, 190);
      const left = Math.max(12, Math.min(rect.left, window.innerWidth - menuWidth - 12));
      menu.style.position = 'fixed';
      menu.style.top = `${Math.round(rect.bottom + 6)}px`;
      menu.style.left = `${Math.round(left)}px`;
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
    };

    const syncMenu = () => {
      const selectedRows = rowSelectionApi.getSelectedRows();
      const selectedCount = selectedRows.length;
      const allSelected = rowSelectionApi.isAllSelected();
      const allDeletable = selectedCount > 0 && selectedRows.every((row) => !!row.getAttribute('data-delete-url'));
      const label = selectAllAction.querySelector('span');
      if (label) label.textContent = allSelected ? 'Desselecionar' : 'Selecionar tudo';
      selectAllAction.setAttribute('aria-label', allSelected ? 'Desselecionar tudo' : 'Selecionar tudo');
      selectAllAction.setAttribute('title', allSelected ? 'Desselecionar tudo' : 'Selecionar tudo');
      deleteAction.disabled = !allDeletable;
      if (hint){
        hint.textContent = selectedCount
          ? `${selectedCount} item(ns) selecionado(s).`
          : 'Selecione uma ou mais linhas para habilitar as ações.';
      }
    };

    button.addEventListener('click', () => {
      syncMenu();
      if (menu.hidden) openMenu();
      else closeMenu();
    });

    menu.addEventListener('click', (event) => {
      event.stopPropagation();
    });

    document.addEventListener('click', (event) => {
      if (menu.hidden) return;
      if (!event.target.closest(menuSelector) && !event.target.closest(buttonSelector)) closeMenu();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !menu.hidden) closeMenu();
    });

    selectAllAction.addEventListener('click', () => {
      rowSelectionApi.toggleAllRows();
      syncMenu();
    });

    deleteAction.addEventListener('click', async () => {
      if (deleteAction.disabled) return;
      const selectedRows = rowSelectionApi.getSelectedRows();
      const count = selectedRows.length;
      if (!count) return;
      const message = count === 1 ? deleteMessageSingle : deleteMessageMultiple(count);
      if (!window.confirm(message)) return;
      closeMenu();
      button.disabled = true;
      deleteAction.disabled = true;
      selectAllAction.disabled = true;
      try{
        if (typeof onDelete === 'function'){
          await onDelete(selectedRows);
        } else {
          const deleteUrls = selectedRows.map((row) => row.getAttribute('data-delete-url')).filter(Boolean);
          await postDeleteUrls(deleteUrls);
          window.location.reload();
        }
      }catch(_error){
        window.alert('Não foi possível concluir a exclusão em lote.');
        button.disabled = false;
        selectAllAction.disabled = false;
        syncMenu();
      }
    });

    syncMenu();

    return { syncMenu, openMenu, closeMenu };
  };
})();