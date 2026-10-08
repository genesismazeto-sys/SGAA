/*
  UI-B23 — comprovantes picker, shared by every student comprovante upload.

  Contract
  - Picking files APPENDS to the selection: a second picker interaction never
    discards what was chosen before. The same file picked twice (same name,
    size and modification time) is kept once.
  - Every selected file is listed under the upload card, one row each, with a
    real remove button named for its file ("Remover comprovante <nome>").
  - The input's FileList is rebuilt from that list, so an ordinary form submit
    sends exactly the files the student sees -- no more, no fewer.
  - Stored attachments the server renders in the same list can be marked for
    removal. Each mark adds one hidden remover_comprovantes=<id> input, so
    nothing stored is ever removed unless its id is submitted.

  Markup
    <div class="field-card file-card" data-upload-card>
      <div class="field-chip">...</div>
      <input class="file-input" type="file" multiple data-file-list="LIST_ID">
      <div class="control file-name" data-file-name>Nenhum arquivo selecionado</div>
      <div class="field-chip chip-right">...</div>
    </div>
    <ul class="file-list" id="LIST_ID" aria-label="..." hidden>
      <li class="file-list-item" data-existing-id="12">
        <i class="lucide" data-lucide="file-text" aria-hidden="true"></i>
        <a class="file-list-name" href="...">nome.pdf</a>
        <button type="button" class="file-list-remove" aria-label="Remover comprovante nome.pdf">...</button>
      </li>
    </ul>
*/
(function(){
  'use strict';

  var EMPTY_LABEL = 'Nenhum arquivo selecionado';

  function fileKey(file){
    return [file.name, file.size, file.lastModified].join('\u0000');
  }

  function icon(name){
    var element = document.createElement('i');
    element.className = 'lucide';
    element.setAttribute('data-lucide', name);
    element.setAttribute('aria-hidden', 'true');
    return element;
  }

  function removeButton(fileName){
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'file-list-remove';
    button.setAttribute('aria-label', 'Remover comprovante ' + fileName);
    button.appendChild(icon('x'));
    return button;
  }

  function enhance(card){
    var input = card.querySelector('input[type="file"][data-file-list]');
    if (!input || card.getAttribute('data-comprovantes-picker') === '1') return;
    card.setAttribute('data-comprovantes-picker', '1');
    var list = document.getElementById(input.getAttribute('data-file-list'));
    var nameEl = card.querySelector('[data-file-name]');
    var chip = card.querySelector('.chip-right');
    if (!list || !nameEl) return;
    var canRebuild = typeof DataTransfer === 'function';
    var selected = [];

    function syncInput(){
      if (!canRebuild) return;
      var transfer = new DataTransfer();
      selected.forEach(function(file){ transfer.items.add(file); });
      input.files = transfer.files;
    }

    function refresh(){
      var count = selected.length;
      nameEl.textContent = count === 0
        ? EMPTY_LABEL
        : (count === 1 ? '1 arquivo selecionado' : count + ' arquivos selecionados');
      // The card stays an "Anexar" action (no .has-file dimming): more files
      // can always be added; the list below carries the selection.
      list.hidden = !list.querySelector('.file-list-item');
      if (window.lucide && typeof window.lucide.createIcons === 'function') window.lucide.createIcons();
    }

    function focusAfterRemoval(index){
      var buttons = list.querySelectorAll('.file-list-remove');
      var next = buttons[Math.min(index, buttons.length - 1)];
      if (next) next.focus();
    }

    function positionOf(item){
      return Array.prototype.indexOf.call(list.querySelectorAll('.file-list-item'), item);
    }

    function renderSelected(){
      Array.prototype.forEach.call(list.querySelectorAll('[data-selected-file]'), function(item){
        item.remove();
      });
      selected.forEach(function(file){
        var item = document.createElement('li');
        item.className = 'file-list-item';
        item.setAttribute('data-selected-file', '');
        item.appendChild(icon('file-text'));
        var name = document.createElement('span');
        name.className = 'file-list-name';
        name.textContent = file.name;
        item.appendChild(name);
        var button = removeButton(file.name);
        button.addEventListener('click', function(){
          var position = positionOf(item);
          selected = selected.filter(function(other){ return other !== file; });
          syncInput();
          renderSelected();
          focusAfterRemoval(position);
        });
        item.appendChild(button);
        list.appendChild(item);
      });
      refresh();
    }

    Array.prototype.forEach.call(list.querySelectorAll('[data-existing-id]'), function(item){
      var button = item.querySelector('.file-list-remove');
      if (!button) return;
      button.addEventListener('click', function(){
        var position = positionOf(item);
        var marker = document.createElement('input');
        marker.type = 'hidden';
        marker.name = 'remover_comprovantes';
        marker.value = item.getAttribute('data-existing-id');
        (input.form || card).appendChild(marker);
        item.remove();
        refresh();
        focusAfterRemoval(position);
      });
    });

    input.addEventListener('change', function(){
      // STORAGE S3-A: a direct-upload input is owned by direct-upload.js; the
      // picker keeps only the stored-attachment removal markers.
      if (input.hasAttribute('data-direct-upload-input')) return;
      var picked = Array.prototype.slice.call(input.files || []);
      if (!canRebuild){
        selected = picked;
      } else {
        var known = {};
        selected.forEach(function(file){ known[fileKey(file)] = true; });
        picked.forEach(function(file){
          var key = fileKey(file);
          if (!known[key]){
            known[key] = true;
            selected.push(file);
          }
        });
        syncInput();
      }
      renderSelected();
    });

    function openPicker(){ input.click(); }
    card.addEventListener('click', function(event){
      if (event.target !== input) openPicker();
    });
    if (chip){
      chip.addEventListener('click', function(event){
        event.stopPropagation();
        openPicker();
      });
    }

    renderSelected();
  }

  function init(){
    Array.prototype.forEach.call(document.querySelectorAll('[data-upload-card]'), enhance);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
