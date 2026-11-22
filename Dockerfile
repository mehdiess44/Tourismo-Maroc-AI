FROM node:22-slim AS web
WORKDIR /source/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY tourismo ./tourismo
COPY data ./data
COPY --from=web /source/frontend/dist ./frontend/dist
ENV PORT=8000
CMD ["sh", "-c", "exec uvicorn tourismo.api:app --host 0.0.0.0 --port ${PORT}"]
