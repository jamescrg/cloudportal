# CloudPortal

A free, open-source personal dashboard and productivity suite. Self-hosted, fast, and minimal.

**https://cloudportal.link**


## Overview

CloudPortal is an all-in-one personal home page built on Django. It brings together bookmarks, tasks, contacts, notes, weather, and financial data into a single, customizable dashboard. The interface is built with HTMX and Alpine.js for fast, seamless interactions without the overhead of a JavaScript framework.


## Features

### Home Dashboard
- Configurable multi-column layout with drag-and-drop reordering (SortableJS)
- Pin favorite bookmarks, task lists, and upcoming calendar events to the home page
- Integrated search bar with selectable engine (Google, DuckDuckGo, Wikipedia, Bing)
- Collapsible sections that auto-reset daily

### Favorites / Bookmarks
- Organize bookmarks into folders with sorting, filtering, and pagination
- Pin folders and individual bookmarks to the home dashboard
- Bulk move and delete operations
- Browser extension for one-click saving from Firefox or Chrome

### Calendar
- Year, month, week, and day views with drag-and-drop rescheduling, plus a sortable list view
- Events carry a type (Zoom, Virtual, Phone, In-person) and a meeting link or address, and can run over several days
- Optional two-way sync with Google Calendar (switched on under Settings → Calendar): saves push immediately, and the background worker pulls changes and retries failed pushes
- Forward a calendar invitation to your own forwarding address and it is posted as an event; forwarded updates and cancellations follow (see Forwarding invitations)
- Repeating events (daily, every weekday, weekly on chosen days, monthly by day or by weekday, yearly; every N; ending never, on a day or after a number of times). Occurrences are real events made a year ahead and topped up daily by the background worker; an edit or delete applies to "this event" or "this and following events"
- Email notifications per event, any number of them, set as "N minutes/hours/days/weeks before" (with a time of day for all-day events), sent by the background worker
- Time zone aware: each timed event is a fixed moment, and the browser reports where you are, so times are entered, shown, and notified in your current zone while travelling

### Tasks
- Folder-based task lists with due dates and optional due times
- Recurring tasks, with the same repeat rules as events (shared in `apps/common/recurrence.py`): one open instance at a time, the next due on the rule's next day when it is done
- Share task folders with other users for collaborative lists
- Email notifications per task, set on the task as "N minutes/hours/days/weeks before" like event notifications; recurring tasks pass theirs on to each instance. A daily past-due digest can be switched on in Settings. Both are sent by the background worker
- Time zone aware due times: a task with a due time is a fixed moment, shown and notified where you are now
- Quick-filter for tasks due soon; archive completed tasks

### Notes
- Rich text editor powered by Tiptap with full formatting toolbar
- Autosave with debounce and save-status indicator
- In-editor search and replace with regex support
- Markdown import/export
- Optional end-to-end encryption (AES-256-GCM via Web Crypto API) — the server never sees your plaintext
- Colored highlights, keyboard shortcuts, and inline title editing

### Contacts
- Three-panel layout: folders, contact list, and detail view
- Optional Google Contacts sync via OAuth
- Phone number formatting and click-to-call links

### Weather
- Current conditions plus 12-hour and 7-day forecasts via OpenWeatherMap
- Per-user zip code configuration

### Finance
- Live cryptocurrency prices from CoinMarketCap
- Live securities quotes from Finnhub
- User-configurable watchlists managed in settings

### Search
- Full-text search across favorites, contacts, and notes (django-watson)
- Scope filtering and phone number digit matching

### Settings
- Theme selection (matcha, hojicha, original, auto/system)
- Homepage section toggles
- Google account linking (Calendar and Contacts)
- Notification preferences (email and SMS via Twilio)
- Encryption management (enable, disable, change passphrase)
- Crypto and securities watchlist management


## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2, PostgreSQL, Gunicorn |
| Frontend | HTMX, Alpine.js, SortableJS, Tiptap 2 |
| Icons | Lucide (icon font, from unpkg) |
| Build | esbuild, by hand, for the committed TipTap bundle |
| Search | django-watson |
| APIs | OpenWeatherMap, CoinMarketCap, Finnhub, Google Calendar/Contacts |
| Notifications | SMTP email, Twilio SMS |
| Encryption | Web Crypto API (AES-256-GCM, PBKDF2) |
| Code Quality | Black, isort, flake8, djLint, pre-commit |
| Testing | pytest, pytest-django |


## Installation

### Prerequisites

- Python 3.12+
- PostgreSQL
- Node.js and npm, only to rebuild the TipTap bundle after upgrading TipTap

### Setup

1. Clone the repository:

```bash
git clone git@github.com:jamescrg/cloudportal.git
cd cloudportal
```

2. Install Python dependencies:

[uv](https://docs.astral.sh/uv/) manages the virtual environment and
dependencies. It creates the `.venv` and installs everything from the lockfile:

```bash
uv sync
```

Prefix commands with `uv run` (e.g. `uv run python manage.py ...`) to run them
inside the managed environment, or activate it with `source .venv/bin/activate`.

3. Frontend assets need no build: the TipTap bundle the notes editor uses is
committed in `static/js/vendor/`, and the other libraries load from CDNs. After
upgrading TipTap in `package.json`, rebuild the bundle and commit it:

```bash
npm install
npm run build
```

4. Copy the example environment file and configure it:

```bash
cp .env.example .env
```

5. Create the database and run migrations:

```bash
createdb your-db-name
uv run python manage.py migrate
```

6. Build the search index:

```bash
uv run python manage.py buildwatson
```

7. Create a user account:

```bash
uv run python manage.py createsuperuser
```

8. Run the development server:

```bash
uv run python manage.py runserver
```

### Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Debug mode (True/False) |
| `ENV` | Environment (`dev` or `prod`) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL credentials |
| `OPEN_WEATHER_API_KEY` | OpenWeatherMap API key |
| `CRYPTO_API_KEY` | CoinMarketCap API key |
| `FINNHUB_API_KEY` | Finnhub API key |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP settings |
| `ZIP_PRIMARY` | Default zip code for weather |

### Background Worker (Production)

Scheduled jobs run on a Django-Q2 cluster, which uses the database as its
broker, so no cron is needed. The jobs are listed in
`apps/management/schedules.py`:

| Schedule | When | Job |
| --- | --- | --- |
| `event-reminders` | Every 5 minutes | Emails event notifications that are due |
| `task-reminders` | Every 5 minutes | Emails task notifications that are due, and the daily past-due digest |
| `calendar-sync` | Every 5 minutes | Two-way Google Calendar sync for users who have it on |
| `recurring-tasks` | 1:00 daily | Gives any recurring task left without an open instance its next one |
| `extend-event-series` | 2:00 daily | Tops up repeating events' occurrences to a year ahead |

Each job can also be run by hand with its management command
(`send_event_reminders`, `send_task_reminders`, `sync_calendar`,
`create_recurring_tasks`, `extend_event_series`).

Write the schedules to the database after each migrate (safe to repeat):

```
/path/to/.venv/bin/python /path/to/manage.py setup_schedules
```

A machine that must not send email or sync with Google (a dev copy of the
database, say) installs only the jobs it should run, and drops the rest:

```
/path/to/.venv/bin/python /path/to/manage.py setup_schedules --only extend-event-series
```

Run the cluster beside Gunicorn. `deploy/systemd/cpl-qcluster.service` is a
unit for it: replace `@USER@` and `@APP_DIR@`, install it under
`/etc/systemd/system/`, then `systemctl enable --now cpl-qcluster`. Restart
it after a deploy so it loads the new code.

### Production Deployment

CloudPortal runs behind Gunicorn with an Nginx reverse proxy. See `gunicorn.conf.py` for the Gunicorn configuration.


## Browser Extension

The `extension/` directory contains a Firefox/Chrome extension for saving bookmarks directly from the browser toolbar. Configure it with your CloudPortal domain in the extension options.


## Testing

```bash
pytest
```


## License

Free and open source. Self-host it, customize it, make it yours.

## Forwarding invitations

Invitations are received through a [Mailgun inbound route](https://documentation.mailgun.com/docs/mailgun/user-manual/receive-forward-store/), on the same Mailgun account the app sends from.

1. Use a domain Mailgun already receives for: the sending domain works if its MX records point at `mxa.mailgun.org` and `mxb.mailgun.org`, as `mail.cloudportal.link` does. Otherwise add a receiving domain in Mailgun and add those MX records at the DNS host.
2. Add a route that matches forwarding addresses on that domain and forwards to the webhook:
   `match_recipient("^calendar-.*@mail\.cloudportal\.link$")` → `forward("https://cloudportal.link/calendar/inbound/")`.
3. Set two variables in `.env`: `CALENDAR_INBOUND_DOMAIN=mail.cloudportal.link` and `MAILGUN_WEBHOOK_SIGNING_KEY=…` (Mailgun → Settings → API Security → HTTP webhook signing key). Posts without a valid signature are refused.
4. Under Settings → Calendar, create a forwarding address and list any addresses you forward from besides your account address.

Each forward gets a short email back saying what was posted, updated, or removed, or why nothing was.
