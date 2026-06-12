FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README_tw_site_analyzer.md ./
COPY tw_site_analyzer ./tw_site_analyzer
COPY web_mobile ./web_mobile

RUN pip install --no-cache-dir -e .

ENV HOST=0.0.0.0

EXPOSE 8787

CMD ["python", "-m", "tw_site_analyzer.server"]
