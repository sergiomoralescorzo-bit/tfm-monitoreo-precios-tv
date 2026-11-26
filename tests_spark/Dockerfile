# Entorno de pruebas igual al runtime Apache Spark 3.4 de Synapse (Python 3.10, Spark 3.4, Delta 2.4).
# Construir (desde la raíz del proyecto):  docker build -t tfm-spark-pruebas tests_spark
# Ejecutar:  docker run --rm -v "<proyecto>:/app" tfm-spark-pruebas
FROM python:3.10-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyspark==3.4.3 delta-spark==2.4.0 pytest==8.3.5 pyyaml pydantic==2.11.7
# Descarga una vez los jar de Delta para no depender de Maven en cada prueba.
RUN python -c "from delta import configure_spark_with_delta_pip as c; from pyspark.sql import SparkSession as S; \
c(S.builder.master('local[1]')).getOrCreate().stop()"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
WORKDIR /app
ENTRYPOINT ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests_spark"]
