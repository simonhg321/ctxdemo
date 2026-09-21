FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV HF_HOME=/srv/hf
RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('Qwen/Qwen3-8B')" || echo "tokenizer prefetch failed; chunks strip will be hidden"
COPY app app
COPY config config
COPY corpus corpus
COPY static static
ENV VLLM_URL=http://host.docker.internal:8100
EXPOSE 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
