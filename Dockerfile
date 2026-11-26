# Imagen de captura (Etapa 3): Python 3.12 + Chromium de Playwright, para Azure Container Apps Job.
# 0.5 (16-nov-2026): Scrapling (patchright) para Éxito, con el mismo Chromium de la imagen base.
# Construir:  docker build -t tfm-captura:0.7 .
# Probar:     docker run --rm --ipc=host tfm-captura:0.7 --sin-lago --sitios exito --modo seguimiento --limite 3
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=America/Bogota

WORKDIR /app
COPY requirements-contenedor.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements-contenedor.txt
# Scrapling usa patchright 1.63.0 (requirements-contenedor.txt), que abre el chromium-1243 que ya trae la imagen base.

COPY config/ config/
COPY src/ src/

# Usuario sin privilegios que trae la imagen base.
USER pwuser
ENTRYPOINT ["python", "-m", "src.nube.tarea"]
