/**
 * Alpine.js Components
 * Replacement for Bootstrap JS dropdowns and modals
 */

/**
 * Swipe gestures for a slide-in drawer. A side drawer (left or right)
 * opens with a swipe in from its screen edge, closes with a swipe back
 * toward it, and follows the finger in between. A bottom sheet opens
 * with a swipe up that starts on its button, or in from the bottom edge
 * where the phone leaves that edge to the page, and closes with a swipe
 * down from anywhere on it while it sits at the top of its scroll.
 *
 * drawer:   the Alpine component, with isOpen, open() and close()
 * panel():  the element that slides (looked up on each use, since a page
 *           may swap its contents)
 * backdrop: the drawer's own backdrop element
 * side:     'left', 'right' or 'bottom', the edge the panel slides in from
 */
function attachDrawerSwipe(drawer, { panel, backdrop, side }) {
  const mql = window.matchMedia('(min-width: 992px)');
  const EDGE_ZONE = 24;           // px from the edge to start an open-swipe
  const VELOCITY_THRESHOLD = 0.3; // px/ms — a fast flick opens or closes
  const DISTANCE_RATIO = 0.35;    // fraction of the size to snap
  const vertical = side === 'bottom';
  // +1: the panel rests off the right or bottom edge when closed; -1: off the left
  const sign = side === 'left' ? -1 : 1;
  let touch = null;

  // the panel's extent along its axis of travel
  function size() {
    const el = panel();
    return (vertical ? el?.offsetHeight : el?.offsetWidth) || 280;
  }

  function along(t) {
    return vertical ? t.clientY : t.clientX;
  }

  function across(t) {
    return vertical ? t.clientX : t.clientY;
  }

  // px: 0 = fully open, sign * size = fully closed
  function clamp(px) {
    const closed = sign * size();
    return Math.max(Math.min(0, closed), Math.min(Math.max(0, closed), px));
  }

  function applyTranslate(px) {
    panel().style.transform = vertical ? `translateY(${px}px)` : `translateX(${px}px)`;
    // Sync backdrop opacity: 0 when closed, 1 when open
    const progress = 1 - px / (sign * size());
    backdrop.style.opacity = Math.max(0, Math.min(1, progress));
    backdrop.style.pointerEvents = progress > 0.05 ? 'auto' : 'none';
  }

  function clearDrag() {
    const el = panel();
    if (el) {
      el.classList.remove('drawer-dragging');
      el.style.transform = '';
    }
    backdrop.style.opacity = '';
    backdrop.style.pointerEvents = '';
    touch = null;
  }

  function nearEdge(pos, target) {
    if (vertical) {
      return pos >= window.innerHeight - EDGE_ZONE || !!target.closest('.drawer-fab-panel');
    }
    return side === 'right' ? pos >= window.innerWidth - EDGE_ZONE : pos <= EDGE_ZONE;
  }

  function overPanel(pos) {
    if (vertical) return pos >= window.innerHeight - size();
    return side === 'right' ? pos >= window.innerWidth - size() : pos <= size();
  }

  // A sheet scrolled down scrolls back up first; only at its top does a
  // downward swipe close it
  function canDragClosed(target) {
    if (!vertical) return true;
    const el = panel();
    if (!el?.contains(target)) return true;
    return !el.scrollTop;
  }

  function onTouchStart(e) {
    if (mql.matches || !panel()) return; // desktop, or no panel on this page
    const t = e.touches[0];
    const state = { start: along(t), startAcross: across(t), last: along(t), lastTime: e.timeStamp, locked: false };

    if (!drawer.isOpen && nearEdge(along(t), e.target)) {
      touch = { ...state, mode: 'open' };
      panel().classList.add('drawer-dragging');
      backdrop.classList.add('open');
      document.body.style.overflow = 'hidden';
    } else if (drawer.isOpen && (overPanel(along(t)) || e.target.closest('.drawer-backdrop')) && canDragClosed(e.target)) {
      touch = { ...state, mode: 'close' };
      panel().classList.add('drawer-dragging');
    }
  }

  function onTouchMove(e) {
    if (!touch) return;
    const t = e.touches[0];
    const d = along(t) - touch.start;
    const dAcross = across(t) - touch.startAcross;

    // A vertical drag must be claimed from its first movement: once the
    // browser has begun scrolling the sheet (or the page, from its edge)
    // it no longer listens. Sideways there is nothing to scroll, so the
    // side drawers can wait for the direction to be sure.
    if (vertical) {
      e.preventDefault();
    }

    // Lock direction after 10px of movement; movement across the axis of
    // travel is a scroll (or, on a sheet, a sideways gesture), not ours
    if (!touch.locked) {
      if (Math.abs(d) < 10 && Math.abs(dAcross) < 10) return;
      if (Math.abs(dAcross) > Math.abs(d) || (vertical && d < 0)) {
        const wasOpening = touch.mode === 'open';
        clearDrag();
        if (wasOpening) {
          backdrop.classList.remove('open');
          document.body.style.overflow = '';
        }
        return;
      }
      touch.locked = true;
    }

    e.preventDefault();
    touch.last = along(t);
    touch.lastTime = e.timeStamp;

    // Opening starts from the closed position and follows the finger in;
    // closing starts from open and follows it out
    const from = touch.mode === 'open' ? sign * size() : 0;
    applyTranslate(clamp(from + d));
  }

  function onTouchEnd(e) {
    if (!touch) return;
    const mode = touch.mode;
    const dt = e.timeStamp - touch.lastTime || 1;
    const d = touch.last - touch.start;
    const velocity = d / dt; // px/ms, positive = rightward or downward
    const extent = size();

    clearDrag();

    // Movement away from the panel's edge opens; toward it closes
    if (mode === 'open') {
      if (velocity * -sign > VELOCITY_THRESHOLD || d * -sign > extent * DISTANCE_RATIO) {
        drawer.open();
      } else {
        backdrop.classList.remove('open');
        document.body.style.overflow = '';
      }
    } else if (velocity * sign > VELOCITY_THRESHOLD || d * sign > extent * DISTANCE_RATIO) {
      drawer.close();
    }
  }

  document.addEventListener('touchstart', onTouchStart, { passive: true });
  document.addEventListener('touchmove', onTouchMove, { passive: false });
  document.addEventListener('touchend', onTouchEnd, { passive: true });
}


// The Repeat fields of the event and task forms
// (templates/components/repeat-fields.html). The Repeat choices read as
// Google's do, from the date ("Weekly on
// Tuesday", "Monthly on the second Tuesday", "Annually on October 6"), and
// follow it as it changes; so does the weekday ticked for a weekly repeat,
// while it is still the only one. The ordinal matches the server's
// (recurrence.nth_weekday): a fifth weekday repeats as the last.
const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const ORDINALS = { 1: "first", 2: "second", 3: "third", 4: "fourth", 5: "last" };

function parseDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  if (!match) {
    return null;
  }
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

// Monday 0, as Python counts them
function weekdayOf(day) {
  return (day.getDay() + 6) % 7;
}

function repeatLabels(day) {
  if (!day) {
    return {};
  }
  const weekday = WEEKDAY_NAMES[weekdayOf(day)];
  const nth = ORDINALS[Math.floor((day.getDate() - 1) / 7) + 1];
  return {
    daily: "Daily",
    weekdays: "Every weekday (Monday to Friday)",
    // The days come from the checkboxes beneath, so the choice is plain
    weekly: "Weekly",
    monthly: `Monthly on day ${day.getDate()}`,
    monthly_weekday: `Monthly on the ${nth} ${weekday}`,
    yearly: `Annually on ${MONTH_NAMES[day.getMonth()]} ${day.getDate()}`,
  };
}

document.addEventListener('alpine:init', () => {
  // The task list's selection: a mode the Select button turns on, and the
  // ids picked while it is. It sits on the card, outside the list htmx
  // swaps, so it outlives every re-render; the bulk requests carry the
  // ids (static/js/tasks.js), and the list clears them once one is done.
  Alpine.data("taskSelection", () => ({
    mode: false,
    ids: [],
    toggleMode() {
      this.mode = !this.mode;
      if (!this.mode) {
        this.ids = [];
      }
    },
    picked(id) {
      return this.ids.includes(id);
    },
    pick(id) {
      if (this.picked(id)) {
        this.ids = this.ids.filter((picked) => picked !== id);
      } else {
        this.ids = [...this.ids, id];
      }
    },
    allIds() {
      return [...this.$root.querySelectorAll("tr[data-task-id]")].map((row) =>
        Number(row.dataset.taskId),
      );
    },
    allPicked() {
      const all = this.allIds();
      return all.length > 0 && all.every((id) => this.picked(id));
    },
    toggleAll() {
      this.ids = this.allPicked() ? [] : this.allIds();
    },
    clear() {
      this.ids = [];
    },
  }));

  Alpine.data("repeatFields", (initial) => ({
    repeat: initial.repeat || "",
    ends: initial.ends || "never",
    date: initial.date || "",
    scope: "this",

    init() {
      this.relabel();
      this.$watch("date", (value, previous) => {
        this.relabel();
        this.followWeekday(parseDay(previous), parseDay(value));
      });
    },

    relabel() {
      const labels = repeatLabels(parseDay(this.date));
      this.$root.querySelectorAll('select[name="repeat"] option').forEach((option) => {
        if (labels[option.value]) {
          option.textContent = labels[option.value];
        }
      });
    },

    // A weekly repeat starts on the date's weekday; when the date moves and
    // that is still the only day ticked, the tick moves with it
    followWeekday(previous, current) {
      if (!previous || !current) {
        return;
      }
      const boxes = [...this.$root.querySelectorAll('input[name="weekdays"]')];
      const ticked = boxes.filter((box) => box.checked).map((box) => Number(box.value));
      if (ticked.length === 1 && ticked[0] === weekdayOf(previous)) {
        boxes.forEach((box) => {
          box.checked = Number(box.value) === weekdayOf(current);
        });
      }
    },
  }));


  /**
   * Dropdown Component
   * Usage: <div class="dropdown" x-data="dropdown()">
   *          <button x-ref="button" @click="toggle()" :aria-expanded="open">
   *          <ul class="dropdown-menu" x-ref="menu" x-show="open" @click="close()">
   */
  Alpine.data('dropdown', () => ({
    open: false,

    toggle() {
      if (this.open) {
        this.close();
      } else {
        this.openDropdown();
      }
    },

    openDropdown() {
      // Close any other open dropdowns first
      document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
        menu.classList.remove('show');
      });

      this.open = true;
      this.$nextTick(() => {
        this.position();
        this.$refs.menu?.classList.add('show');
      });
    },

    close() {
      this.open = false;
      this.$refs.menu?.classList.remove('show');
      this.resetPosition();
    },

    position() {
      const menu = this.$refs.menu;
      const button = this.$refs.button;
      if (!menu || !button) return;

      const rect = button.getBoundingClientRect();

      // Use fixed positioning to escape overflow constraints
      menu.style.position = 'fixed';
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.left = `${rect.left}px`;
      menu.style.right = 'auto';
      menu.style.bottom = 'auto';
      menu.style.minWidth = `${rect.width}px`;

      // Check if menu would overflow viewport and adjust
      this.$nextTick(() => {
        const menuRect = menu.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;

        // Only flip up if menu truly doesn't fit below AND there's more room above
        if (menuRect.height > spaceBelow && spaceAbove > spaceBelow) {
          const flippedTop = rect.top - menuRect.height - 4;
          if (flippedTop >= 8) {
            menu.style.top = `${flippedTop}px`;
          } else {
            // Constrain to viewport
            menu.style.top = '8px';
            menu.style.maxHeight = `${rect.top - 16}px`;
            menu.style.overflowY = 'auto';
          }
        } else if (menuRect.bottom > window.innerHeight) {
          // Keep below but constrain height
          menu.style.maxHeight = `${spaceBelow - 16}px`;
          menu.style.overflowY = 'auto';
        }

        // Align to right edge if would overflow right
        if (menuRect.right > window.innerWidth - 8) {
          menu.style.left = 'auto';
          menu.style.right = `${window.innerWidth - rect.right}px`;
        }
      });
    },

    resetPosition() {
      const menu = this.$refs.menu;
      if (!menu) return;
      menu.style.position = '';
      menu.style.top = '';
      menu.style.left = '';
      menu.style.right = '';
      menu.style.bottom = '';
      menu.style.minWidth = '';
      menu.style.maxHeight = '';
      menu.style.overflowY = '';
    },

    // Close on click outside
    handleClickOutside(event) {
      if (this.open && !this.$el.contains(event.target)) {
        this.close();
      }
    },

    // Close on escape key
    handleEscape(event) {
      if (this.open && event.key === 'Escape') {
        this.close();
        this.$refs.button?.focus();
      }
    },

    // Close when clicking any link or button inside the menu
    handleMenuClick(event) {
      const clickedElement = event.target.closest('a, button');
      if (clickedElement && this.$refs.menu?.contains(clickedElement)) {
        this.close();
      }
    },

    init() {
      // Bind event listeners
      this._clickOutsideHandler = this.handleClickOutside.bind(this);
      this._escapeHandler = this.handleEscape.bind(this);
      this._menuClickHandler = this.handleMenuClick.bind(this);

      document.addEventListener('click', this._clickOutsideHandler);
      document.addEventListener('keydown', this._escapeHandler);
      this.$el.addEventListener('click', this._menuClickHandler);
    },

    destroy() {
      document.removeEventListener('click', this._clickOutsideHandler);
      document.removeEventListener('keydown', this._escapeHandler);
      this.$el.removeEventListener('click', this._menuClickHandler);
    }
  }));


  /**
   * Modal Component
   * Usage: Applied to #htmx-modal-container
   * Listens for custom events: 'open-modal', 'close-modal'
   */
  Alpine.data('modal', () => ({
    isOpen: false,

    open() {
      if (this.isOpen) return;
      this.isOpen = true;

      // Add backdrop
      let backdrop = document.querySelector('.modal-backdrop');
      if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop fade show';
        document.body.appendChild(backdrop);
      }

      this.$el.classList.add('show');
      this.$el.style.display = 'block';
      document.body.style.overflow = 'hidden';
      document.body.classList.add('modal-open');

      // Focus first autofocus element or first focusable
      this.$nextTick(() => {
        const autofocus = this.$el.querySelector('[autofocus]');
        if (autofocus) {
          autofocus.focus();
        }
      });
    },

    close() {
      if (!this.isOpen) return;
      this.isOpen = false;
      this.$el.classList.remove('show');

      // Remove backdrop
      const backdrop = document.querySelector('.modal-backdrop');
      if (backdrop) backdrop.remove();

      // Allow fade transition
      setTimeout(() => {
        this.$el.style.display = 'none';
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
        // Clear modal content
        this.$el.innerHTML = '';
      }, 150);
    },

    init() {
      // Listen for custom events
      window.addEventListener('open-modal', () => this.open());
      window.addEventListener('close-modal', () => this.close());
    }
  }));


  /**
   * Menu Drawer Component
   * Mobile slide-in panel holding the site's pages (the nav bar collapses
   * into a floating button on small screens)
   * Usage: <div x-data="navDrawer()">
   */
  Alpine.data('navDrawer', () => ({
    isOpen: false,

    toggle() {
      this.isOpen ? this.close() : this.open();
    },

    open() {
      this.isOpen = true;
      this.$el.querySelector('.drawer-backdrop')?.classList.add('open');
      document.body.style.overflow = 'hidden';
    },

    close() {
      this.isOpen = false;
      this.$el.querySelector('.drawer-backdrop')?.classList.remove('open');
      document.body.style.overflow = '';
    },

    init() {
      attachDrawerSwipe(this, {
        panel: () => this.$el.querySelector('.nav-drawer'),
        backdrop: this.$el.querySelector('.drawer-backdrop'),
        side: 'left',
      });

      // Close if the viewport grows past the mobile breakpoint while open
      window.matchMedia('(min-width: 992px)').addEventListener('change', (e) => {
        if (e.matches && this.isOpen) {
          this.close();
        }
      });
    }
  }));


  /**
   * Side Drawer Component
   * On a phone, a sheet rising from the bottom for whatever the page
   * marks with data-drawer: the folder sidebar, or the settings section
   * nav. Its button sits at the bottom left, under the thumb.
   * Usage: <div x-data="sideDrawer()">
   */
  Alpine.data('sideDrawer', () => ({
    isOpen: false,
    hasPanel: false,

    // Swipe state
    _touch: null,

    toggle() {
      this.isOpen ? this.close() : this.open();
    },

    open() {
      const panel = document.querySelector('[data-drawer]');
      if (!panel) return;
      this.isOpen = true;
      panel.classList.add('drawer-open');
      this.$el.querySelector('.drawer-backdrop')?.classList.add('open');
      document.body.style.overflow = 'hidden';
    },

    close() {
      const panel = document.querySelector('[data-drawer]');
      if (!panel) return;
      this.isOpen = false;
      panel.classList.remove('drawer-open');
      this.$el.querySelector('.drawer-backdrop')?.classList.remove('open');
      document.body.style.overflow = '';
    },

    init() {
      this.hasPanel = !!document.querySelector('[data-drawer]');
      if (!this.hasPanel) return;

      // Looked up on each use: a page may swap the panel's contents, and
      // must never be left dragging an element that is no longer there.
      const sidebarEl = () => document.querySelector('[data-drawer]');
      const mql = window.matchMedia('(min-width: 992px)');
      attachDrawerSwipe(this, {
        panel: sidebarEl,
        backdrop: this.$el.querySelector('.drawer-backdrop'),
        side: 'bottom',
      });

      // Auto-close the drawer when a link inside it is tapped (htmx navigation)
      document.addEventListener('htmx:beforeRequest', (e) => {
        if (this.isOpen && e.detail.elt.closest('[data-drawer]')) {
          this.close();
        }
      });

      // Clean up if viewport crosses 992px while drawer is open
      mql.addEventListener('change', (e) => {
        if (e.matches && this.isOpen) {
          this.close();
        }
      });
    }
  }));


  /**
   * Confirm Modal Component
   * A styled replacement for browser's native confirm() dialog
   * Usage: Applied to #confirm-modal-container
   */
  Alpine.data('confirmModal', () => ({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    isDangerous: false,
    onConfirm: null,
    onCancel: null,

    show(options) {
      this.title = options.title || 'Confirm';
      this.message = options.message || 'Are you sure?';
      this.confirmText = options.confirmText || 'Confirm';
      this.cancelText = options.cancelText || 'Cancel';
      this.isDangerous = options.isDangerous !== false;
      this.onConfirm = options.onConfirm || null;
      this.onCancel = options.onCancel || null;
      this.isOpen = true;

      // Focus the cancel button by default for safety
      this.$nextTick(() => {
        const cancelBtn = this.$el.querySelector('.confirm-modal-cancel');
        if (cancelBtn) cancelBtn.focus();
      });
    },

    confirm() {
      this.isOpen = false;
      if (this.onConfirm) this.onConfirm();
      this.reset();
    },

    cancel() {
      this.isOpen = false;
      if (this.onCancel) this.onCancel();
      this.reset();
    },

    reset() {
      this.onConfirm = null;
      this.onCancel = null;
    },

    handleKeydown(event) {
      if (!this.isOpen) return;
      if (event.key === 'Escape') {
        this.cancel();
      } else if (event.key === 'Enter') {
        // Only confirm on Enter if the confirm button is focused
        if (document.activeElement?.classList.contains('confirm-modal-confirm')) {
          this.confirm();
        }
      }
    }
  }));

});


/**
 * HTMX Integration for Modal
 * Replaces Bootstrap modal hooks in main.js
 */
document.addEventListener('DOMContentLoaded', () => {

  // Helper to check if target is the modal container
  function isModalTarget(target) {
    if (!target) return false;
    return target.id === 'htmx-modal-container' ||
           target.id === 'htmx-modal-content' ||
           target.closest('#htmx-modal-container');
  }

  // Open modal when HTMX swaps content into modal container
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (isModalTarget(e.detail.target) && e.detail.xhr.response) {
      // Small delay to ensure Alpine has processed new content
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('open-modal'));
      }, 10);
    }
  });

  // Close modal on empty response
  document.body.addEventListener('htmx:beforeSwap', (e) => {
    if (isModalTarget(e.detail.target) && !e.detail.xhr.response) {
      window.dispatchEvent(new CustomEvent('close-modal'));
      e.detail.shouldSwap = false;
    }
  });

  // Close modal on 204 status (successful form submission, no content)
  document.body.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.xhr.status === 204) {
      window.dispatchEvent(new CustomEvent('close-modal'));
    }
  });

  // Intercept hx-confirm to use custom modal instead of browser confirm
  document.body.addEventListener('htmx:confirm', (e) => {
    if (!e.detail.question) {
      return;
    }

    const confirmModal = document.getElementById('confirm-modal');
    if (!confirmModal) {
      return;
    }

    e.preventDefault();

    const message = e.detail.question;
    const triggerEl = e.detail.elt;

    const title = triggerEl.dataset.confirmTitle || 'Confirm';
    const confirmText = triggerEl.dataset.confirmText || 'Delete';
    const cancelText = triggerEl.dataset.cancelText || 'Cancel';

    const component = Alpine.$data(confirmModal);
    component.show({
      title: title,
      message: message,
      confirmText: confirmText,
      cancelText: cancelText,
      isDangerous: true,
      onConfirm: () => {
        e.detail.issueRequest(true);
      }
    });
  });

});


/**
 * Global showConfirm() function
 * Promise-based replacement for browser's native confirm()
 */
/**
 * Search card navigation (delegated for HTMX compatibility)
 * Navigates to data-href on click, unless a link inside was clicked.
 */
document.addEventListener('click', function(e) {
  // Skip if a real link was clicked
  if (e.target.closest('a[href]')) return;

  const card = e.target.closest('.search-card[data-href]');
  if (!card) return;

  const href = card.getAttribute('data-href');
  if (card.getAttribute('data-target') === '_blank') {
    window.open(href, '_blank');
  } else {
    window.location.href = href;
  }
});


/**
 * Copy to clipboard (delegated for HTMX compatibility)
 */
document.addEventListener('click', function(e) {
  const copyBtn = e.target.closest('.copy-btn');
  if (!copyBtn) return;

  e.preventDefault();
  let data = copyBtn.getAttribute('data-copy');

  // If data-copy-target is specified, get text from target element
  const targetSelector = copyBtn.getAttribute('data-copy-target');
  if (targetSelector) {
    const targetElement = document.querySelector(targetSelector);
    if (targetElement) {
      data = targetElement.textContent.trim();
    }
  }

  navigator.clipboard.writeText(data).then(() => {
    const originalHtml = copyBtn.innerHTML;
    copyBtn.innerHTML = '<i class="icon-check"></i>';
    copyBtn.style.color = 'green';
    setTimeout(() => {
      copyBtn.innerHTML = originalHtml;
      copyBtn.style.color = '';
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy value: ', err);
  });
});


window.showConfirm = function(options) {
  return new Promise((resolve) => {
    const confirmModal = document.getElementById('confirm-modal');
    if (!confirmModal) {
      resolve(confirm(options.message || 'Are you sure?'));
      return;
    }

    const component = Alpine.$data(confirmModal);
    component.show({
      title: options.title || 'Confirm',
      message: options.message || 'Are you sure?',
      confirmText: options.confirmText || 'Confirm',
      cancelText: options.cancelText || 'Cancel',
      isDangerous: options.isDangerous !== false,
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false)
    });
  });
};
