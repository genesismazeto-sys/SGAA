/* SGAA human-text authority, browser side.
   Mirrors app/text.py `human_text_key`: Unicode compatibility decomposition
   (NFKD), only the combining marks dropped, lower-cased, whitespace collapsed.
   "Éverto", "éverto" and "EVERTO" all become "everto"; "Ç" becomes "c".
   For names, titles and descriptions only -- comparison keys, never display
   text. Every client-side search over human text goes through `key`. */
(function (global) {
  'use strict';

  var COMBINING_MARKS = /\p{M}/gu;

  function key(value) {
    return String(value == null ? '' : value)
      .normalize('NFKD')
      .replace(COMBINING_MARKS, '')
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)
      .join(' ');
  }

  function includes(haystack, needle) {
    return key(haystack).indexOf(key(needle)) !== -1;
  }

  global.SGAAHumanText = Object.freeze({ key: key, includes: includes });
})(window);
