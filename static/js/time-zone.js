/**
 * Tell the server where the user is now.
 *
 * The browser knows its time zone; the server keeps it on the user so
 * typed times are read in it and the list and notifications follow it.
 * Sent only when it differs from what the server last recorded (the body
 * carries that), so a page load costs nothing while the user stays put.
 */
document.addEventListener("DOMContentLoaded", () => {
  const body = document.body;
  const recorded = body.dataset.timeZone;
  let current;
  try {
    current = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (e) {
    return;
  }
  if (!current || recorded === undefined || current === recorded) {
    return;
  }

  const form = new FormData();
  form.append("time_zone", current);
  fetch("/settings/time-zone", {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken() },
    body: form,
  })
    .then((response) => {
      if (!response.ok) {
        return;
      }
      body.dataset.timeZone = current;
      // The calendar page, if that is where we are, re-reads its list and
      // feed in the new zone.
      if (document.getElementById("events") && window.htmx) {
        window.htmx.trigger(document.body, "eventsChanged");
      }
    })
    .catch(() => {});

  function csrfToken() {
    try {
      const headers = JSON.parse(body.getAttribute("hx-headers") || "{}");
      if (headers["X-CSRFToken"]) {
        return headers["X-CSRFToken"];
      }
    } catch (e) {
      // fall through to the cookie
    }
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }
});
