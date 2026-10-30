FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UGNAS_BRIDGE_PORT=8770 UGNAS_BRIDGE_HOST=0.0.0.0
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 前端静态资源（显式，便于确认打进镜像）
COPY web/static ./web/static
VOLUME ["/app/state"]
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8770/api/health',timeout=3).status==200 else 1)"
CMD ["uvicorn","web.app:app","--host","0.0.0.0","--port","8770"]
