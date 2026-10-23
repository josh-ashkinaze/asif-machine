FROM python:3.12-slim

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The app reads PORT from the environment and falls back to 5001.
ENV PORT=5001
EXPOSE 5001

CMD ["gunicorn", "-w", "2", "--timeout", "120", "-b", "0.0.0.0:5001", "app:app"]
