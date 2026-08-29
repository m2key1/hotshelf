FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY hotshelf hotshelf
RUN pip install --no-cache-dir .
ENV HOTSHELF_CONFIG=/config/config.yaml \
    HOTSHELF_STATE=/config/state.db \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "hotshelf.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
