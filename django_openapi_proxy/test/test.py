import requests
import json

from decouple import config
PROXY_API_KEY = config('PROXY_API_KEY', default=None)

# URL de tu proxy Django (cámbiala si usas otro puerto)
BASE_URL = "http://localhost:8000/api/v1/chat/completions"

# Tu mensaje de prueba
payload = {
    "model": "gpt-4o-mini",  # Este se mapeará automáticamente a groq-4-1-fast-reasoning (o lo que tengas en providers.json)
    "messages": [
        {"role": "system", "content": "Eres un asistente útil y divertido."},
        {"role": "user", "content": "Cuéntame un chiste corto sobre programación"}
    ],
    "temperature": 0.7,
    "max_tokens": 200,
    # Cambia a True si quieres probar streaming
    "stream": False
}

headers = {
    "Content-Type": "application/json",
}

# El proxy espera el header: Authorization: Bearer <PROXY_API_KEY>
if PROXY_API_KEY:
    headers["Authorization"] = f"Bearer {PROXY_API_KEY}"

print("🚀 Enviando petición al proxy...\n")

response = requests.post(BASE_URL, headers=headers, json=payload)

if response.status_code == 200:
    if payload["stream"]:
        print("Respuesta en streaming:\n")
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data: "):
                    data = decoded[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        json_data = json.loads(data)
                        content = json_data["choices"][0]["delta"].get("content", "")
                        print(content, end="", flush=True)
                    except:
                        pass
        print("\n\n✅ Streaming terminado.")
    else:
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        model_used = result.get("model", "desconocido")
        provider = result.get("provider", "desconocido")  # Si falla algún proveedor, lo verás
        print(f"Modelo usado: {model_used}")
        print(f"Proveedor: {provider}")
        print("\nRespuesta:\n")
        print(answer)
else:
    print(f"❌ Error {response.status_code}")
    print(response.text)