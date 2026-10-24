import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from paula_hub.adapters.outbound.alexa.notifier import AlexaNotifier
from paula_hub.adapters.signing import sign, verify
from paula_hub.domain.messages import Alert

SECRET = "s3cret"
LAMBDA = Path(__file__).parents[2] / "alexa-skill" / "lambda" / "lambda_function.py"


def load_lambda():
    spec = importlib.util.spec_from_file_location("paula_alexa_lambda", LAMBDA)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notifier_posts_signed_alert():
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received["body"] = body
            received["headers"] = {k.lower(): v for k, v in self.headers.items()}
            self.send_response(202)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    AlexaNotifier(f"http://127.0.0.1:{server.server_port}", SECRET).notify(
        Alert(title="Tarea terminada", message="Listo")
    )
    thread.join(timeout=5)
    server.server_close()

    verify(SECRET, received["body"], received["headers"])
    assert json.loads(received["body"])["title"] == "Tarea terminada"


def test_notifier_swallows_connection_errors():
    AlexaNotifier("http://127.0.0.1:9", SECRET, timeout=0.5).notify(Alert("t", "m"))


def test_lambda_rejects_unsigned_request(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", SECRET)
    module = load_lambda()

    response = module.lambda_handler({"body": "{}", "headers": {}}, None)

    assert response["statusCode"] == 401


def test_lambda_builds_message_alert(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", SECRET)
    module = load_lambda()
    body = json.dumps(Alert("Paula", "Listo").to_dict()).encode()
    sent = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request):
        sent["url"] = request.full_url
        sent["data"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(module, "_access_token", lambda: "token")
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    response = module.lambda_handler({"body": body.decode(), "headers": sign(SECRET, body)}, None)

    assert response["statusCode"] == 202
    assert sent["url"].endswith("/v1/proactiveEvents/stages/development")
    event = sent["data"]["event"]
    assert event["name"] == "AMAZON.MessageAlert.Activated"
    assert event["payload"]["messageGroup"]["creator"]["name"] == "Paula"
