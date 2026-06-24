ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_EXTRA_INDEX_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONPATH=/opt/hydros \
    HYDROS_AGENT_START_ARGS="outflowplan scheduling"

WORKDIR /opt/hydros

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN EXTRA_INDEX_ARGS=""; \
    if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then EXTRA_INDEX_ARGS="--extra-index-url ${PIP_EXTRA_INDEX_URL}"; fi; \
    python -m pip install --upgrade pip setuptools wheel \
    -i "${PIP_INDEX_URL}" ${EXTRA_INDEX_ARGS} \
    && for i in 1 2 3; do \
        python -m pip install --no-cache-dir --retries 10 --timeout 120 --progress-bar off \
        -i "${PIP_INDEX_URL}" ${EXTRA_INDEX_ARGS} \
        paho-mqtt==2.1.0 \
        pydantic==2.12.5 \
        PyYAML==6.0.3 \
        requests==2.32.5 \
        rich==14.3.1 \
        debugpy==1.8.20 \
        numpy==2.2.6 \
        matplotlib==3.10.7 && exit 0; \
        echo "pip install failed, retry ${i}/3"; \
        sleep 5; \
    done; \
    exit 1

COPY hydros_agent_sdk /opt/hydros/hydros_agent_sdk
COPY custom-agent/power /opt/hydros/custom-agent/power

WORKDIR /opt/hydros/custom-agent/power

RUN mkdir -p /opt/hydros/custom-agent/power/logs

EXPOSE 8015

CMD ["bash", "./start_agents.sh"]
