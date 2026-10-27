FROM python:3.14-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

COPY rsa_checkins/ rsa_checkins/
COPY views/ views/
COPY app.py .

USER appuser
ENV CHECKINS_DATA_DIR=/app/data
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
