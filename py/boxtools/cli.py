import os, os.path, sys
import json
import tomli

default_config_toml = """\
[auth]
client-id = "(your client-id)"
client-secret = "(your client-secret)"
redirect-url = "http://127.0.0.1:18444"
"""

usage = """\
Usage: boxcli.sh command [args...]

Commands:
    auth        obtain auth tokens via OAuth2
    refresh     refresh existing auth tokens

    userinfo    print user info as JSON
"""

# The user can override the default ~/.boxtools directory via $BOXTOOLS_DIR
config_dir = os.environ.get("BOXTOOLS_DIR", os.path.expanduser("~/.boxtools"))

if not os.path.exists(config_dir):
    print(f"Creating {config_dir}...")
    os.mkdir(config_dir)

config_file = os.path.join(config_dir, "boxtools.toml")
tokens_file = os.path.join(config_dir, "auth-tokens.json")

if not os.path.exists(config_file):
    print(f"Edit the default config file at '{config_file}'")
    with open(config_file, 'wt') as f:
        f.write(default_config_toml)
        sys.exit(0)

# Read the config
with open(config_file, 'rb') as f:
    config = tomli.load(f)
    client_id = config['auth']['client-id']
    client_secret = config['auth']['client-secret']
    redirect_url = config['auth']['redirect-url']

# Ensure the user actually modified the config file
if client_id == "(your client-id)" or client_secret == "(your client-secret)":
    print(f"Edit '{config_file}' to supply a valid client ID and secret")
    sys.exit(0)

# Print help if we need to
args = sys.argv[1:]
if len(args) == 0 or any(flag in args for flag in ('-h', '--help')):
    print(usage, end="")
    sys.exit(1)

# Two functions to work with the tokens file
def save_tokens(access_token, refresh_token):
    with open(tokens_file, 'wt') as f:
        json.dump({ 'access_token' : access_token, 'refresh_token' : refresh_token }, f, 
                  indent=2)
        f.write('\n')  # We want the file to end in a newline, like a usual text file

def load_tokens_or_die():
    if not os.path.exists(tokens_file):
        print("You must first retrieve auth tokens by using the 'auth' command")
        sys.exit(1)
    with open(tokens_file, 'rt') as f:
        tokendict = json.load(f)
    return tokendict['access_token'], tokendict['refresh_token']

import boxtools.ops as ops

# And now our big command if-else
command = args.pop(0)
# The auth commands are special in that they don't need a client
if command == "auth":
    from .auth import retrieve_tokens
    access_token, refresh_token = retrieve_tokens(client_id, client_secret, redirect_url)
    save_tokens(access_token, refresh_token)
    print(f"Tokens saved to {tokens_file}")
elif command == "refresh":
    access_token, refresh_token = load_tokens_or_die()
    from .auth import refresh_tokens
    access_token, refresh_token = refresh_tokens(client_id, client_secret, access_token, refresh_token)
    save_tokens(access_token, refresh_token)
    print(f"Tokens refreshed and saved")
else:  # All the other commands depend upon a client
    access_token, refresh_token = load_tokens_or_die()
    from .auth import get_client
    client = get_client(client_id, client_secret, access_token, refresh_token, save_tokens)
    if command == "userinfo":
        user = ops.getuserinfo(client)
        infodict = {field : getattr(user, field) for field in ('id', 'login', 'name')}
        print(json.dumps(infodict, indent=2))
    else:
        print(f"Unknown command '{command}'")
        sys.exit(2)
