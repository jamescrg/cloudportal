/**
 * FullCalendar Integration for the Calendar page
 * Alpine.js component for calendar initialization and interaction
 */

// The container that hosts the calendar (templates/calendar/content.html)
const CALENDAR_CONTAINER_ID = "events";

// Alpine initializes content htmx swaps in on its own (it watches the
// DOM), so the calendar's x-init runs once for each new container. No
// manual Alpine.initTree here: that ran x-init a second time and built a
// second grid inside the first.

// Phones get the grid's agenda view (listRolling) in place of both the
// month grid, which is unusable at that width, and the table list, which
// is not laid out for it.
const PHONE_WIDTH = 768;

function onPhone() {
  return window.innerWidth <= PHONE_WIDTH;
}

// The day the page was asked to open on (the home page's week strip
// links each day here as ?date=YYYY-MM-DD); null when it was not.
function requestedDate() {
  const date = new URLSearchParams(window.location.search).get("date");
  return date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null;
}

// If a phone lands on the table (the saved view is the list), fetch the
// calendar partial in its place; the saved view is left alone for the
// desktop. The partial's x-init then builds the agenda.
function preferAgendaOnPhone(container) {
  if (!onPhone() || !window.htmx) {
    return;
  }
  if (container && container.querySelector(".events-table")) {
    window.htmx.ajax("GET", "/calendar/calendar/", {
      target: "#" + CALENDAR_CONTAINER_ID,
      swap: "innerHTML",
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  preferAgendaOnPhone(document.getElementById(CALENDAR_CONTAINER_ID));
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === CALENDAR_CONTAINER_ID) {
    preferAgendaOnPhone(event.detail.target);
  }
});

// Track when we're intentionally switching views
let viewSwitchPending = false;

document.body.addEventListener("eventsViewChanged", () => {
  viewSwitchPending = true;
});

// In calendar mode, intercept auto-refresh triggers and refetch instead of
// reloading. Requests from buttons/links targeting #events are allowed through.
document.body.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail.target;
  if (target && target.id === CALENDAR_CONTAINER_ID) {
    const calendarContainer = document.querySelector(".fullcalendar-container");
    if (calendarContainer && window.Alpine) {
      const elt = event.detail.elt;

      // If the request originates from the container div itself (auto-refresh),
      // block it and refetch calendar events instead - unless it's a view switch
      if (elt.id === target.id) {
        if (viewSwitchPending) {
          viewSwitchPending = false;
          return; // Allow view mode switch through
        }

        // Block auto-refresh and refetch calendar instead
        const alpineData = Alpine.$data(calendarContainer);
        if (alpineData && alpineData.calendar) {
          event.preventDefault();
          alpineData.calendar.refetchEvents();
        }
      }
    }
  }
});

// A repeating event shows its rule in words when hovered
function markRepeats(info) {
  const repeats = (info.event.extendedProps || {}).repeats;
  if (repeats) {
    info.el.title = `${info.event.title} · ${repeats}`;
  }
}

// The views drawn as the month grid is: the month, and the home page's week
const MONTH_GRIDS = ["dayGridMonth", "homeWeek"];

// A task's box is an element of its own, so a click on it can be told
// from a click on the rest of the chip: the box marks the task done, the
// chip opens it. It goes where the dot would be in the agenda, and before
// the title everywhere else.
function addTaskBox(info) {
  if ((info.event.extendedProps || {}).kind !== "task") {
    return;
  }
  const host =
    info.el.querySelector(".fc-list-event-graphic") ||
    info.el.querySelector(".fc-event-title");
  if (!host || host.querySelector(".fc-task-box")) {
    return;
  }
  const box = document.createElement("span");
  box.className = "fc-task-box";
  box.setAttribute("role", "button");
  box.setAttribute("aria-label", `Mark "${info.event.title}" done`);
  box.title = "Mark done";
  host.prepend(box);
  // An overdue task gathered on today (the home page) is dated after its
  // box, or in the agenda, where the box has a column, before its title
  const due = info.event.extendedProps.due_label;
  if (due) {
    const label = document.createElement("span");
    label.className = "fc-task-due";
    label.textContent = due;
    const title = info.el.querySelector(".fc-list-event-title a");
    if (title) {
      title.prepend(label);
    } else {
      box.after(label);
    }
  }
}

// In the month grid a chip's title stops at two lines (app-calendar.css).
// A timed entry's time goes inside its title, after a task's box, so the
// two are cut together as one run of text, and a title cut short is read
// whole on hover.
function fitMonthChip(info) {
  if (!MONTH_GRIDS.includes(info.view.type)) {
    return;
  }
  if (!info.el.title) {
    info.el.title = info.event.title;
  }
  const time = info.el.querySelector(".fc-event-time");
  const title = info.el.querySelector(".fc-event-title");
  if (!time || !title || !info.el.classList.contains("fc-daygrid-dot-event")) {
    return;
  }
  const box = title.querySelector(".fc-task-box");
  if (box) {
    box.after(time);
  } else {
    title.prepend(time);
  }
}

// Where an entry stands in its day, for the calendar's order: the events
// first, then the tasks, led by any overdue ones the home page's card
// gathers on today. FullCalendar hands its order function the entry with
// its extended props, by version either under extendedProps or spread
// onto it.
function entryRank(entry) {
  const props = entry.extendedProps || entry;
  if (props.kind !== "task") {
    return 0;
  }
  return props.overdue ? 1 : 2;
}

function onEventMount(info) {
  markRepeats(info);
  addTaskBox(info);
  fitMonthChip(info);
}

document.addEventListener("alpine:init", () => {
  // Options, all optional:
  //   apiUrl — the feed (default: the calendar's own)
  //   week   — the home page's calendar card: one week of the month grid
  //            (the agenda on a phone), stepped by the card's own heading
  // The grid is built in the x-ref "grid" when there is one (the home
  // card, whose heading is outside it), else in the component's own
  // element.
  Alpine.data("eventsCalendar", (opts = {}) => ({
    calendar: null,
    apiUrl: opts.apiUrl || "/calendar/api/",
    addUrl: "/calendar/add",
    week: Boolean(opts.week),
    weekRange: "",
    isCurrentWeek: true,
    menuOpen: false,
    menuButton: null,

    init() {
      // The menu closes on a click anywhere else, on Escape, and on a
      // choice from it (a link; a checkbox row keeps it open for the next)
      this._closeOnOutsideClick = (event) => {
        if (
          this.menuOpen &&
          !this.$refs.menu.contains(event.target) &&
          !(this.menuButton && this.menuButton.contains(event.target))
        ) {
          this.closeMenu();
        }
      };
      this._closeOnEscape = (event) => {
        if (this.menuOpen && event.key === "Escape") {
          this.closeMenu();
          this.menuButton?.focus();
        }
      };
      document.addEventListener("click", this._closeOnOutsideClick);
      document.addEventListener("keydown", this._closeOnEscape);
    },

    destroy() {
      document.removeEventListener("click", this._closeOnOutsideClick);
      document.removeEventListener("keydown", this._closeOnEscape);
    },

    openAdd() {
      htmx.ajax("GET", this.addUrl, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      });
    },

    toggleMenu(button) {
      if (this.menuOpen) {
        this.closeMenu();
        return;
      }
      this.menuButton = button;
      this.menuOpen = true;
      button.classList.add("fc-button-active");
      this.$nextTick(() => this.positionMenu());
    },

    closeMenu() {
      this.menuOpen = false;
      this.menuButton?.classList.remove("fc-button-active");
      const menu = this.$refs.menu;
      menu.classList.remove("show");
      menu.style.display = "";
      menu.style.position = "";
      menu.style.top = "";
      menu.style.left = "";
      menu.style.right = "";
    },

    // Fixed under the button, as the site's dropdowns are: its left edge
    // on the button's, or its right edge on the button's where the
    // viewport's edge is near (a phone)
    positionMenu() {
      const menu = this.$refs.menu;
      const rect = this.menuButton.getBoundingClientRect();
      menu.classList.add("show");
      // shown here, not left to x-show's own turn, so the width is real
      menu.style.display = "block";
      menu.style.position = "fixed";
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.right = "auto";
      const width = menu.offsetWidth;
      const left =
        rect.left + width > window.innerWidth - 8 ? rect.right - width : rect.left;
      menu.style.left = `${Math.max(8, left)}px`;
    },

    closeMenuOnChoice(event) {
      if (event.target.closest("a")) {
        this.closeMenu();
      }
    },

    initCalendar() {
      const calendarEl = this.$refs.grid || this.$el;
      // Never build twice into one element (FullCalendar marks it "fc")
      if (calendarEl.classList.contains("fc")) {
        return;
      }
      const phone = onPhone();

      this.calendar = new FullCalendar.Calendar(calendarEl, {
        ...this.calendarOptions(phone),
        ...(this.week ? this.weekOptions(phone) : {}),
      });

      this.calendar.render();

      // Listen for filter changes to refresh calendar
      document.body.addEventListener("eventsChanged", () => {
        this.calendar.refetchEvents();
      });
      // A task edited from the grid re-draws the tasks on it
      document.body.addEventListener("tasksChanged", () => {
        this.calendar.refetchEvents();
      });
    },

    // The home page's calendar card over the calendar's own options: a
    // week of the month grid, Sunday first (the agenda on a phone), with
    // no toolbar (the card's heading steps it) and the heading's span kept
    // in step. A day's number opens the calendar on that day, and a day
    // shows five rows before the rest fold into "+N more".
    weekOptions(phone) {
      return {
        initialView: phone ? "homeAgenda" : "homeWeek",
        initialDate: undefined,
        headerToolbar: false,
        dayMaxEvents: false,
        dayMaxEventRows: 5,
        views: {
          homeWeek: {
            type: "dayGrid",
            duration: { weeks: 1 },
            dayHeaderFormat: { weekday: "short" },
            // one row of days carries no numbers of its own; this puts
            // the month view's back
            dayCellContent: (arg) => String(arg.date.getDate()),
          },
          homeAgenda: {
            type: "list",
            duration: { weeks: 1 },
            listDayFormat: { weekday: "short", month: "short", day: "numeric" },
            listDaySideFormat: false,
            displayEventEnd: false,
            eventTimeFormat: {
              hour: "numeric",
              minute: "2-digit",
              omitZeroMinute: true,
              meridiem: "short",
            },
            noEventsContent: "Nothing on the calendar this week.",
          },
        },
        navLinkDayClick: (date) => {
          window.location.href = `/calendar/?date=${this.formatDate(date)}`;
        },
        // the view is the card's, not a choice to carry to the calendar
        datesSet: (info) => this.setWeekHeading(info),
        windowResize: undefined,
      };
    },

    // The card's span (Oct 11 – 17, Oct 25 – Nov 1, the year when it is
    // not this one) and whether the week holds today, for This Week
    setWeekHeading(info) {
      const first = info.view.currentStart;
      const last = new Date(info.view.currentEnd);
      last.setDate(last.getDate() - 1);
      const month = (date) => date.toLocaleString("en-US", { month: "short" });
      let range = `${month(first)} ${first.getDate()} – `;
      range +=
        last.getMonth() === first.getMonth()
          ? `${last.getDate()}`
          : `${month(last)} ${last.getDate()}`;
      const year = new Date().getFullYear();
      if (first.getFullYear() !== year || last.getFullYear() !== year) {
        range += `, ${last.getFullYear()}`;
      }
      this.weekRange = range;
      const now = new Date();
      this.isCurrentWeek =
        now >= info.view.currentStart && now < info.view.currentEnd;
    },

    calendarOptions(phone) {
      return {
        // Core settings. A phone opens the month's agenda with a toolbar
        // pared to navigation; wider screens get the full set of views,
        // the agenda among them.
        initialView: phone ? "listRolling" : this.savedView(),
        ...(requestedDate() ? { initialDate: requestedDate() } : {}),
        // The calendar's own tools ride the toolbar: Add beside the
        // navigation, and the menu (the overlays, Filter, the list view)
        // behind a sliders button before the views. Both are drawn by
        // FullCalendar and iconed in CSS.
        headerToolbar: phone
          ? { left: "prev,next add", center: "title", right: "menu today" }
          : {
              left: "prev,next today add",
              center: "title",
              right:
                "menu multiMonthRolling,dayGridMonth,timeGridWeek,timeGridDay,listRolling",
            },
        customButtons: {
          add: {
            text: "",
            hint: "Add Event",
            click: () => this.openAdd(),
          },
          menu: {
            text: "",
            hint: "Show…",
            click: (event, button) => this.toggleMenu(button),
          },
        },
        noEventsContent: "No events",

        // The year view: the next twelve months as mini months, three
        // across, from the month in view rather than from January, so in
        // October it looks a year ahead rather than mostly back. Its cells
        // are small, so fewer events show before a day collapses to "+N
        // more".
        views: {
          multiMonthRolling: {
            type: "multiMonth",
            duration: { months: 12 },
            dateAlignment: "month",
            buttonText: "Year",
            dayMaxEvents: 2,
          },
          // Month scrolls with the page, where FullCalendar would pin its
          // weekday row to the window's top with nothing behind it
          dayGridMonth: {
            stickyHeaderDates: false,
          },
          // The agenda (the phone's only view, a choice on wider screens):
          // the month ahead from the day in view, so it opens on today and
          // runs forward rather than opening on the calendar month's first
          // event; prev and next step a month. A compact day heading, and
          // start times only, abbreviated where they can be ("7am",
          // "7:30am"), so the title keeps most of the row
          listRolling: {
            type: "list",
            duration: { months: 1 },
            // a month's duration aligns to the month unless told otherwise
            dateAlignment: "day",
            buttonText: "Agenda",
            // the span's title ("October – November 2026") is cut to fit
            // a phone's toolbar
            ...(phone ? { titleFormat: { month: "short", year: "numeric" } } : {}),
            listDayFormat: { weekday: "short", month: "short", day: "numeric" },
            listDaySideFormat: false,
            displayEventEnd: false,
            eventTimeFormat: {
              hour: "numeric",
              minute: "2-digit",
              omitZeroMinute: true,
              meridiem: "short",
            },
            // The last day of a timed event that runs over several days
            // would read "12am" (that day's share starts at midnight); it
            // reads "until 3pm" instead
            eventDidMount: (info) => {
              onEventMount(info);
              if (info.isStart || !info.isEnd || info.event.allDay) {
                return;
              }
              const cell = info.el.querySelector(".fc-list-event-time");
              if (cell && info.event.end) {
                const end = info.view.calendar.formatDate(info.event.end, {
                  hour: "numeric",
                  minute: "2-digit",
                  omitZeroMinute: true,
                  meridiem: "short",
                });
                cell.textContent = `until ${end}`;
              }
            },
          },
        },

        // Every other view: the repeat tooltip and a task's box (the
        // agenda sets its own, above)
        eventDidMount: onEventMount,

        // Event source - JSON API
        events: {
          url: this.apiUrl,
          method: "GET",
          failure: function () {
            console.error("Failed to load events");
          },
        },

        // A day's events come before its tasks, then FullCalendar's own
        // order within each (by start, longest first, all-day first, by
        // title)
        eventOrder: [
          (a, b) => entryRank(a) - entryRank(b),
          "start",
          "-duration",
          "allDay",
          "title",
        ],

        // Drag and drop
        editable: true,
        eventStartEditable: true,
        eventDurationEditable: true,

        // Event handlers
        eventClick: (info) => this.handleEventClick(info),
        eventDrop: (info) => this.handleEventDrop(info),
        eventResize: (info) => this.handleEventResize(info),
        dateClick: (info) => this.handleDateClick(info),

        // All-day entries carry a class of their own, so the agenda can
        // leave their dot off (a dot marks a timed entry, as on the grid)
        eventClassNames: (arg) => (arg.event.allDay ? ["fc-event-all-day"] : []),

        // Display settings
        nowIndicator: true,
        dayMaxEvents: true,
        navLinks: true,

        // Responsive
        height: "auto",

        // Week/Day views cap the grid to the viewport so the wheel scrolls
        // FullCalendar's internal scroller (sticky day headers) instead of
        // the whole page; month keeps auto height. datesSet also fires on
        // every view switch, so it doubles as the persistence hook.
        datesSet: (info) => {
          this.applyViewHeight(info.view.type);
          // The agenda is the phone's view, not a choice to carry over
          if (!phone) {
            localStorage.setItem("calendar-view", info.view.type);
          }
        },
        windowResize: () => this.applyViewHeight(this.calendar.view.type),

        themeSystem: "standard",
      };
    },

    savedView() {
      // Reopen in the last-used view (year/month/week/day/agenda). Validate against
      // the real view names so a stale or hand-edited value can't break the
      // render.
      const saved = localStorage.getItem("calendar-view");
      const valid = [
        "multiMonthRolling",
        "dayGridMonth",
        "timeGridWeek",
        "timeGridDay",
        "listRolling",
      ];
      // The agenda was listMonth before it rolled from the day in view
      if (saved === "listMonth") {
        return "listRolling";
      }
      return valid.includes(saved) ? saved : "dayGridMonth";
    },

    applyViewHeight(viewType) {
      let height = "auto";
      if (viewType.startsWith("timeGrid")) {
        // Fit the calendar between its natural page position and the bottom
        // of the viewport, so the time grid gets an internal scroller. The
        // card around it keeps its own padding and margin below, as on any
        // other page. Floor keeps it usable on short windows.
        const offsetTop =
          this.$el.getBoundingClientRect().top + window.scrollY;
        const card = this.$el.closest(".card");
        const below = card
          ? parseFloat(getComputedStyle(card).paddingBottom) +
            parseFloat(getComputedStyle(card).marginBottom)
          : 16;
        height = Math.max(480, window.innerHeight - offsetTop - below);
      }
      if (this.calendar.getOption("height") !== height) {
        this.calendar.setOption("height", height);
      }
    },

    handleEventClick(info) {
      info.jsEvent.preventDefault();
      info.jsEvent.stopPropagation();

      // Open the edit modal using HTMX; alpine-components.js opens the
      // modal when the content lands in the container. A task on the grid
      // opens the task form instead.
      const props = info.event.extendedProps || {};
      // A holiday is a date, not a record: nothing to open
      if (props.kind === "holiday") {
        return;
      }
      // A Kosmos event lives in Kosmos: it opens there, in a new tab
      if (props.kind === "kosmos") {
        if (props.url) {
          window.open(props.url, "_blank", "noopener");
        }
        return;
      }
      // A task's box marks it done; it leaves the grid, which shows only
      // open tasks, at once, and comes back if the server says no
      if (props.kind === "task" && info.jsEvent.target.closest(".fc-task-box")) {
        this.completeTask(info.event);
        return;
      }
      const url =
        props.kind === "task"
          ? `/tasks/${props.task_id}/form`
          : `/calendar/${info.event.id}/edit`;
      htmx.ajax("GET", url, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      });
    },

    completeTask(event) {
      const taskId = event.extendedProps.task_id;
      event.remove();
      fetch(`/tasks/${taskId}/done`, {
        method: "POST",
        headers: { "X-CSRFToken": this.getCsrfToken() },
      })
        .then((response) => {
          if (response.ok) {
            // the task list, where it is on the page, redraws too
            htmx.trigger(document.body, "tasksChanged");
          } else {
            this.calendar.refetchEvents();
          }
        })
        .catch(() => this.calendar.refetchEvents());
    },

    handleEventDrop(info) {
      // Reschedule event via quick-update endpoint
      this.quickUpdate(info.event.id, this.datesAndTimes(info.event), info);
    },

    handleEventResize(info) {
      // Update duration via quick-update endpoint
      this.quickUpdate(info.event.id, this.datesAndTimes(info.event), info);
    },

    datesAndTimes(event) {
      // The date, end date and times an event now has, as the server takes
      // them. FullCalendar's end is exclusive, so an all-day event's end
      // date is the day before its end; a one-day event has no end date.
      const date = this.formatDate(event.start);
      const updateData = { date, end_date: null, time_zone: this.browserZone() };

      if (event.allDay) {
        updateData.start_time = null;
        updateData.end_time = null;
        if (event.end) {
          const last = new Date(event.end);
          last.setDate(last.getDate() - 1);
          const lastDate = this.formatDate(last);
          if (lastDate > date) {
            updateData.end_date = lastDate;
          }
        }
      } else {
        updateData.start_time = this.formatTime(event.start);
        if (event.end) {
          updateData.end_time = this.formatTime(event.end);
          const endDate = this.formatDate(event.end);
          if (endDate > date) {
            updateData.end_date = endDate;
          }
        }
      }

      return updateData;
    },

    handleDateClick(info) {
      // Open add modal with pre-filled date. A click on a Week or Day time
      // slot carries its time too; info.dateStr is then a full date-time,
      // so the date and the start time are sent as separate values.
      let query = `date=${this.formatDate(info.date)}`;
      if (!info.allDay) {
        query += `&start_time=${this.formatTime(info.date).slice(0, 5)}`;
      }
      htmx.ajax("GET", `${this.addUrl}?${query}`, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      });
    },

    browserZone() {
      // The zone the dragged-to wall-clock times are in: the browser's
      try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
      } catch (e) {
        return null;
      }
    },

    formatDate(date) {
      // Format as YYYY-MM-DD
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    },

    formatTime(date) {
      // Format as HH:MM:SS
      const hours = String(date.getHours()).padStart(2, "0");
      const minutes = String(date.getMinutes()).padStart(2, "0");
      const seconds = String(date.getSeconds()).padStart(2, "0");
      return `${hours}:${minutes}:${seconds}`;
    },

    quickUpdate(eventId, data, info) {
      const csrfToken = this.getCsrfToken();

      // A task dragged to another day keeps only its new date
      const props = info.event.extendedProps || {};
      if (props.kind === "task") {
        const form = new FormData();
        form.append("due_date", data.date);
        fetch(`/tasks/${props.task_id}/due-date`, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body: form,
        })
          .then((response) => {
            if (response.ok) {
              this.redrawMoved();
            } else {
              info.revert();
            }
          })
          .catch(() => info.revert());
        return;
      }

      fetch(`/calendar/${eventId}/quick-update`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(data),
      })
        .then((response) => {
          if (response.ok) {
            this.redrawMoved();
          } else {
            // Revert on failure
            info.revert();
            console.error("Failed to update event");
          }
        })
        .catch((error) => {
          info.revert();
          console.error("Error updating event:", error);
        });
    },

    // A moved entry is redrawn from the feed: FullCalendar redraws a moved
    // chip's insides in place, which puts back what the mount hooks
    // arranged (a timed entry's time inside its title, in the month grid)
    redrawMoved() {
      this.calendar.refetchEvents();
    },

    getCsrfToken() {
      // Try to get from body hx-headers attribute
      const hxHeaders = document.body.getAttribute("hx-headers");
      if (hxHeaders) {
        try {
          const headers = JSON.parse(hxHeaders);
          if (headers["X-CSRFToken"]) {
            return headers["X-CSRFToken"];
          }
        } catch (e) {
          console.error("Failed to parse hx-headers", e);
        }
      }

      // Fallback to cookie
      const name = "csrftoken";
      const cookies = document.cookie.split(";");
      for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name + "=")) {
          return cookie.substring(name.length + 1);
        }
      }
      return "";
    },

    destroy() {
      if (this.calendar) {
        this.calendar.destroy();
      }
    },
  }));
});
