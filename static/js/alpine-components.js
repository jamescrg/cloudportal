/**
 * Alpine.js Components
 * Replacement for Bootstrap JS dropdowns and modals
 */

document.addEventListener('alpine:init', () => {

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
   * Folder Drawer Component
   * Mobile slide-in drawer for the sidebar folder list
   * Usage: <div x-data="folderDrawer()">
   */
  Alpine.data('folderDrawer', () => ({
    isOpen: false,
    hasSidebar: false,

    // Swipe state
    _touch: null,

    toggle() {
      this.isOpen ? this.close() : this.open();
    },

    open() {
      const sidebar = document.getElementById('sidebar');
      if (!sidebar) return;
      this.isOpen = true;
      sidebar.classList.add('drawer-open');
      document.body.style.overflow = 'hidden';
    },

    close() {
      const sidebar = document.getElementById('sidebar');
      if (!sidebar) return;
      this.isOpen = false;
      sidebar.classList.remove('drawer-open');
      document.body.style.overflow = '';
    },

    init() {
      this.hasSidebar = !!document.getElementById('sidebar');
      if (!this.hasSidebar) return;

      const sidebar = document.getElementById('sidebar');
      const backdrop = this.$el.querySelector('.drawer-backdrop');
      const mql = window.matchMedia('(min-width: 992px)');
      const EDGE_ZONE = 24;        // px from left edge to start open-swipe
      const VELOCITY_THRESHOLD = 0.3; // px/ms — fast flick opens/closes
      const DISTANCE_RATIO = 0.35; // fraction of drawer width to snap

      const self = this;

      // --- helpers ---
      function drawerWidth() {
        return sidebar.offsetWidth || 280;
      }

      function applyTranslate(px) {
        // px: 0 = fully open, -drawerWidth = fully closed
        sidebar.style.transform = `translateX(${px}px)`;
        // Sync backdrop opacity: 0 when closed, 1 when open
        const progress = 1 + px / drawerWidth();
        backdrop.style.opacity = Math.max(0, Math.min(1, progress));
        backdrop.style.pointerEvents = progress > 0.05 ? 'auto' : 'none';
      }

      function clearDrag() {
        sidebar.classList.remove('drawer-dragging');
        sidebar.style.transform = '';
        backdrop.style.opacity = '';
        backdrop.style.pointerEvents = '';
        self._touch = null;
      }

      // --- touch handlers ---
      function onTouchStart(e) {
        if (mql.matches) return; // desktop
        const t = e.touches[0];

        if (!self.isOpen && t.clientX <= EDGE_ZONE) {
          // Begin open-swipe from left edge
          self._touch = { startX: t.clientX, startY: t.clientY, lastX: t.clientX, lastTime: e.timeStamp, mode: 'open', locked: false };
          sidebar.classList.add('drawer-dragging');
          backdrop.classList.add('open');
          document.body.style.overflow = 'hidden';
        } else if (self.isOpen && (t.clientX <= drawerWidth() || e.target.closest('.drawer-backdrop'))) {
          // Begin close-swipe on open drawer or backdrop
          self._touch = { startX: t.clientX, startY: t.clientY, lastX: t.clientX, lastTime: e.timeStamp, mode: 'close', locked: false };
          sidebar.classList.add('drawer-dragging');
        }
      }

      function onTouchMove(e) {
        const touch = self._touch;
        if (!touch) return;
        const t = e.touches[0];
        const dx = t.clientX - touch.startX;
        const dy = t.clientY - touch.startY;

        // Lock direction after 10px of movement
        if (!touch.locked) {
          if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
          // If more vertical than horizontal, abort swipe
          if (Math.abs(dy) > Math.abs(dx)) {
            clearDrag();
            if (!self.isOpen) {
              backdrop.classList.remove('open');
              document.body.style.overflow = '';
            }
            return;
          }
          touch.locked = true;
        }

        e.preventDefault();
        touch.lastX = t.clientX;
        touch.lastTime = e.timeStamp;

        const w = drawerWidth();
        if (touch.mode === 'open') {
          // dx goes 0 → w; translate goes -w → 0
          const offset = Math.min(0, Math.max(-w, dx - w));
          applyTranslate(offset);
        } else {
          // dx goes 0 → -w; translate goes 0 → -w
          const offset = Math.min(0, Math.max(-w, dx));
          applyTranslate(offset);
        }
      }

      function onTouchEnd(e) {
        const touch = self._touch;
        if (!touch) return;

        const dt = e.timeStamp - touch.lastTime || 1;
        const dx = touch.lastX - touch.startX;
        const velocity = dx / dt; // px/ms, positive = rightward
        const w = drawerWidth();

        clearDrag();

        if (touch.mode === 'open') {
          if (velocity > VELOCITY_THRESHOLD || dx > w * DISTANCE_RATIO) {
            self.isOpen = true;
            sidebar.classList.add('drawer-open');
          } else {
            backdrop.classList.remove('open');
            document.body.style.overflow = '';
          }
        } else {
          if (velocity < -VELOCITY_THRESHOLD || -dx > w * DISTANCE_RATIO) {
            self.isOpen = false;
            sidebar.classList.remove('drawer-open');
            backdrop.classList.remove('open');
            document.body.style.overflow = '';
          }
        }
      }

      document.addEventListener('touchstart', onTouchStart, { passive: true });
      document.addEventListener('touchmove', onTouchMove, { passive: false });
      document.addEventListener('touchend', onTouchEnd, { passive: true });

      // Auto-close drawer when a folder link is tapped (htmx navigation)
      document.addEventListener('htmx:beforeRequest', (e) => {
        if (this.isOpen && e.detail.elt.closest('#sidebar')) {
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
