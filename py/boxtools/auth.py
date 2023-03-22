from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread

port = 18444

http_server = None

class OAuthRequestHandler(BaseHTTPRequestHandler):
    server_version = "boxtools/0.1"

    def do_GET(self):
        print("Path:", self.path)
        url = urlparse(self.path)
        query_params = parse_qs(url.query)
        print("Query Params:", query_params)
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if url.path == '/shutdown':
            shutdown_server()
            self.wfile.write("Shutting down...".encode())
        else:
            self.wfile.write("That URL, I'm afraid, has no meaning to me.".encode())

    def log_message(format, *args):
        pass

def shutdown_server():
    print("Shutting down...")
    thread = Thread(target = lambda: http_server.shutdown())
    thread.start()

def start_server():
    global http_server
    print(f"Starting server on port {port}...")
    http_server = HTTPServer(('127.0.0.1', port), OAuthRequestHandler)
    http_server.serve_forever()

if __name__ == '__main__':
    start_server()
