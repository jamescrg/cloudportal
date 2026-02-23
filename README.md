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

### Tasks
- Folder-based task lists with due dates and optional due times
- Recurring tasks (daily, weekly, monthly, yearly) with automatic instance generation
- Share task folders with other users for collaborative lists
- Email reminders for overdue and upcoming tasks (via cron)
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
| Icons | Lucide (icon font) |
| Build | esbuild (JS bundling), npm |
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
- Node.js and npm (for building frontend assets)

### Setup

1. Clone the repository:

```bash
git clone git@github.com:jamescrg/cloudportal.git
cd cloudportal
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

4. Install frontend dependencies and build assets:

```bash
npm install
node build.mjs
```

5. Copy the example environment file and configure it:

```bash
cp .env.example .env
```

6. Create the database and run migrations:

```bash
createdb your-db-name
python manage.py migrate
```

7. Build the search index:

```bash
python manage.py buildwatson
```

8. Create a user account:

```bash
python manage.py createsuperuser
```

9. Run the development server:

```bash
python manage.py runserver
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

### Cron Jobs (Production)

```
0 1 * * * /path/to/.venv/bin/python /path/to/manage.py create_recurring_tasks
*/15 * * * * /path/to/.venv/bin/python /path/to/manage.py send_task_reminders
```

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
