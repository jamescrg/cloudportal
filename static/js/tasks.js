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

/**
 * On a touch screen, a task swiped to the left is checked off.
 *
 * The row's cells follow the finger, and a green strip with a check mark
 * opens behind them at the right. Let go past a third of the row's width
 * (the strip deepens there to say so), or with a quick flick, and the row
 * runs off and its check mark's own request is sent; short of that it
 * slides back. A swipe to the right, or one that is more down than
 * across, is left to the page.
 *
 * A swipe begun at the edge of the screen belongs to the drawers
 * (alpine-components.js), which open from there, so those are left alone.
 * A task already checked has nothing to do here.
 */
(function () {
  const EDGE_ZONE = 24; // px from a screen edge: the drawers' own
  const LOCK = 10; // px of movement before the direction is decided
  const DISTANCE_RATIO = 0.35; // of the row's width, to check it off
  const FLICK = 0.4; // px/ms: a quick swipe checks it off from less
  const FLICK_MIN = 32; // px: but not from a mere twitch
  const SETTLE = 150; // ms: the slide back, or off

  let swipe = null;

  function place(px) {
    swipe.px = px;
    swipe.cells.forEach((cell) => {
      cell.style.transform = px ? `translateX(${px}px)` : "";
    });
    swipe.reveal.style.width = `${-px}px`;
    swipe.reveal.classList.toggle("armed", -px > swipe.width * DISTANCE_RATIO);
  }

  function settle(on) {
    swipe.cells.forEach((cell) => cell.classList.toggle("task-swipe-settling", on));
    swipe.reveal.classList.toggle("task-swipe-settling", on);
  }

  // Everything put back as it was; `done` is the swipe to clear, so a
  // late timer cannot undo a newer one
  function clear(done) {
    if (!done) return;
    done.cells.forEach((cell) => {
      cell.classList.remove("task-swipe-settling");
      cell.style.transform = "";
    });
    done.reveal?.remove();
    if (swipe === done) swipe = null;
  }

  function begin() {
    const container = swipe.row.closest(".table-container");
    const rowBox = swipe.row.getBoundingClientRect();
    const box = container.getBoundingClientRect();
    const reveal = document.createElement("div");
    reveal.className = "task-swipe-reveal";
    reveal.innerHTML = '<i class="icon-check"></i>';
    reveal.style.top = `${rowBox.top - box.top + container.scrollTop}px`;
    reveal.style.height = `${rowBox.height}px`;
    container.appendChild(reveal);
    swipe.reveal = reveal;
    swipe.width = rowBox.width;
    swipe.cells = [...swipe.row.querySelectorAll("td")];
    swipe.locked = true;
  }

  function onStart(e) {
    // A swipe whose end never came must not be left standing
    clear(swipe);
    if (e.touches.length !== 1) return;
    const row = e.target.closest?.('.tasks-table tr[id^="task-"]');
    if (!row || row.classList.contains("complete") || e.target.closest(".dropdown-menu")) return;
    const t = e.touches[0];
    if (t.clientX <= EDGE_ZONE || t.clientX >= window.innerWidth - EDGE_ZONE) return;
    swipe = { row, cells: [], startX: t.clientX, startY: t.clientY, lastX: t.clientX, lastTime: e.timeStamp, speed: 0, px: 0, locked: false };

    // The end is heard on the element the touch began on too: if the list
    // is re-rendered under the finger, the end never reaches the document
    e.target.addEventListener("touchend", onEnd, { once: true, passive: true });
    e.target.addEventListener("touchcancel", onCancel, { once: true, passive: true });
  }

  function onMove(e) {
    if (!swipe || swipe.leaving) return;
    const t = e.touches[0];
    const dx = t.clientX - swipe.startX;
    const dy = t.clientY - swipe.startY;

    if (!swipe.locked) {
      if (Math.abs(dx) < LOCK && Math.abs(dy) < LOCK) return;
      // down or up is a scroll, and to the right is nothing of ours
      if (Math.abs(dy) > Math.abs(dx) || dx > 0) {
        swipe = null;
        return;
      }
      begin();
    }

    e.preventDefault();
    swipe.speed = (t.clientX - swipe.lastX) / Math.max(1, e.timeStamp - swipe.lastTime);
    swipe.lastX = t.clientX;
    swipe.lastTime = e.timeStamp;
    place(Math.max(-swipe.width, Math.min(0, dx)));
  }

  function onEnd() {
    if (!swipe || swipe.leaving) return;
    const done = swipe;
    if (!done.locked) {
      swipe = null;
      return;
    }
    const far = -done.px > done.width * DISTANCE_RATIO;
    const flicked = done.speed < -FLICK && -done.px > FLICK_MIN;
    settle(true);
    if (far || flicked) {
      // off to the left, then the check mark's own request: the list
      // comes back re-rendered, the row and the strip gone with it
      done.leaving = true;
      place(-done.width);
      setTimeout(() => {
        done.row.querySelector(".tasks-col-checkbox a")?.click();
        // should the request fail, the row is not left off the screen
        setTimeout(() => clear(done), 4000);
      }, SETTLE);
    } else {
      place(0);
      setTimeout(() => clear(done), SETTLE);
    }
  }

  function onCancel() {
    if (swipe && !swipe.leaving) clear(swipe);
  }

  document.addEventListener("touchstart", onStart, { passive: true });
  document.addEventListener("touchmove", onMove, { passive: false });
  document.addEventListener("touchend", onEnd, { passive: true });
  document.addEventListener("touchcancel", onCancel, { passive: true });
})();
