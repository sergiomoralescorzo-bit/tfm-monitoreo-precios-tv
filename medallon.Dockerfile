# Imagen del medallón (Etapa 3, opción B): Spark 3.4 + Delta 2.4 en modo local, igual a tests_spark y al
# runtime de Synapse. Corre en el Container Apps Job `caj-tfm-medallon` (ver src/nube/tarea_medallon.py).
# Construir:  docker build -f medallon.Dockerfile -t tfm-medallon:0.2 .
# Probar:     docker run --rm -v "<carpeta lago>:/lago" tfm-medallon:0.2 --lago-local /lago
FROM python:3.10-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-medallon.txt .
RUN pip install --no-cache-dir -r requirements-medallon.txt
# Aparte, para no invalidar la capa de PySpark (311 MB) al agregar dependencias livianas.
RUN pip install --no-cache-dir pyyaml==6.0.2
# Los jar de Delta van dentro de pyspark/jars: la imagen no depende de Maven al arrancar.
RUN python -c "import pyspark, os, urllib.request as u; d = os.path.join(os.path.dirname(pyspark.__file__), 'jars'); \
m = 'https://repo1.maven.org/maven2/io/delta'; \
[u.urlretrieve(f'{m}/{a}/2.4.0/{a}-2.4.0.jar', os.path.join(d, f'{a}-2.4.0.jar')) for a in ('delta-core_2.12', 'delta-storage')]"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=America/Bogota
RUN useradd --create-home spark
WORKDIR /app
COPY config/servicios.yaml config/servicios.yaml
COPY src/ src/
USER spark
ENTRYPOINT ["python", "-m", "src.nube.tarea_medallon"]
