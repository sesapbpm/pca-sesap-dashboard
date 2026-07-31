from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import webbrowser


PORTA = 8765
ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        # Evita que um console/pipe fechado interrompa a resposta HTTP.
        pass


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    endereco = f"http://localhost:{PORTA}"
    servidor = Server(("127.0.0.1", PORTA), Handler)
    print(f"Dashboard SESAP disponível em {endereco}")
    print("Mantenha esta janela aberta enquanto estiver usando o painel.")
    webbrowser.open(endereco)
    servidor.serve_forever()
