import os, os.path, sys
import tomli

default_config_toml = """\
[auth]
client-id = "(your client-id)"
client-secret = "(your client-secret)"
redirect-uri = "http://127.0.0.1:18444"
"""

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
    redirect_uri = config['auth']['redirect-uri']

# Ensure the user actually modified the config file
if client_id == "(your client-id)" or client_secret == "(your client-secret)":
    print(f"Edit '{config_file}' to supply a valid client ID and secret")
    sys.exit(0)
