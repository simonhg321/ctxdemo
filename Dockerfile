FROM python:3.12-slim
WORKDIR /srv
ARG CTXDEMO_TOKENIZER=Qwen/Qwen3-8B
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV HF_HOME=/srv/hf
ENV CTXDEMO_TOKENIZER=$CTXDEMO_TOKENIZER
RUN python -c "import os; from tokenizers import Tokenizer; Tokenizer.from_pretrained(os.environ['CTXDEMO_TOKENIZER'])" || echo "tokenizer prefetch failed; chunks strip will be hidden"
COPY app app
COPY config config
COPY corpus corpus
COPY static static
ENV VLLM_URL=http://host.docker.internal:8100
EXPOSE 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
