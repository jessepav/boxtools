import os, os.path, sys, argparse
import json
import tomli

# Preliminaries {{{1

# The invoking shell script must set $BOXTOOLS_APP_DIR
app_dir = os.environ.get("BOXTOOLS_APP_DIR")
if not app_dir:
    print("You must set $BOXTOOLS_APP_DIR before running this program!")
    sys.exit(1)

# We keep certain resources as their own files for easy editing
with open(os.path.join(app_dir, 'resources/boxtools.toml'), "rt") as f:
    default_config_toml = f.read()
with open(os.path.join(app_dir, 'resources/usage.txt'), "rt") as f:
    general_usage = f.read().format(progname=os.path.basename(sys.argv[0]))

# The user can override the default ~/.boxtools directory by setting $BOXTOOLS_DIR
config_dir = os.environ.get("BOXTOOLS_DIR", os.path.expanduser("~/.boxtools"))
if not os.path.exists(config_dir):
    print(f"Creating {config_dir}...")
    os.mkdir(config_dir)

# These are the configuration files
config_file = os.path.join(config_dir, "boxtools.toml")
tokens_file = os.path.join(config_dir, "auth-tokens.json")

# If no config file exists, write the default and exit
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
if len(sys.argv) == 1 or sys.argv[1] in ('-h', '--help'):
    print(general_usage, end="")
    sys.exit(1)

# Support functions for working with the tokens file {{{1

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

# Definte command functions {{{1

def auth_cmd(args):
    from .auth import retrieve_tokens
    retrieve_tokens(client_id, client_secret, redirect_url, save_tokens)
    print(f"Tokens saved to {tokens_file}")

def refresh_cmd(args):
    access_token, refresh_token = load_tokens_or_die()
    from .auth import refresh_tokens
    refresh_tokens(client_id, client_secret, access_token, refresh_token, save_tokens)
    print(f"Tokens refreshed and saved")

def userinfo_cmd(args, client):
    user = ops.getuserinfo(client)
    infodict = {field : getattr(user, field) for field in ('id', 'login', 'name')}
    print(json.dumps(infodict, indent=2))

# A mapping of command names to the implementing command function along
# with a bool indicating if the command requires a Box client object as the
# second parameter.
command_funcs = {
    'auth' : (auth_cmd, False),
    'refresh' : (refresh_cmd, False),
    'userinfo' : (userinfo_cmd, True)
}

# Run the appropriate command function {{{1

command = sys.argv[1]
command_args = sys.argv[2:]

if command not in command_funcs:
    print(f"Unknown command '{command}'")
    sys.exit(2)

cmdfunc, need_client = command_funcs[command]
if need_client:
    import boxtools.ops as ops  # All client operations are defined in ops
    access_token, refresh_token = load_tokens_or_die()
    from .auth import get_client
    client = get_client(client_id, client_secret, access_token, refresh_token, save_tokens)
    cmdfunc(command_args, client)
else:
    cmdfunc(command_args)
