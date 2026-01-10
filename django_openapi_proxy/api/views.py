import json, logging, requests
import re
from itertools import cycle
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Manejo de proveedores
# ----------------------------------------------------------------------
SERVICES = settings.AI_PROVIDERS
_service_cycle = cycle(SERVICES)          # ciclo infinito de proveedores
_current_service = next(_service_cycle)   # inicializamos con el primero

def _next_service(body):
    """Avanza al siguiente proveedor que soporte el modelo solicitado y registra la selección."""
    global _current_service
    model = body.get("model", "")
    # Si no se especifica modelo, rotamos entre todos los servicios
    if not model:
        _current_service = next(_service_cycle)
        logger.info(f"Balanceando a (sin modelo): {_current_service.get('name')}")
        return _current_service

    valid_services = [service for service in SERVICES if "model_map" in service and model in service["model_map"]]
    if not valid_services:
        # Si no hay proveedores que soporten el modelo, retornamos un error
        return None
    _current_service = next((s for s in _service_cycle if s in valid_services), valid_services[0])
    logger.info(f"Balanceando a: {_current_service['name']}")
    return _current_service

def _map_model(service, body):
    """Si el proveedor tiene un mapeo de modelo, lo reemplaza."""
    if "model" in body:
        mapped = service.get("model_map", {}).get(body["model"])
        if mapped:
            logger.info(f"Modelo mapeado: {body['model']} → {mapped}")
            body["model"] = mapped
    return body

def _build_headers(service):
    """Construye los encabezados HTTP para la petición al proveedor."""
    return {
        "Authorization": f"Bearer {service['api_key']}",
        "Content-Type": "application/json",
    }



# ----------------------------------------------------------------------
# Ayudas para respuestas en streaming
# ----------------------------------------------------------------------
def _stream_response(service, headers, body):
    """Genera chunks SSE normalizados compatibles con el estilo de OpenAI."""
    def generator():
        try:
            with requests.post(
                service["url"], headers=headers, json=body, stream=True, timeout=120
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        payload = decoded[6:]                     # quita el prefijo "data: "
                        if payload.strip() == "[DONE]":           # señal de finalización
                            yield b"data: [DONE]\n\n"
                            continue
                        try:
                            chunk = json.loads(payload)
                            # Normalizamos el chunk para que coincida con la respuesta de OpenAI
                            normalized = {
                                "id": chunk.get("id", "chatcmpl-proxy"),
                                "object": "chat.completion.chunk",
                                "created": chunk.get("created", 1700000000),
                                "model": body.get("model", "unknown"),
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "content": choice.get("delta", {}).get("content", "")
                                        },
                                        "finish_reason": choice.get("finish_reason"),
                                    }
                                    for choice in chunk.get("choices", [])
                                ],
                            }
                            yield f"data: {json.dumps(normalized)}\n\n".encode()
                        except json.JSONDecodeError:
                            # Si no se puede parsear, reenviamos la línea tal cual (fallback)
                            yield line + b"\n"
        except Exception as exc:
            # En caso de error interno enviamos un chunk de error SSE
            err = {"error": {"message": str(exc), "type": "server_error"}}
            yield f"data: {json.dumps(err)}\n\n".encode()
    return StreamingHttpResponse(generator(), content_type="text/event-stream")


# ----------------------------------------------------------------------
# Vista principal (refactorizada)
# ----------------------------------------------------------------------
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

    # Seleccionamos proveedor y preparamos la petición
    if "model" in body:
        service = _next_service(body)
        if service is None:
            return JsonResponse({"error": "Modelo no soportado por ninguno de los proveedores"}, status=400)
    else:
        service = _next_service({"model": ""})  # Esto se puede personalizar según sea necesario
    body = _map_model(service, body)
    headers = _build_headers(service)


    print(service.get("name", "").lower())

    # --------------------------------------------------------------
    # Ruta de streaming
    # --------------------------------------------------------------
    if body.get("stream", False):
        return _stream_response(service, headers, body)

    # --------------------------------------------------------------
    # Ruta normal (sin streaming)
    # --------------------------------------------------------------
    try:
        resp = requests.post(service["url"], headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return JsonResponse(resp.json(), status=resp.status_code)
    except requests.exceptions.RequestException as exc:
        logger.error(f"Error con {service['name']}: {exc}")
        status = getattr(exc.response, "status_code", 500)
        return JsonResponse(
            {"error": str(exc), "provider": service["name"]}, status=status
        )