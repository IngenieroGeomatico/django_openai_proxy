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
   git clone <repo>
   cd django_openai_proxy
2. Entorno virtual:
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt


## Uso
- Levantar servidor:
  python manage.py migrate
  python manage.py runserver
  rellenar .env t providers.json
- Endpoint principal:
  POST /api/v1/chat/completions
  - Cuerpo compatible con OpenAI (model, messages, stream, etc.)
  - El proxy selecciona proveedor y reescribe modelo si está mapeado.


## Notas de seguridad
- No commitear archivos con claves (ej. config.yaml). Añadirlos a .gitignore.
- Si una API key se filtra, revocar/rotar inmediatamente.
- Limitar y monitorizar acceso mediante PROXY_API_KEY si se expone públicamente.
