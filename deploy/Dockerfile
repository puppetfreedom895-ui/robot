FROM python:3.12-slim

# 操作手机依赖 adb 二进制
RUN apt-get update \
 && apt-get install -y --no-install-recommends adb ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY robot ./robot
RUN pip install --no-cache-dir -e ".[phone]"

COPY config.example.toml persona.md ./
RUN mkdir -p /app/data

# 截图和界面 dump 都落在这里，记得挂卷
ENV PHONE_DATA_DIR=/app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "robot", "live"]
