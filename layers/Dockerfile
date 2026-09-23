# layers/Dockerfile
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY __init__.py lens.py engine.py server.py ./layers/
ENV LAYERS_SERVE=1 LAYERS_MODEL=Qwen/Qwen3-4B LAYERS_DEVICE=cuda HF_HOME=/root/.cache/huggingface
EXPOSE 8400
CMD ["uvicorn", "layers.server:app", "--host", "0.0.0.0", "--port", "8400"]
