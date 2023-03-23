from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread

from boxsdk import OAuth2, Client

http_server = None
auth_url, csrf_token = None, None
authcode = None

class OAuthRequestHandler(BaseHTTPRequestHandler):
    server_version = "boxtools/0.1"

    def do_GET(self):
        global authcode
        url = urlparse(self.path)
        query_params = parse_qs(url.query)
        authcode = query_params.get('code', [None])[0]
        ctoken = query_params.get('state', [None])[0]
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if authcode and ctoken == csrf_token:
            self.wfile.write("Authcode retrieved -- return to boxtools".encode())
            shutdown_server()
        else:
            self.wfile.write("The request did not include appropriate 'code' and 'state' query parameters".encode())
            print(authcode, ctoken, csrf_token)

    def log_message(format, *args):
        pass

def shutdown_server():
    thread = Thread(target = http_server.shutdown)
    thread.start()

def start_server(port):
    global http_server
    http_server = HTTPServer(('127.0.0.1', port), OAuthRequestHandler)
    http_server.serve_forever()

def retrieve_tokens(client_id, client_secret, redirect_url):
    global auth_url, csrf_token, authcode
    oauth = OAuth2(client_id=client_id, client_secret=client_secret)
    auth_url, csrf_token = oauth.get_authorization_url(redirect_url)
    port = urlparse(redirect_url).port
    if not port:
        print("The redirect URL must include an explicit port number.")
        sys.exit(1)
    import webbrowser
    print("Opening a web browser to URL:\n\n", auth_url, sep='')
    webbrowser.open(auth_url)
    start_server(port)  # This blocks until we retrieve the authcode!
    access_token, refresh_token = oauth.authenticate(authcode)
    return access_token, refresh_token

def refresh_tokens(client_id, client_secret, access_token, refresh_token):
    oauth = OAuth2(client_id=client_id, client_secret=client_secret,
                   access_token=access_token, refresh_token=refresh_token)
    access_token, refresh_token = oauth.refresh(access_token)
    return access_token, refresh_token

def get_client(client_id, client_secret, access_token, refresh_token):
    oauth = OAuth2(client_id=client_id, client_secret=client_secret,
                   access_token=access_token, refresh_token=refresh_token)
    client = Client(oauth)
    return client

