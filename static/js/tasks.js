/**
 * Task list helpers: the selection's ids on bulk requests, and the Due
 * column's date picker.
 *
 * A bulk action (an element marked data-bulk) acts on the tasks picked
 * while selecting (the taskSelection component in alpine-components.js):
 * their ids are added to its request as "ids", and once the list has
 * been re-rendered the selection is cleared, since the tasks it held have
 * changed or gone.
 *
 * The date in the list is a plain link. Clicking it opens a flatpickr
 * calendar anchored to it, from a hidden input made for the occasion, so
 * the link itself never changes. A chosen day, or the calendar's Clear,
 * posts to the task's due-date route and the list re-renders. Closing
 * the calendar without a choice removes the input again.
 */
document.body.addEventListener("htmx:configRequest", (event) => {
  const source = event.detail.elt;
  if (!(source instanceof Element) || !source.closest("[data-bulk]")) {
    return;
  }
  const selection = window.Alpine ? window.Alpine.$data(source) : null;
  if (selection && Array.isArray(selection.ids)) {
    event.detail.parameters.ids = selection.ids.join(",");
  }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  const config = event.detail.requestConfig;
  if (!config || config.parameters.ids === undefined) {
    return;
  }
  const card = event.target.closest(".card.tasks");
  const selection = card && window.Alpine ? window.Alpine.$data(card) : null;
  if (selection && typeof selection.clear === "function") {
    selection.clear();
  }
});

function openTaskDatePicker(anchor, postUrl, currentDate) {
  if (typeof flatpickr === "undefined" || !window.htmx) {
    return;
  }

  const input = document.createElement("input");
  input.type = "text";
  input.className = "task-date-picker-input";
  anchor.parentElement.appendChild(input);

  const post = (dateStr) => {
    window.htmx.ajax("POST", postUrl, {
      source: anchor,
      target: "#tasks-container",
      swap: "innerHTML scroll:none",
      values: { due_date: dateStr },
    });
  };

  flatpickr(input, {
    dateFormat: "Y-m-d",
    defaultDate: currentDate || null,
    allowInput: false,
    onReady: (_, __, fp) => {
      const clear = document.createElement("button");
      clear.textContent = "Clear";
      clear.className = "flatpickr-clear";
      clear.type = "button";
      clear.addEventListener("click", () => {
        post("");
        fp.close();
      });
      fp.calendarContainer.appendChild(clear);
      fp.open();
    },
    onChange: (_, dateStr) => post(dateStr),
    onClose: (_, __, fp) => {
      // Let the close finish before the input goes
      setTimeout(() => {
        fp.destroy();
        input.remove();
      }, 0);
    },
  });
}
