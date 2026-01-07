import requests
import json
import logging
from itertools import cycle
from django.http import JsonResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

logger = logging.getLogger(__name__)

SERVICES = settings.AI_PROVIDERS
service_cycle = cycle(SERVICES)
current_service = next(service_cycle)  # Inicializamos

def get_next_service():
    global current_service
    current_service = next(service_cycle)
    logger.info(f"Balanceando a: {current_service['name']}")
    return current_service

@csrf_exempt
def ai_proxy(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Solo POST permitido")

    # Protección opcional con clave
    if settings.PROXY_API_KEY:
        auth = request.headers.get('Authorization')
        if not auth or auth != f"Bearer {settings.PROXY_API_KEY}":
            return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON inválido")

    service = get_next_service()

    # Mapeo de modelo (si existe)
    if 'model' in body:
        mapped_model = service.get('model_map', {}).get(body['model'])
        if mapped_model:
            body['model'] = mapped_model
            logger.info(f"Modelo mapeado: {body['model']} → {mapped_model}")

    headers = {
        "Authorization": f"Bearer {service['api_key']}",
        "Content-Type": "application/json",
    }

    # Soporte streaming
    if body.get('stream', False):
        def event_stream():
            try:
                with requests.post(service['url'], headers=headers, json=body, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if line:
                            yield line + b'\n'
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()

        return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

    # Respuesta normal
    try:
        response = requests.post(service['url'], headers=headers, json=body, timeout=60)
        response.raise_for_status()
        return JsonResponse(response.json(), status=response.status_code)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error con {service['name']}: {e}")
        return JsonResponse({"error": str(e), "provider": service['name']}, status=getattr(e.response, 'status_code', 500))