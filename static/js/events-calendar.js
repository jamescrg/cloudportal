/**
 * FullCalendar Integration for the Calendar page
 * Alpine.js component for calendar initialization and interaction
 */

// The container that hosts the calendar (templates/calendar/content.html)
const CALENDAR_CONTAINER_ID = "events";

// Reinitialize Alpine on HTMX swaps for the events container
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (
    event.detail.target.id === CALENDAR_CONTAINER_ID &&
    typeof Alpine !== "undefined"
  ) {
    // Small delay to ensure DOM is ready
    setTimeout(() => {
      Alpine.initTree(event.detail.target);
    }, 10);
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
    const calendarContainer = document.getElementById("fullcalendar-container");
    if (calendarContainer && calendarContainer._x_dataStack) {
      const elt = event.detail.elt;

      // If the request originates from the container div itself (auto-refresh),
      // block it and refetch calendar events instead - unless it's a view switch
      if (elt.id === target.id) {
        if (viewSwitchPending) {
          viewSwitchPending = false;
          return; // Allow view mode switch through
        }

        // Block auto-refresh and refetch calendar instead
        const alpineData = calendarContainer._x_dataStack[0];
        if (alpineData && alpineData.calendar) {
          event.preventDefault();
          alpineData.calendar.refetchEvents();
        }
      }
    }
  }
});

document.addEventListener("alpine:init", () => {
  Alpine.data("eventsCalendar", () => ({
    calendar: null,
    apiUrl: "/calendar/api/",
    addUrl: "/calendar/add",

    initCalendar() {
      // On mobile the FullCalendar grid is unusable, so render the list
      // instead. Switch the saved view to "list" with htmx.ajax (the 204
      // response's HX-Trigger: eventsViewChanged makes #events re-fetch
      // list.html; the session then persists 'list', so later loads render it
      // directly). The request is issued here rather than by clicking the
      // hidden toggle button — that relied on htmx having already wired the
      // button up, which races with this x-init and left the panel blank. If
      // the toggle can't be found we fall through and build the grid, so
      // events are never missing.
      if (window.innerWidth <= 768) {
        const listUrl = document
          .querySelector('.view-toggle button[title="List View"]')
          ?.getAttribute("hx-post");
        if (listUrl) {
          window.htmx.ajax("POST", listUrl, { swap: "none" });
          return;
        }
      }

      const calendarEl = this.$el;

      this.calendar = new FullCalendar.Calendar(calendarEl, {
        // Core settings
        initialView: this.savedView(),
        headerToolbar: {
          left: "prev,next today",
          center: "title",
          right: "multiMonthYear,dayGridMonth,timeGridWeek,timeGridDay",
        },

        // The year view: twelve mini months, three across. Its cells are
        // small, so fewer events show before a day collapses to "+N more".
        views: {
          multiMonthYear: {
            dayMaxEvents: 2,
          },
        },

        // Event source - JSON API
        events: {
          url: this.apiUrl,
          method: "GET",
          failure: function () {
            console.error("Failed to load events");
          },
        },

        // Drag and drop
        editable: true,
        eventStartEditable: true,
        eventDurationEditable: true,

        // Event handlers
        eventClick: (info) => this.handleEventClick(info),
        eventDrop: (info) => this.handleEventDrop(info),
        eventResize: (info) => this.handleEventResize(info),
        dateClick: (info) => this.handleDateClick(info),

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
          localStorage.setItem("calendar-view", info.view.type);
        },
        windowResize: () => this.applyViewHeight(this.calendar.view.type),

        themeSystem: "standard",
      });

      this.calendar.render();

      // Listen for filter changes to refresh calendar
      document.body.addEventListener("eventsChanged", () => {
        this.calendar.refetchEvents();
      });
    },

    savedView() {
      // Reopen in the last-used view (year/month/week/day). Validate against
      // the real view names so a stale or hand-edited value can't break the
      // render.
      const saved = localStorage.getItem("calendar-view");
      const valid = [
        "multiMonthYear",
        "dayGridMonth",
        "timeGridWeek",
        "timeGridDay",
      ];
      return valid.includes(saved) ? saved : "dayGridMonth";
    },

    applyViewHeight(viewType) {
      let height = "auto";
      if (viewType.startsWith("timeGrid")) {
        // Fit the calendar between its natural page position and the bottom
        // of the viewport (with a little breathing room), so the time grid
        // gets an internal scroller. Floor keeps it usable on short windows.
        const offsetTop =
          this.$el.getBoundingClientRect().top + window.scrollY;
        height = Math.max(480, window.innerHeight - offsetTop - 16);
      }
      if (this.calendar.getOption("height") !== height) {
        this.calendar.setOption("height", height);
      }
    },

    handleEventClick(info) {
      info.jsEvent.preventDefault();
      info.jsEvent.stopPropagation();

      // Open the edit modal using HTMX; alpine-components.js opens the
      // modal when the content lands in the container.
      htmx.ajax("GET", `/calendar/${info.event.id}/edit`, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      });
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
      const updateData = { date, end_date: null };

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

      fetch(`/calendar/${eventId}/quick-update`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(data),
      })
        .then((response) => {
          if (!response.ok) {
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
