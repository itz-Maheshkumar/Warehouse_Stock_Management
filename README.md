CatParts India - MVP

A focused Django MVP for spare parts availability and stockout risk.

Quick start (using Docker Compose):

1. Install Docker and Docker Compose.
2. From the project root run:

   docker-compose up --build

3. The web app will be available at http://localhost:8000
   - Admin: http://localhost:8000/admin/
   - API: http://localhost:8000/api/v1/parts/

Local Python setup (without Docker):

1. Create and activate a virtual environment:

   python -m venv .venv
   .venv\Scripts\Activate.ps1

2. Install dependencies:

   pip install -r requirements.txt

3. Apply Django migrations:

   python manage.py migrate

4. Load initial data:

   python manage.py loaddata parts/fixtures/initial_data.json

5. Run the development server:

   python manage.py runserver

6. Open the app at http://127.0.0.1:8000

Enterprise readiness:
- Log files are written to `logs/warehouse.log`.
- Advanced front-end styling has been added across templates using modern cards, gradients, and responsive UI patterns.
- A brand SVG logo and favicon are included in `static/images/`.

Notes:
- The repo contains a small `parts` app with models for Part, Inventory, Warehouse, Dealer and Order.
- Fixtures are available at parts/fixtures/initial_data.json (use `python manage.py loaddata initial_data.json`).
- If not using Docker, create a Python virtualenv, install requirements.txt and configure DATABASES in mysite/settings.py.

Next steps:
- Add authentication & role-based permissions
- Add demand forecasting & stockout-risk calculations
- Add Celery workers for background processing and Redis as broker

This scaffold was created to follow structure.md and provide a working foundation to build the modules described there.
