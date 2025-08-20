edit .env isi kredensial & parameter
```
cp .env.example .env
```

install dependencies
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

example payload
```
curl -X POST http://localhost:8080/webhook/grafana \
  -H "Content-Type: application/json" \
  -H "X-API-Key: changeme" \
  -d '{
    "status": "firing",
    "commonLabels": {
      "alertname": "ComputeMemoryHigh",
      "host": "compute1",
      "fingerprint": "mem-compute1-20250820"
    },
    "commonAnnotations": {
      "summary": "memory usage: 60%"
    },
    "target_threshold": 0.6
  }'
```
