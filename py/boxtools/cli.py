import os, os.path, sys, argparse, pprint, re, shutil
import json, pickle
import tomli

# Preliminaries {{{1

# The invoking shell script must set $BOXTOOLS_APP_DIR
app_dir = os.environ.get("BOXTOOLS_APP_DIR")
if not app_dir:
    print("You must set $BOXTOOLS_APP_DIR before running this program!")
    sys.exit(1)

# The user can override the default ~/.boxtools directory by setting $BOXTOOLS_DIR
config_dir = os.environ.get("BOXTOOLS_DIR", os.path.expanduser("~/.boxtools"))

# We keep certain resources as their own files for easy editing
with open(os.path.join(app_dir, 'resources/usage.txt'), "rt") as f:
    general_usage = f.read().\
        format(progname=os.path.basename(sys.argv[0]),
               app_dir=app_dir, config_dir=config_dir)

if not os.path.exists(config_dir):
    print(f"Creating {config_dir}...")
    os.mkdir(config_dir)

# These are the configuration files
config_file = os.path.join(config_dir, "boxtools.toml")
tokens_file = os.path.join(config_dir, "auth-tokens.json")
prev_ids_file = os.path.join(config_dir, "previous-ids.pickle")
aliases_file = os.path.join(config_dir, "id-aliases.toml")

# If no config file exists, write the default and exit
if not os.path.exists(config_file):
    print(f"Edit the default config file at '{config_file}'")
    shutil.copyfile(os.path.join(app_dir, 'resources/boxtools.toml'), config_file)
    sys.exit(0)

# Read the config
with open(config_file, 'rb') as f:
    config = tomli.load(f)
    auth_table = config['auth']
    client_id = auth_table['client-id']
    client_secret = auth_table['client-secret']
    redirect_urls = {'internal' : auth_table['internal-redirect-url'],
                     'external' : auth_table['external-redirect-url']}
    config_table = config['config']
    id_history_size = config_table['id-history-size']

if os.path.exists(prev_ids_file):
    with open(prev_ids_file, 'rb') as f:
        prev_id_map = pickle.load(f)
else:
    prev_id_map = {}

if not os.path.exists(aliases_file):
    shutil.copyfile(os.path.join(app_dir, 'resources/id-aliases.toml'), aliases_file)
with open(aliases_file, 'rb') as f:
    id_aliases = tomli.load(f)['aliases']

# Ensure the user actually modified the config file
if client_id == "(your client-id)" or client_secret == "(your client-secret)":
    print(f"Edit '{config_file}' to supply a valid client ID and secret")
    sys.exit(0)

# Print help if we need to
if len(sys.argv) == 1 or sys.argv[1] in ('-h', '--help'):
    print(general_usage, end="")
    sys.exit(1)

# Support functions {{{1

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

# Loads boxtools.ops as 'ops' in the global namespace, and retrieves a Box Client object
def get_ops_client():
    global ops
    import boxtools.ops as ops
    access_token, refresh_token = load_tokens_or_die()
    from .auth import get_client
    return get_client(client_id, client_secret, access_token, refresh_token, save_tokens)

def print_table(items, fields, colgap=4, print_header=True):
    max_field_len = [0] * len(fields)
    for item in items:
        for i, field in enumerate(fields):
            max_field_len[i] = max(max_field_len[i], len(getattr(item, field)))
    for i in range(len(max_field_len) - 1):
        max_field_len[i] += colgap
    if print_header:
        for i, field in enumerate(fields):
            print(f"{field.capitalize():{max_field_len[i]}}", end="")
        print()
        print("-" * sum(max_field_len))
    for item in items:
        for i, field in enumerate(fields):
            print(f"{getattr(item, field):{max_field_len[i]}}", end="")
        print()
    return sum(max_field_len)

def translate_id(id_):
    if id_ in id_aliases:
        return str(id_aliases[id_])
    elif len(id_) >= 3 and id_[0] == '/' and id_[-1] == '/':  # a regex
        matched_ids = []
        reo = re.compile(id_[1:-1], re.IGNORECASE)
        for entry in prev_id_map.items():
            if any(reo.search(part) for part in entry):
                matched_ids.append(entry)
        if len(matched_ids) == 0:
            print(f"{id_} did not match any previous IDs")
            sys.exit(2)
        elif len(matched_ids) > 1:
            print(f"{id_} matched multiple previous IDs:\n")
            for entry in matched_ids:
                print(f"  {entry}")
            sys.exit(2)
        else:
            return matched_ids[0][0]
    else:  # Not a special syntax
        return id_

# Define command functions {{{1

def auth_cmd(args):
    cli_parser = argparse.ArgumentParser(usage='%(prog)s auth [options]',
                                         description='Authenticate (via OAuth2) with Box')
    cli_parser.add_argument('-B', '--no-browser', action='store_true',
                            help="Do not open a browser window to the authorization URL")
    cli_parser.add_argument('-e', '--external-redirect', action='store_true',
                            help="Redirect to an external address to retrieve the auth code")
    options = cli_parser.parse_args(args)
    from .auth import retrieve_tokens
    redirect_url = redirect_urls['external' if options.external_redirect else 'internal']
    retrieve_tokens(client_id, client_secret, redirect_url, save_tokens,
                    run_server=not options.external_redirect, open_browser=not options.no_browser)
    print(f"Tokens saved to {tokens_file}")

def refresh_cmd(args):
    if len(args):
        print(f"usage: {os.path.basename(sys.argv[0])} refresh\n\n"
               "Manually refresh access tokens")
        sys.exit(1)
    access_token, refresh_token = load_tokens_or_die()
    from .auth import refresh_tokens
    refresh_tokens(client_id, client_secret, access_token, refresh_token, save_tokens)
    print(f"Tokens refreshed and saved")

def userinfo_cmd(args):
    if len(args):
        print(f"usage: {os.path.basename(sys.argv[0])} userinfo\n\n"
               "Print authorized user information as a JSON object")
        sys.exit(1)
    client = get_ops_client()
    user = ops.getuserinfo(client)
    infodict = {field : getattr(user, field) for field in ('id', 'login', 'name')}
    print(json.dumps(infodict, indent=2))

def list_folder(args):
    global prev_id_map
    cli_parser = argparse.ArgumentParser(usage='%(prog)s list [options] id [id...]',
                                         description='List a folder')
    cli_parser.add_argument('id', nargs='+', help='Folder ID(s)')
    cli_parser.add_argument('-f', '--fields', default="type, name, id",
                            help='Comma-separated list of Box item fields to list')
    cli_parser.add_argument('-H', '--no-header', action='store_true',
                            help='Do not print header text for the listing')
    cli_parser.add_argument('-J', '--json', action='store_true',
                            help='Print folder contents as JSON (implies --no-header)')
    options = cli_parser.parse_args(args)
    folder_ids = [translate_id(_id) for _id in options.id]
    fields = [field.strip() for field in options.fields.split(",")]
    print_header = not options.no_header
    json_format = options.json
    record_ids = 'id' in fields and 'name' in fields
    client = get_ops_client()
    for i, folder_id in enumerate(folder_ids):
        folder, items = ops.list_folder(client, folder_id, fields=fields)
        if record_ids:
            prev_id_map[folder_id] = folder.name
            if _p := folder.parent:
                prev_id_map[_p.id] = _p.name
            prev_id_map.update((item.id, item.name) for item in items)
        if json_format:
            print(json.dumps([{field : getattr(item, field) for field in fields}
                              for item in items], indent=2))
        else:
            if i != 0:  # Note that table_width is set at the end of this block
                print("\n" + "=" * table_width + "\n")
            if print_header:
                folder_header_info = f"{folder.name} | {folder.id}"
                if _p := folder.parent:
                    folder_header_info += f" - (Parent: {_p.name} | {_p.id})"
                print(folder_header_info, end="\n\n")
            table_width = print_table(items, fields, print_header=print_header)

# A mapping of command names to the implementing command function
command_funcs = {
    'auth' : auth_cmd,
    'refresh' : refresh_cmd,
    'userinfo' : userinfo_cmd,
    'list' : list_folder, 'ls' : list_folder,
}

# Run the appropriate command function {{{1

command = sys.argv[1]
command_args = sys.argv[2:]

if command not in command_funcs:
    print(f"Unknown command '{command}'")
    sys.exit(2)

try:
    command_funcs[command](command_args)
finally:
    if (ndel := len(prev_id_map) - id_history_size) > 0:
        keys = list(prev_id_map.keys())
        for k in keys[0:ndel]:
            del prev_id_map[k]
    with open(prev_ids_file, "wb") as f:
        pickle.dump(prev_id_map, f)
