# Warehouse Stock Management

A Django-based inventory and spare parts management application built to track stock levels, warehouses, orders, and risk indicators.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Docker Setup](#docker-setup)
- [Local Python Setup](#local-python-setup)
- [Data and Fixtures](#data-and-fixtures)
- [Project Structure](#project-structure)
- [Administration](#administration)
- [Logging](#logging)
- [Contributing](#contributing)
- [License](#license)

## Overview

This repository contains a warehouse and parts inventory management MVP built with Django. The project provides a foundation for managing spare parts availability, warehouse inventory, order records, and risk-based inventory reporting.

## Key Features

- Warehouse and inventory management
- Part catalog and dealer order tracking
- REST API endpoints for parts and inventory
- Django admin panel for data management
- Initial fixture data for rapid local setup

## Technology Stack

- Python 3.x
- Django
- Django REST Framework
- Docker and Docker Compose
- SQLite (default development database)

## Getting Started

### Docker Setup

1. Install Docker Desktop and enable Docker Compose.
2. From the project root run:

   ```powershell
   docker-compose up --build
   ```

3. Open the application in your browser:

   - Web app: `http://localhost:8000`
   - Admin: `http://localhost:8000/admin/`
   - API: `http://localhost:8000/api/v1/parts/`

### Local Python Setup

1. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Apply migrations:

   ```powershell
   python manage.py migrate
   ```

4. Load sample data:

   ```powershell
   python manage.py loaddata parts/fixtures/initial_data.json
   ```

5. Start the development server:

   ```powershell
   python manage.py runserver
   ```

6. Open the app at `http://127.0.0.1:8000`

## Data and Fixtures

The repository includes initial fixture data for the `parts` app at `parts/fixtures/initial_data.json`. Use the Django loaddata command to populate sample warehouses, parts, inventory records, and orders.

## Project Structure

- `manage.py` — Django management utility.
- `mysite/` — Project configuration, settings, URLs, and WSGI/ASGI entry points.
- `parts/` — Core application for inventory, parts, warehouses, orders, serializers, views, and templates.
- `api/` — API routing and versioned endpoint configuration.
- `static/` and `templates/` — Front-end assets and HTML templates.
- `logs/` — Application log output.

## Administration

The Django admin interface is available at `http://localhost:8000/admin/` after creating a superuser.

Create a superuser with:

```powershell
python manage.py createsuperuser
```

## Logging

Application log output is configured to write to `logs/warehouse.log`. Ensure the `logs/` directory exists and is writable by the running process.

## Contributing

Contributions are welcome. Suggested improvements include:

- Authentication and role-based access control
- Demand forecasting and stockout risk analysis
- Background job processing with Celery and Redis
- API pagination, filtering, and documentation

MIT License

Copyright (c) 2026 Maheshkumar V

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.