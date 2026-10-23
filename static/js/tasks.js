/**
 * Task list helpers: the Due column's date picker.
 *
 * The date in the list is a plain link. Clicking it opens a flatpickr
 * calendar anchored to it, from a hidden input made for the occasion, so
 * the link itself never changes. A chosen day, or the calendar's Clear,
 * posts to the task's due-date route and the list re-renders. Closing
 * the calendar without a choice removes the input again.
 *
 * Opened from a dropdown's item (the bulk bar's Choose a Date…), the
 * calendar hangs off the dropdown's button instead, since the menu closes
 * on the click. flatpickr draws its own calendar on phones too: its usual
 * hand-off to the phone's picker needs a visible input, which this is not.
 */
function openTaskDatePicker(anchor, postUrl, currentDate) {
  if (typeof flatpickr === "undefined" || !window.htmx) {
    return;
  }

  const dropdown = anchor.closest(".dropdown-menu")?.closest(".dropdown");
  const host = dropdown || anchor.parentElement;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "task-date-picker-input";
  host.appendChild(input);

  const post = (dateStr) => {
    window.htmx.ajax("POST", postUrl, {
      target: "#tasks-container",
      swap: "innerHTML scroll:none",
      values: { due_date: dateStr },
    });
  };

  flatpickr(input, {
    dateFormat: "Y-m-d",
    defaultDate: currentDate || null,
    allowInput: false,
    disableMobile: true,
    positionElement: dropdown?.querySelector("[x-ref=button]") || anchor,
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
