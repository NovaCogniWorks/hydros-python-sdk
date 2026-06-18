ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ARG APT_MIRROR=https://mirrors.aliyun.com
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

RUN sed -i \
        -e "s|http://deb.debian.org|${APT_MIRROR}|g" \
        -e "s|http://security.debian.org|${APT_MIRROR}|g" \
        -e "s|https://deb.debian.org|${APT_MIRROR}|g" \
        -e "s|https://security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY custom-agent/pump/requirements.txt /tmp/requirements.txt
RUN EXTRA_INDEX_ARGS=""; \
    if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then EXTRA_INDEX_ARGS="--extra-index-url ${PIP_EXTRA_INDEX_URL}"; fi; \
    python -m pip install --upgrade pip setuptools wheel \
    -i "${PIP_INDEX_URL}" ${EXTRA_INDEX_ARGS} \
    && for i in 1 2 3; do \
        python -m pip install --no-cache-dir --retries 10 --timeout 120 --progress-bar off \
        -i "${PIP_INDEX_URL}" ${EXTRA_INDEX_ARGS} \
        -r /tmp/requirements.txt && exit 0; \
        echo "pip install failed, retry ${i}/3"; \
        sleep 5; \
    done; \
    exit 1

COPY hydros_agent_sdk /opt/hydros/hydros_agent_sdk
COPY custom-agent/pump /opt/hydros/custom-agent/pump

WORKDIR /opt/hydros/custom-agent/pump

RUN mkdir -p /opt/hydros/custom-agent/pump/logs

EXPOSE 8015

CMD ["bash", "./start_agents.sh"]
