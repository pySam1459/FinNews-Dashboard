FROM python:3.12-slim

RUN pip install --no-cache-dir uv
RUN uv tool install openmarkets
ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /app
COPY . .
RUN uv run --script news_dashboard.py --self-test

CMD ["uv", "run", "--script", "news_dashboard.py"]
