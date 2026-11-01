(function() {
  let focusedInputId = null;

  document.body.addEventListener('htmx:beforeSwap', function(evt) {
    const activeElement = document.activeElement;
    // Only save focus if the request was triggered by the input itself
    // (e.g. typing triggered a swap) or by something holding it (the form
    // it was typed into, or the container being refreshed around it: an
    // hx-preserve input is moved into the new content, which drops its
    // focus), not by clicking something else
    const requestElt = evt.detail.requestConfig && evt.detail.requestConfig.elt;
    if (activeElement && activeElement.tagName === 'INPUT' && activeElement.id) {
      const target = evt.detail.target;
      const fromItself = activeElement === requestElt;
      const fromAround = requestElt && requestElt.contains(activeElement);
      if (target.contains(activeElement) && (fromItself || fromAround)) {
        focusedInputId = activeElement.id;
      }
    }
  });

  document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (focusedInputId) {
      const input = document.getElementById(focusedInputId);
      if (input) {
        input.focus({ preventScroll: true });
        input.setSelectionRange(input.value.length, input.value.length);
      }
      focusedInputId = null;
    }
  });
})();
