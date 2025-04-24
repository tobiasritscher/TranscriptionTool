# Anleitung
## Docker build
```bash
docker build -t openai-transcriber .
```

## Docker run
```bash
docker run -p 5000:5000 \
  -e OPENAI_API_KEY="<OpenAI API Key>" \
  -e PYANNOTE_API_KEY="<Pyannote AI API Key>" \
  --rm --name my-transcriber openai-transcriber
```
