import sys
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
import requests

import logging
# Konfiguration
HOST = "127.0.0.1"
PORT = 11435
OLLAMA_URL = "http://localhost:11434/api/generate"

logging.basicConfig(level=logging.INFO)

class OllamaHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            prompt = data.get("prompt", "")
            model = data.get("model", "mistral")
            req_data = {"model": model, "prompt": prompt, "stream": False}
            logging.info(f"Ollama-Worker: Anfrage erhalten: Modell={model}, Prompt={prompt}")
            response = requests.post(OLLAMA_URL, json=req_data, timeout=60)
            response.raise_for_status()
            result_json = response.json()
            result = result_json.get("response", "")
            logging.info(f"Ollama-Worker: Antwort erhalten: {result[:80]}")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"result": result}).encode())
        except Exception as e:
            logging.error(f"Ollama-Worker: Fehler: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), OllamaHandler)
    print(f"AIID Ollama Worker läuft auf http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Beende Worker...")
        server.server_close()
