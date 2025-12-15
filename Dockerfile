# Multi-stage Dockerfile: builds frontend with Node and copies into final image

# --- frontend build stage ---
FROM node:20-bullseye AS frontend-build
ARG FRONTEND_REPO="https://github.com/wenchen-cai/Slurm-web"
ARG FRONTEND_REF="main"
WORKDIR /src

# clone full repo into /src/repo
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 --branch "${FRONTEND_REF}" "${FRONTEND_REPO}" /src/repo

# build from repo frontend
WORKDIR /src/repo/frontend

# install & build, then normalize output to /src/out (either dist or build)
RUN npm install && npm run build && \
    if [ -d ./dist ]; then \
      rm -rf /src/out || true; mkdir -p /src/out && cp -a ./dist/. /src/out/; \
    elif [ -d ./build ]; then \
      rm -rf /src/out || true; mkdir -p /src/out && cp -a ./build/. /src/out/; \
    else \
      echo "ERROR: frontend build produced no 'dist' or 'build' directory" >&2; exit 1; \
    fi

# --- final runtime image ---
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 非敏感 build-time 參數
ARG RACKSLAB_REPO="https://pkgs.rackslab.io/deb"
ARG RACKSLAB_KEYS_URL="https://pkgs.rackslab.io/keyring.asc"
ARG RACKSLAB_SUITE="ubuntu24.04"

# 先安裝基本工具和 LDAP 開發庫（拆成多個 RUN 有利於除錯）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates gnupg curl apt-transport-https dirmngr gettext \
      python3-pip python3-dev build-essential \
      libldap2-dev libsasl2-dev && \
    rm -rf /var/lib/apt/lists/*

# 新增 key 與 sources（獨立步驟，若失敗可立即看到錯誤）
RUN set -eux; \
    curl -fsSL "${RACKSLAB_KEYS_URL}" | gpg --dearmor -o /usr/share/keyrings/rackslab.gpg; \
    echo "deb [signed-by=/usr/share/keyrings/rackslab.gpg] ${RACKSLAB_REPO} ${RACKSLAB_SUITE} main slurmweb-5" \
      > /etc/apt/sources.list.d/rackslab.list; \
    apt-get update

# 再安裝目標套件（拆開，方便判斷缺哪個依賴）
# 注意：我們會用源代碼覆蓋這些包，但先安裝以獲取依賴
RUN set -eux; \
    apt-get install -y --no-install-recommends \
      nginx supervisor python3-minimal jq; \
    apt-get install -y --no-install-recommends \
      slurm-web-gateway slurm-web-agent || (apt-cache policy slurm-web-gateway slurm-web-agent && false); \
    rm -rf /var/lib/apt/lists/*

# ===== 從源代碼安裝 slurm-web 以支援 PCS =====
# Copy entire source repo from frontend-build stage
COPY --from=frontend-build /src/repo /tmp/slurm-web-src

# Remove old apt-installed slurm-web and RFL packages to avoid conflicts
RUN set -eux; \
    rm -rf /usr/lib/python3/dist-packages/slurmweb* \
           /usr/lib/python3/dist-packages/slurm_web* \
           /usr/lib/python3/dist-packages/RFL* \
           /usr/lib/python3/dist-packages/rfl* || true

# Install Python dependencies including boto3 for PCS support
RUN set -eux; \
    pip3 install --no-cache-dir --break-system-packages boto3

# Install slurm-web from source
RUN set -eux; \
    cd /tmp/slurm-web-src && \
    pip3 install --no-cache-dir --break-system-packages --ignore-installed .

# Copy config files and create compatibility wrappers BEFORE cleanup
RUN set -eux; \
    mkdir -p /usr/share/slurm-web/conf/vendor && \
    cp -r /tmp/slurm-web-src/conf/vendor/* /usr/share/slurm-web/conf/vendor/ && \
    cp /tmp/slurm-web-src/conf/vendor/agent.yml /usr/share/slurm-web/conf/agent.yml && \
    cp /tmp/slurm-web-src/conf/vendor/gateway.yml /usr/share/slurm-web/conf/gateway.yml 2>/dev/null || true && \
    rm -f /usr/bin/slurm-web-agent /usr/bin/slurm-web-gateway || true && \
    cp /tmp/slurm-web-src/lib/exec/slurm-web-compat /usr/bin/slurm-web-compat && \
    chmod +x /usr/bin/slurm-web-compat && \
    for cmd in slurm-web-agent slurm-web-gateway slurm-web-ldap-check slurm-web-gen-jwt-key slurm-web-show-conf slurm-web-connect-check; do \
      ln -sf /usr/bin/slurm-web-compat "/usr/bin/$cmd"; \
    done && \
    rm -rf /tmp/slurm-web-src

# 建目錄、預設定
RUN mkdir -p /etc/slurm-web /var/lib/slurm-web /usr/share/slurm-web/frontend /usr/share/slurm-web/gateway/templates \
    && if ! id -u slurm-web >/dev/null 2>&1; then useradd -r -s /bin/false slurm-web || true; fi \
    && chown -R slurm-web:slurm-web /var/lib/slurm-web /etc/slurm-web /usr/share/slurm-web || true

# install aws cli
RUN apt-get update && apt-get install -y unzip curl && \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install --update && \
    rm -rf aws awscliv2.zip

# Copy normalized frontend output from build stage into the image
COPY --from=frontend-build /src/out/ /usr/share/slurm-web/frontend/

# If your frontend outputs to a different folder, update the build stage to copy into /src/out.

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx-slurm-web.conf /etc/nginx/sites-available/slurm-web
RUN ln -sf /etc/nginx/sites-available/slurm-web /etc/nginx/sites-enabled/slurm-web && rm -f /etc/nginx/sites-enabled/default

RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 80 5011 5012

# 建議把 JWT key 與 /etc/slurm-web 作為 volume 在 runtime 提供（避免把 secrets 寫入映像）
# Note: /usr/share/slurm-web is NOT included as a volume to preserve config files
VOLUME ["/etc/slurm-web", "/var/lib/slurm-web"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
