# BioSeq AI web app. Holds no model: it calls whatever OpenAI-compatible
# endpoint BIOSEQ_BASE_URL points to (the model service, or any other host).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
COPY bioseq_ai ./bioseq_ai
RUN pip install -r requirements.txt && pip install .

COPY app.py ./
COPY examples ./examples

RUN useradd --create-home bioseq
USER bioseq

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
