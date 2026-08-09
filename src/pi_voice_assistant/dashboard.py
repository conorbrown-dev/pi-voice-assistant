"""Local HTTP API and static-file server for the touchscreen dashboard."""

from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from .commands import parse_reminder_schedule, parse_reminder_time, strip_punctuation
from .storage import Store


def _item(todo: object) -> dict[str, object]:
    return {"id": todo.id, "text": todo.text, "createdAt": todo.created_at.isoformat()}  # type: ignore[attr-defined]


def _reminder(reminder: object) -> dict[str, object]:
    return {
        "id": reminder.id,  # type: ignore[attr-defined]
        "text": reminder.text,  # type: ignore[attr-defined]
        "dueAt": reminder.due_at.isoformat(),  # type: ignore[attr-defined]
        "recurrence": reminder.recurrence,  # type: ignore[attr-defined]
        "status": reminder.status,  # type: ignore[attr-defined]
    }


class DashboardHandler(BaseHTTPRequestHandler):
    store: Store
    web_root: Path

    def log_message(self, format: str, *args: object) -> None:
        print(f"Dashboard: {format % args}")

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("Request body must be JSON.") from error
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._get_api(parsed.path, parse_qs(parsed.query))
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._body()
            now = datetime.now()
            if self.path == "/api/todos":
                text = strip_punctuation(str(body.get("text", "")))
                if not text:
                    self._error("Todo text is required.")
                    return
                self._json(_item(self.store.add_todo(text, now)), HTTPStatus.CREATED)
                return
            if self.path == "/api/shopping-items":
                text = strip_punctuation(str(body.get("text", "")))
                if not text:
                    self._error("Shopping item text is required.")
                    return
                self._json(_item(self.store.add_shopping_item(text, now)), HTTPStatus.CREATED)
                return
            if self.path == "/api/reminders":
                text = strip_punctuation(str(body.get("text", "")))
                schedule = strip_punctuation(str(body.get("schedule", "")))
                due_at, recurrence = parse_reminder_schedule(schedule, now)
                if due_at is None:
                    due_at = parse_reminder_time(schedule, now)
                if not text or due_at is None:
                    self._error("Enter a reminder and a time such as 'in 10 minutes' or 'every day at 9 am'.")
                    return
                self._json(_reminder(self.store.add_reminder(text, due_at, now, recurrence)), HTTPStatus.CREATED)
                return
            if self.path.startswith("/api/reminders/") and self.path.endswith("/complete"):
                reminder_id = int(self.path.split("/")[3])
                self.store.complete_reminder(reminder_id, now)
                self._json({"ok": True})
                return
            self._error("Unknown endpoint.", HTTPStatus.NOT_FOUND)
        except (ValueError, IndexError):
            self._error("Invalid request.")

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            now = datetime.now()
            path = self.path.rstrip("/")
            if path.startswith("/api/todos/"):
                todo = self.store.archive_todo_id(int(path.rsplit("/", 1)[1]), now)
                self._json({"ok": todo})
                return
            if path.startswith("/api/shopping-items/"):
                item = self.store.archive_shopping_item(int(path.rsplit("/", 1)[1]), now)
                self._json({"ok": item})
                return
            self._error("Unknown endpoint.", HTTPStatus.NOT_FOUND)
        except ValueError:
            self._error("Invalid item ID.")

    def _get_api(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/todos":
            self._json([_item(todo) for todo in self.store.list_todos()])
        elif path == "/api/reminders":
            self._json([_reminder(reminder) for reminder in self.store.list_active_reminders()])
        elif path == "/api/shopping-items":
            self._json([_item(item) for item in self.store.list_shopping_items()])
        elif path == "/api/weather":
            self._weather(query)
        else:
            self._error("Unknown endpoint.", HTTPStatus.NOT_FOUND)

    def _weather(self, query: dict[str, list[str]]) -> None:
        location = query.get("location", ["Sapulpa, Oklahoma"])[0]
        try:
            geocode_url = "https://geocoding-api.open-meteo.com/v1/search?name=" + location.replace(" ", "+") + "&count=1"
            with urlopen(geocode_url, timeout=8) as response:  # noqa: S310 - fixed public API URL
                place = json.load(response)["results"][0]
            forecast_url = (
                "https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&current=temperature_2m,weather_code&daily="
                "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&temperature_unit=fahrenheit&timezone=auto"
            ).format(place["latitude"], place["longitude"])
            with urlopen(forecast_url, timeout=8) as response:  # noqa: S310 - fixed public API URL
                forecast = json.load(response)
            self._json({"location": f"{place['name']}, {place.get('admin1', place.get('country', ''))}", "forecast": forecast})
        except (KeyError, IndexError, OSError, TimeoutError, json.JSONDecodeError):
            self._error("Weather is unavailable. Check the network connection or location.", HTTPStatus.SERVICE_UNAVAILABLE)

    def _static(self, request_path: str) -> None:
        relative = request_path.lstrip("/") or "index.html"
        candidate = (self.web_root / relative).resolve()
        if self.web_root not in candidate.parents and candidate != self.web_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            candidate = self.web_root / "index.html"
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Build the dashboard first with npm run build.")
            return
        content = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Touchscreen dashboard for Orange Castle Assistant")
    parser.add_argument("--database", type=Path, default=Path.home() / ".local/share/pi-voice-assistant/assistant.db")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (use 0.0.0.0 only for trusted local networks)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--web-root", type=Path, default=project_root / "web" / "dist")
    args = parser.parse_args()
    store = Store(args.database)
    DashboardHandler.store = store
    DashboardHandler.web_root = args.web_root.resolve()
    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard available at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
