# django_openai_proxy

Proxy compatible con la API de OpenAI que balancea peticiones entre múltiples proveedores de modelos (ej. Groq, Cerebras, Gemini, etc.) para ofrecer una alternativa económica o gratuita a GPT. Implementado en Django y pensado para integración con editores como VS Code / Continue.dev.

## Características
- API compatible con endpoints de OpenAI (ej. /v1/chat/completions).
- Balanceo round-robin entre proveedores configurables.
- Soporta streaming (SSE) y respuestas normales.
- Mapéo de modelos por proveedor.
- Protección opcional por clave de proxy.

## Requisitos
- Python 3.10+
- pip
- Dependencias en requirements.txt (requests, Django, ...)

## Instalación rápida
1. Clonar:
   - git clone <repo>
   - cd django_openai_proxy
2. Entorno virtual:
   - python -m venv .venv
   - source .venv/bin/activate
   - pip install -r requirements.txt


## Uso
- Levantar servidor:
     - python manage.py migrate
     - python manage.py runserver
     - rellenar .env y providers.json
- Endpoint principal:
  POST /api/v1/chat/completions
  - Cuerpo compatible con OpenAI (model, messages, stream, etc.)
  - El proxy selecciona proveedor y reescribe modelo si está mapeado.


## Notas de seguridad
- No commitear archivos con claves (ej. config.yaml). Añadirlos a .gitignore.
- Si una API key se filtra, revocar/rotar inmediatamente.
- Limitar y monitorizar acceso mediante PROXY_API_KEY si se expone públicamente.

## Integración con OpenCode

Este proxy se puede usar como proveedor de modelos dentro de [OpenCode](https://opencode.ai) (o cualquier cliente que hable el protocolo OpenAI-compatible). OpenCode se conecta vía el paquete `@ai-sdk/openai-compatible` y solo necesita dos endpoints, ambos expuestos por el proxy:

- `POST /api/v1/chat/completions` (normal y streaming SSE)
- `GET /api/v1/models` (descubrimiento de modelos, opcional)

### Prerrequisitos
1. Proxy levantado y accesible: `python manage.py runserver` → `http://127.0.0.1:8000`
2. `providers.json` con las claves reales de al menos un proveedor (se auto-genera desde `providers.example.json` al primer arranque).

### Configuración

Copia el bloque del archivo [`opencode.example.json`](opencode.example.json) dentro de la clave `provider` de tu configuración de opencode (normalmente `~/.config/opencode/opencode.json`). Resumen:

```jsonc
{
  "provider": {
    "django-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Django OpenAI Proxy",
      "options": {
        "baseURL": "http://127.0.0.1:8000/api/v1",
        "apiKey": "{env:DJANGO_PROXY_API_KEY}"
      },
      "models": {
        "gpt-oss-120b": { "name": "GPT OSS 120B" },
        "gemini-2.5-flash-lite": { "name": "Gemini 2.5 Flash Lite" }
      }
    }
  }
}
```

Después, selecciona los modelos por defecto a nivel de config:

```jsonc
{
  "model": "django-proxy/gpt-oss-120b",
  "small_model": "django-proxy/gemini-2.5-flash-lite"
}
```

> El balanceo round-robin decide qué proveedor real responde cada petición (Groq, Cerebras, Gemini u OpenRouter según los `model_map` de `providers.json`).

### Clave de API
- Si en el `.env` del proxy `PROXY_API_KEY=None` (valor por defecto), el proxy no exige autenticación: en opencode puedes dejar la `apiKey` como está o poner un valor ficticio.
- Si activas `PROXY_API_KEY` en el `.env` del proxy, el **mismo valor** debe llegar como `DJANGO_PROXY_API_KEY` a opencode (variable de entorno o sustitución `{env:...}`), porque el proxy comprueba `Authorization: Bearer <PROXY_API_KEY>`.

### Solución de problemas
- **El modelo no aparece en opencode**: prueba `GET /api/v1/models` en el navegador; si responde la lista, revisa la ruta del `baseURL` (debe incluir `/api/v1`).
- **Streaming raro o cortado**: opencode usa `stream: true` por defecto; el proxy normaliza los chunks SSE a formato OpenAI (incluido `reasoning_content` y `usage`). Si algún proveedor envía un formato no estándar, el proxy reenvía la línea cruda como fallback.
- **Error de un proveedor**: si el proveedor seleccionado falla, el proxy devuelve su error (con el campo `provider` en la ruta no-streaming). Revisa que la `api_key` de ese proveedor en `providers.json` sea válida.
- **Probar el proxy sin opencode**: usa el script [`test/test.py`](django_openapi_proxy/test/test.py) (normal y streaming).
