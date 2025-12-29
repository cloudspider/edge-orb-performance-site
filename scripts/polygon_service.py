import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from polygon_downloader import download_symbol_data

BASE_DIR = Path(__file__).resolve().parents[1]
SYMBOL_RE = re.compile(r"^[A-Z0-9.-]+$")
DOWNLOAD_STATUS: dict[str, dict[str, str]] = {}


class PolygonRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_POST(self) -> None:
        if self.path.startswith("/api/polygon-download"):
            self._handle_download()
            return
        super().do_POST()

    def do_GET(self) -> None:
        if self.path.startswith("/api/polygon-download/status"):
            self._handle_download_status()
            return
        if self.path.startswith("/api/polygon-download"):
            self._handle_download()
            return
        super().do_GET()

    def _handle_download(self) -> None:
        symbol = self._extract_symbol()
        if not symbol:
            self._send_json({"error": "Missing symbol."}, HTTPStatus.BAD_REQUEST)
            return
        if not SYMBOL_RE.match(symbol):
            self._send_json({"error": "Invalid symbol format."}, HTTPStatus.BAD_REQUEST)
            return
        self._set_status(symbol, "running", f"Starting download for {symbol}...")
        try:
            df = download_symbol_data(symbol, progress=lambda msg: self._set_status(symbol, "running", msg))
        except Exception as exc:
            self._set_status(symbol, "error", f"Download failed: {exc}")
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        output_path = BASE_DIR / "data" / f"{symbol}_1m.csv"
        if df is None:
            if output_path.exists():
                self._set_status(symbol, "done", "Data already up to date.")
                self._send_json(
                    {
                        "ok": True,
                        "symbol": symbol,
                        "rows": 0,
                        "path": f"data/{symbol}_1m.csv",
                        "note": "up-to-date",
                    },
                    HTTPStatus.OK,
                )
                return
            self._set_status(symbol, "error", "No data returned from Polygon.")
            self._send_json({"error": "No data returned from Polygon."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        rows = int(df.shape[0])
        self._set_status(symbol, "done", f"Downloaded {rows} rows.")
        self._send_json(
            {
                "ok": True,
                "symbol": symbol,
                "rows": rows,
                "path": f"data/{symbol}_1m.csv",
            },
            HTTPStatus.OK,
        )

    def _extract_symbol(self) -> str:
        parsed = urlparse(self.path)
        if parsed.query:
            params = parse_qs(parsed.query)
            symbol = params.get("symbol", [""])[0]
            return (symbol or "").strip().upper()
        if self.command != "POST":
            return ""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return ""
        try:
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body) if body else {}
        except Exception:
            return ""
        return str(payload.get("symbol", "")).strip().upper()

    def _handle_download_status(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        symbol = (params.get("symbol", [""])[0] or "").strip().upper()
        if not symbol:
            self._send_json({"error": "Missing symbol."}, HTTPStatus.BAD_REQUEST)
            return
        status = DOWNLOAD_STATUS.get(symbol)
        if not status:
            self._send_json({"ok": False, "symbol": symbol, "state": "idle", "message": ""}, HTTPStatus.OK)
            return
        payload = {"ok": True, "symbol": symbol, **status}
        self._send_json(payload, HTTPStatus.OK)

    def _set_status(self, symbol: str, state: str, message: str) -> None:
        DOWNLOAD_STATUS[symbol] = {"state": state, "message": message}

    def _send_json(self, payload: dict, status: HTTPStatus) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer(("localhost", 8000), PolygonRequestHandler)
    print("Serving on http://localhost:8000 (CTRL+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
