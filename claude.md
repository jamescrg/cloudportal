
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

CloudPortal is a personal home page and organizer. It manages
favorites, tasks, a calendar, contacts, and notes. It also provides some
weather data and some crypto and securities data via api connections.

## Development Commands

### Environment Setup

Dependencies are managed with uv (pyproject.toml, uv.lock); the virtual
environment is `.venv`.

```bash
# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### Running the Application

```bash
python manage.py runserver
```

### Testing

```bash
# Run all tests
pytest

# Run tests with parallel execution
pytest -n auto

# Run specific app tests
pytest apps/tasks/tests/
```

### Code Quality

```bash
# Format code with Black
black .

# Run linting with flake8
flake8

# Sort imports with isort
isort . --profile black --combine-as --trailing-comma

# Run pre-commit hooks manually
pre-commit run --all-files

# Format Django templates
djlint --profile django --reformat templates/
```

## Architecture

### Key Configuration

- **config/**: Django configuration directory
  - settings.py: Main Django settings with environment variable support
  - urls.py: Root URL configuration
- **utils/**: Shared utilities
- **templates/**: Django templates organized by app
- **static/**: CSS, JavaScript, and images

### Database

- PostgreSQL with custom user model (CustomUser)
- Migration files in each app's migrations/ directory

### External Integrations

- Google Calendar API (calendar_tokens.json)
- Google Contacts API (contact_tokens.json)

### Testing Strategy

- pytest with django plugin
- Test files in each app's tests/ directory
- Conftest.py files for test configuration
- Parallel test execution support with pytest-xdist

### Code Standards

- Black code formatting
- isort for import sorting
- flake8 for linting
- djLint for Django template formatting
- Pre-commit hooks enforce code quality
- Migrations excluded from linting (see .pre-commit-config.yaml)

- do not use inline styles in HTML
- css values should snap to a 4px grid
- tests run slowly on this server, when testing, please run targeted unit tests to cover recent changes
- do not apply claude branding to commit descriptions
