FROM python:3.12-slim
ENV PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
