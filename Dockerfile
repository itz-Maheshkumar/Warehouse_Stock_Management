FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /code

# system deps
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /code/

CMD ["gunicorn", "catparts.wsgi:application", "--bind", "0.0.0.0:8000"]
