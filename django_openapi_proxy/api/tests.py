import json
from unittest import mock
from django.test import TestCase, RequestFactory
from django.conf import settings
from django.http import HttpResponseBadRequest
from api.views import list_models, ai_proxy, _stream_response


class ListModelsTestCase(TestCase):
    def test_list_models_shape(self):
        """Test list_models returns valid OpenAI list shape without _ prefixed keys."""
        mock_providers = [
            {
                "name": "ProviderA",
                "url": "https://api.a.com",
                "api_key": "key-a",
                "model_map": {
                    "_top": "model-top-a",
                    "_low": "model-low-a",
                    "model-1": "actual-model-1",
                    "model-2": "actual-model-2",
                },
            },
            {
                "name": "ProviderB",
                "url": "https://api.b.com",
                "api_key": "key-b",
                "model_map": {
                    "_top": "model-top-b",
                    "model-2": "actual-model-2-b",
                    "model-3": "actual-model-3",
                },
            },
        ]

        with mock.patch.object(settings, "AI_PROVIDERS", mock_providers), \
             mock.patch.object(settings, "PROXY_API_KEY", None):
            response = self.client.get("/api/v1/models")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("object"), "list")
            self.assertIsInstance(data.get("data"), list)
            self.assertEqual(len(data["data"]), 3)

            model_ids = [m["id"] for m in data["data"]]
            self.assertEqual(model_ids, ["model-1", "model-2", "model-3"])

            for entry in data["data"]:
                self.assertIn("id", entry)
                self.assertIn("object", entry)
                self.assertIn("created", entry)
                self.assertIn("owned_by", entry)
                self.assertEqual(entry["object"], "model")
                self.assertFalse(entry["id"].startswith("_"))

            # Check deduplication - first provider wins
            model_2_entry = next(m for m in data["data"] if m["id"] == "model-2")
            self.assertEqual(model_2_entry["owned_by"], "ProviderA")

    def test_list_models_auth_required_when_key_set(self):
        """Test list_models requires auth when PROXY_API_KEY is set."""
        with mock.patch.object(settings, "PROXY_API_KEY", "secret-proxy-key"):
            # Sin header Authorization -> 401
            resp_no_auth = self.client.get("/api/v1/models")
            self.assertEqual(resp_no_auth.status_code, 401)
            self.assertEqual(resp_no_auth.json(), {"error": "Unauthorized"})

            # Header incorrecto -> 401
            resp_wrong_auth = self.client.get(
                "/api/v1/models", HTTP_AUTHORIZATION="Bearer wrong-key"
            )
            self.assertEqual(resp_wrong_auth.status_code, 401)
            self.assertEqual(resp_wrong_auth.json(), {"error": "Unauthorized"})

            # Header correcto -> 200
            resp_auth = self.client.get(
                "/api/v1/models", HTTP_AUTHORIZATION="Bearer secret-proxy-key"
            )
            self.assertEqual(resp_auth.status_code, 200)
            self.assertEqual(resp_auth.json().get("object"), "list")

    def test_list_models_rejects_non_get(self):
        """Test list_models returns 400 for non-GET methods."""
        with mock.patch.object(settings, "PROXY_API_KEY", None):
            response = self.client.post("/api/v1/models", data={})
            self.assertEqual(response.status_code, 400)


class AiProxyTestCase(TestCase):
    def test_ai_proxy_rejects_get(self):
        """Test ai_proxy rejects GET requests with 400."""
        response = self.client.get("/api/v1/chat/completions")
        self.assertEqual(response.status_code, 400)

    def test_ai_proxy_validates_json(self):
        """Test ai_proxy returns 400 when body is not valid JSON."""
        with mock.patch.object(settings, "PROXY_API_KEY", None):
            response = self.client.post(
                "/api/v1/chat/completions",
                data="not a json string",
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)


class StreamResponseTestCase(TestCase):
    def test_stream_response_normalizes_reasoning_content_and_usage(self):
        """Test _stream_response yields reasoning_content and usage in normalized chunks."""
        fake_service = {
            "name": "TestProvider",
            "url": "https://api.test.com/v1/chat/completions",
            "api_key": "test-key",
        }
        fake_headers = {
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        }
        fake_body = {"model": "test-model", "stream": True}

        class FakeResponse:
            def __init__(self):
                self.status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def raise_for_status(self):
                pass

            def iter_lines(self):
                return [
                    b'data: {"id":"x","choices":[{"index":0,"delta":{"reasoning_content":"think","content":"hi"}}],"usage":{"total_tokens":5}}',
                    b"",
                    b"data: [DONE]",
                ]

        with mock.patch("api.views.requests.post", return_value=FakeResponse()):
            response = _stream_response(fake_service, fake_headers, fake_body)
            content = b"".join(response.streaming_content)
            content_str = content.decode("utf-8")

            self.assertIn("reasoning_content", content_str)
            self.assertIn("usage", content_str)
            self.assertIn("total_tokens", content_str)
            self.assertIn("data: [DONE]", content_str)

            # Check parsed chunk JSON structure
            lines = [l for l in content_str.split("\n\n") if l.startswith("data: ") and not l.strip() == "data: [DONE]"]
            self.assertTrue(len(lines) >= 1)
            chunk_data = json.loads(lines[0][6:])
            self.assertEqual(chunk_data["choices"][0]["delta"]["reasoning_content"], "think")
            self.assertEqual(chunk_data["choices"][0]["delta"]["content"], "hi")
            self.assertEqual(chunk_data["choices"][0]["index"], 0)
            self.assertEqual(chunk_data["usage"], {"total_tokens": 5})
