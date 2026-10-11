import json, logging, requests
import re
from itertools import cycle
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Endpoint de descubrimiento de modelos (OpenAI-compatible)
# ----------------------------------------------------------------------
import time

def models_list(request):
    """Devuelve la lista de modelos disponibles en formato OpenAI-compatible."""
    models = []
    seen = set()
    for provider in SERVICES:
        for model_name in provider.get("model_map", {}):
            if model_name.startswith("_"):
                continue
            if model_name not in seen:
                seen.add(model_name)
                models.append({
                    "id": model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider["name"],
                })
    return JsonResponse({"object": "list", "data": models}, status=200)


# ----------------------------------------------------------------------
# Manejo de proveedores
# ----------------------------------------------------------------------
SERVICES = settings.AI_PROVIDERS
_service_cycle = cycle(SERVICES)          # ciclo infinito de proveedores
_current_service = next(_service_cycle)   # inicializamos con el primero

def _resolve_api_key(service):
    """Resuelve la api_key: si empieza con 'env:', la carga desde variables de entorno."""
    key = service.get('api_key', '')
    if isinstance(key, str) and key.startswith('env:'):
        env_var = key[4:]
        value = os.environ.get(env_var, '')
        if not value:
            logger.warning(f"Variable de entorno {env_var} no definida para {service.get('name')}")
        return value
    return key


def _next_service(body):
    """Avanza al siguiente proveedor que soporte el modelo solicitado y registra la selección."""
    global _current_service
    model = body.get("model", "")
    # Filtrar proveedores con api_key válida
    active_services = [s for s in SERVICES if _resolve_api_key(s)]
    # Si no se especifica modelo, rotamos entre todos los servicios activos
    if not model:
        valid = active_services
    else:
        valid = [s for s in active_services if "model_map" in s and model in s["model_map"]]
    if not valid:
        return None
    _current_service = next((s for s in _service_cycle if s in valid), valid[0])
    logger.info(f"Balanceando a: {_current_service['name']}")
    return _current_service

def _map_model(service, body):
    """Si el proveedor tiene un mapeo de modelo, lo reemplaza."""
    if "model" in body:
        mapped = service.get("model_map", {}).get(body["model"])
        if mapped:
            logger.info(f"Modelo mapeado: {body['model']} → {mapped}")
            body["model"] = mapped
            # Si el proveedor usa url_template (ej: Hugging Face), inyecta el modelo en la URL
            if "url_template" in service:
                service["url"] = service["url_template"].format(model=mapped)
                logger.info(f"URL construida: {service['url']}")
    return body

def _build_headers(service):
    """Construye los encabezados HTTP para la petición al proveedor."""
    return {
        "Authorization": f"Bearer {_resolve_api_key(service)}",
        "Content-Type": "application/json",
    }


def _get_service_url(service):
    """Devuelve la URL final del servicio, resolviendo url_template si existe."""
    if "url_template" in service:
        # Si la plantilla ya tiene el modelo inyectado (lo hace _map_model)
        return service.get("url") or service["url_template"]
    return service["url"]



# ----------------------------------------------------------------------
# Ayudas para respuestas en streaming
# ----------------------------------------------------------------------
def _stream_response(service, headers, body):
    """Genera chunks SSE normalizados compatibles con el estilo de OpenAI.

    Hace la petición POST de forma eager (no perezosa) para que un
    error HTTP (4xx/5xx) se propague al caller y el loop pueda reintentar
    con otro proveedor.
    """
    # Petición eager — si falla (413, etc.) la excepción sale de aquí
    resp = requests.post(
        _get_service_url(service), headers=headers, json=body, stream=True, timeout=120
    )
    resp.raise_for_status()

    def generator():
        try:
            with resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        payload = decoded[6:]
                        if payload.strip() == "[DONE]":
                            yield b"data: [DONE]\n\n"
                            continue
                        try:
                            chunk = json.loads(payload)
                            # Normalizamos el chunk para que coincida con la respuesta de OpenAI
                            choices = []
                            for choice in chunk.get("choices", []):
                                delta_src = choice.get("delta") or {}
                                delta = {
                                    "content": delta_src.get("content", "")
                                }
                                if "reasoning_content" in delta_src:
                                    delta["reasoning_content"] = delta_src["reasoning_content"]
                                choices.append({
                                    "index": choice.get("index", 0),
                                    "delta": delta,
                                    "finish_reason": choice.get("finish_reason"),
                                })
                            normalized = {
                                "id": chunk.get("id", "chatcmpl-proxy"),
                                "object": "chat.completion.chunk",
                                "created": chunk.get("created", 1700000000),
                                "model": body.get("model", "unknown"),
                                "choices": choices,
                            }
                            if "usage" in chunk:
                                normalized["usage"] = chunk["usage"]
                            yield f"data: {json.dumps(normalized)}\n\n".encode()
                        except json.JSONDecodeError:
                            yield line + b"\n"
        except Exception as exc:
            err = {"error": {"message": str(exc), "type": "server_error"}}
            yield f"data: {json.dumps(err)}\n\n".encode()

    return StreamingHttpResponse(generator(), content_type="text/event-stream")


# ----------------------------------------------------------------------
# Vistas (refactorizadas)
# ----------------------------------------------------------------------
@csrf_exempt
def list_models(request):
    """Devuelve la lista de modelos disponibles en formato compatible con OpenAI."""
    if request.method != "GET":
        return HttpResponseBadRequest("Solo GET permitido")

    # Protección opcional mediante clave API
    if settings.PROXY_API_KEY:
        auth = request.headers.get("Authorization")
        if not auth or auth != f"Bearer {settings.PROXY_API_KEY}":
            return JsonResponse({"error": "Unauthorized"}, status=401)

    seen = set()
    data = []
    providers = getattr(settings, "AI_PROVIDERS", SERVICES)
    for provider in providers:
        provider_name = provider.get("name", "unknown")
        model_map = provider.get("model_map", {})
        for model_id in model_map.keys():
            if model_id.startswith("_"):
                continue
            if model_id not in seen:
                seen.add(model_id)
                data.append({
                    "id": model_id,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": provider_name,
                })

    return JsonResponse({"object": "list", "data": data})


@csrf_exempt
def ai_proxy(request):
    """Proxy que reenvía peticiones POST a un proveedor de IA rotativo."""
    if request.method != "POST":
        return HttpResponseBadRequest("Solo POST permitido")

    # Protección opcional mediante clave API
    if settings.PROXY_API_KEY:
        auth = request.headers.get("Authorization")
        if not auth or auth != f"Bearer {settings.PROXY_API_KEY}":
            return JsonResponse({"error": "Unauthorized"}, status=401)

    # Parseamos el cuerpo JSON
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON inválido")

    # --------------------------------------------------------------
    # Reintentar con otro proveedor si falla
    # --------------------------------------------------------------
    model = body.get("model", "")

    for intento in range(len(SERVICES)):
        if model:
            service = _next_service(body)
            if service is None:
                continue
        else:
            service = next(_service_cycle)

        mapped_body = _map_model(service, dict(body))
        headers = _build_headers(service)

        service_url = _get_service_url(service)
        try:
            if body.get("stream", False):
                return _stream_response(service, headers, mapped_body)

            resp = requests.post(service_url, headers=headers, json=mapped_body, timeout=60)
            resp.raise_for_status()
            return JsonResponse(resp.json(), status=resp.status_code)
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Intento {intento+1} falló con {service['name']}: {exc}")
            continue

    return JsonResponse(
        {"error": "Todos los proveedores fallaron"}, status=503
    )