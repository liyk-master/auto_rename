FROM python:3.12-alpine

RUN apk add --no-cache build-base patchelf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

ENTRYPOINT ["python", "run_organizer.py"]
CMD ["--web-only", "--web-host", "0.0.0.0", "--web-port", "8080"]
