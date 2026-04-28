FROM python:3.12-slim

RUN useradd --create-home --shell /bin/bash mcp

RUN pip install --no-cache-dir gitlab-ci-mcp

USER mcp
WORKDIR /home/mcp

ENV GITLAB_URL=""
ENV GITLAB_TOKEN=""
ENV GITLAB_PROJECT_PATH=""
ENV GITLAB_SSL_VERIFY="true"

ENTRYPOINT ["gitlab-ci-mcp"]
