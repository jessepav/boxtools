import os, os.path, sys, argparse, pprint, re, shutil, logging
from types import SimpleNamespace as BareObj
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

ops_client = None

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

# Retrieves and caches a Box Client object
def get_ops_client():
    global ops_client
    if ops_client is None:
        access_token, refresh_token = load_tokens_or_die()
        from .auth import get_client
        ops_client = get_client(client_id, client_secret, access_token, refresh_token, save_tokens)
        # Prevent the Box SDK from spewing logging messages
        logging.getLogger('boxsdk').setLevel(logging.CRITICAL)
    return ops_client

def print_table(items, fields, colgap=4, print_header=True):
    max_field_len = [len(field) for field in fields]
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

def _choose_id(id_, matched_ids):
    if len(matched_ids) == 0:
        print(f'"{id_}" did not match any previous IDs')
        return None
    elif len(matched_ids) > 1:
        print(f'"{id_}" matched multiple previous IDs (listed from old to new):\n')
        choices = []
        for i, entry in enumerate(matched_ids, start=1):
            choice = BareObj()
            choice.n = str(i)
            choice.id = entry[0]
            choice.name = entry[1]
            choices.append(choice)
        print_table(choices, ('n', 'name', 'id'))
        print()
        choice = int(input('choice # (n)> ')) - 1
        if choice >= 0 and choice < len(matched_ids):
            return matched_ids[choice][0]
        else:
            return None
    else:
        return matched_ids[0][0]

def translate_id(id_):
    if id_ in id_aliases:
        return str(id_aliases[id_])
    if id_.startswith('%'):
        term = id_[1:]
        matched_ids = []
        for entry in prev_id_map.items():
            if term in entry[1]:
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif id_.startswith('='):
        term = id_[1:]
        matched_ids = []
        for entry in prev_id_map.items():
            if term == entry[1]:
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif id_.startswith('^'):
        term = id_[1:]
        matched_ids = []
        for entry in prev_id_map.items():
            if entry[1].startswith(term):
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif id_.endswith('$'):
        term = id_[0:-1]
        matched_ids = []
        for entry in prev_id_map.items():
            if any(part.endswith(term) for part in entry):
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif id_.count('/') == 1:
        s, n = id_.split('/')
        matched_ids = []
        for entry in prev_id_map.items():
            entry_id, entry_name = entry
            if s in entry_name and entry_id.endswith(n):
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif len(id_) >= 3 and id_[0] == '/' and id_[-1] == '/':  # a regex
        matched_ids = []
        reo = re.compile(id_[1:-1], re.IGNORECASE)
        for entry in prev_id_map.items():
            if any(reo.search(part) for part in entry):
                matched_ids.append(entry)
        return _choose_id(id_, matched_ids)
    elif id_.isdigit():
        return id_
    else:
        print(f"{id_} is not a valid item ID")
        return None

# Define command functions {{{1

def auth_cmd(args):  # {{{2
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

def refresh_cmd(args):  # {{{2
    if len(args):
        print(f"usage: {os.path.basename(sys.argv[0])} refresh\n\n"
               "Manually refresh access tokens")
        return
    access_token, refresh_token = load_tokens_or_die()
    from .auth import refresh_tokens
    refresh_tokens(client_id, client_secret, access_token, refresh_token, save_tokens)
    print(f"Tokens refreshed and saved")

def userinfo_cmd(args):  # {{{2
    if len(args):
        print(f"usage: {os.path.basename(sys.argv[0])} userinfo\n\n"
               "Print authorized user information as a JSON object")
        return
    client = get_ops_client()
    user = client.user().get()
    infodict = {field : getattr(user, field) for field in ('id', 'login', 'name')}
    print(json.dumps(infodict, indent=2))

def ls_folder(args):  # {{{2
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
    if any(id is None for id in folder_ids):  # translate_id() failed
        return
    fields = [field.strip() for field in options.fields.split(",")]
    print_header = not options.no_header
    json_format = options.json
    record_ids = 'id' in fields and 'name' in fields
    client = get_ops_client()
    for i, folder_id in enumerate(folder_ids):
        folder = client.folder(folder_id=folder_id)
        items = list(folder.get_items(fields=fields))
        folder = folder.get()
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
                else:
                    folder_header_info += " - (Parent: All Files | 0)"
                print(folder_header_info, end="\n\n")
            table_width = print_table(items, fields, print_header=print_header)

def search(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s search [options] term',
                                         description='Search for items')
    cli_parser.add_argument('term', help='Search term')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Search for files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Search for folders')
    cli_parser.add_argument('-l', '--limit', type=int, default=10,
                            help='Maximum number of items to return')
    cli_parser.add_argument('-n', '--name-only', action='store_true',
                            help='Search only in item names rather than in all content')
    cli_parser.add_argument('-P', '--no-parent', action='store_true',
                            help="Don't include parent folder information in output")
    options = cli_parser.parse_args(args)
    term = options.term
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    limit = options.limit
    name_only = options.name_only
    no_parent = options.no_parent
    fields=['name', 'id', 'parent'] if not no_parent else ['name', 'id']
    client = get_ops_client()
    results = client.search().query(query=term, limit=limit, offset=0,
                                    result_type='file' if do_files else 'folder',
                                    content_types=['name'] if name_only else None, fields=fields)
    # We can't just throw the iterator returned by query() into a list(), because it stalls,
    # so we need to manually retrieve 'limit' items
    items = []
    for i, r in enumerate(results, start=1):
        item = BareObj()
        item.name, item.id = r.name, r.id
        prev_id_map[item.id] = item.name
        if not no_parent:
            parent = r.parent
            if parent:
                item.parent, item.parent_id = parent.name, parent.id
                prev_id_map[parent.id] = parent.name
            else:
                item.parent, item.parent_id = 'N/A', 'N/A'
        items.append(item)
        if i == limit: break
    print_table(items, ('name', 'id', 'parent', 'parent_id') if not no_parent else
                       ('name', 'id'))

def get_files(args):  # {{{2
    if len(args) < 2 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} get file_id [file_id...] directory\n\n"
               "Download files")
        return
    target_dir = args[-1]
    file_ids = [translate_id(id) for id in args[0:-1]]
    if any(id is None for id in file_ids):
        return
    if not os.path.isdir(target_dir):
        print(f"{target_dir} is not a directory!")
        return
    client = get_ops_client()
    for file_id in file_ids:
        file = client.file(file_id)
        filename = file.get(fields=['name']).name
        print(f"Downloading {filename}...")
        with open(os.path.join(target_dir, filename), "wb") as f:
           file.download_to(f)

def put_file(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s put [options] file(s)',
                                         description='Upload a file')
    cli_parser.add_argument('files', nargs='+', help='File(s) to upload')
    cli_parser.add_argument('-f', '--file-version', metavar='file_id',
                            help='Upload a new version of a file')
    cli_parser.add_argument('-d', '--folder', metavar='folder_id',
                            help='Upload a file into a given folder')
    options = cli_parser.parse_args(args)
    file_id = options.file_version
    folder_id = options.folder
    files = options.files
    if not any((file_id, folder_id)) or all((file_id, folder_id)):
        print("You must supply exactly one of --version/-f or --folder/-d")
        return
    if file_id and len(files) != 1:
        print("You must supply exactly one file to upload a new version")
        return
    client = get_ops_client()
    if file_id:
        file = client.file(translate_id(file_id))
        box_filename = file.get(fields=['name']).name
        filepath = files[0]
        print(f"Uploading {filepath} as a new version of {box_filename}...", end="")
        file.update_contents(filepath)
        print("done")
    elif folder_id:
        folder = client.folder(translate_id(folder_id))
        foldername = folder.get(fields=['name']).name
        for filepath in files:
            print(f"Uploading {filepath} to {foldername}...", end="")
            folder.upload(filepath)
            print("done")

def rm_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s rm [options] ids...',
                                         description='Remove files or folders')
    cli_parser.add_argument('ids', nargs='+', help='File or folder IDs to remove')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Remove files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Remove folders')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    item_ids = [translate_id(_id) for _id in options.ids]
    if any(id is None for id in item_ids):
        return
    client = get_ops_client()
    if do_files:
        for file_id in item_ids:
            file = client.file(file_id)
            box_filename = file.get(fields=['name']).name
            print(f"Deleting file {box_filename}...")
            file.delete()
    elif do_folders:
        for folder_id in item_ids:
            folder = client.folder(folder_id)
            box_foldername = folder.get(fields=['name']).name
            print(f"Deleting folder {box_foldername}...")
            folder.delete()

def itempaths(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s path [options] ids...',
                                         description='Get full path of files or folders')
    cli_parser.add_argument('ids', nargs='+', help='File or folder IDs')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Get file paths')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Get folder paths')
    cli_parser.add_argument('-R', '--rclone', action='store_true', help='Format paths for use with rclone')
    cli_parser.add_argument('-v', '--verbose', action='store_true', help="Verbose output format")
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    rclone = options.rclone
    verbose = options.verbose
    item_ids = [translate_id(_id) for _id in options.ids]
    if any(id is None for id in item_ids):
        return
    client = get_ops_client()
    for i, id in enumerate(item_ids):
        item = client.file(id).get() if do_files else client.folder(id).get()
        if id == '0':
            print('box:/') if rclone else print('/')
        else:
            if verbose:
                if i != 0: print()
                path_items = item.path_collection['entries'][1:]
                path_items.append(item)
                for j, path_item in enumerate(path_items):
                    print(" " * (j*2) + '/ ', end="")
                    print(f"{path_item.name} [{path_item.id}]")
            else:
                path_entries = [folder.name for folder in item.path_collection['entries'][1:]]
                path_entries.append(item.name)
                path = "/" + "/".join(path_entries)
                if rclone:
                    print('box:', end="")
                print(path)

def mkdir(args):  # {{{2
    if len(args) < 2 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} mkdir parent_folder_id folder_name\n\n"
               "Create a new folder")
        return
    parent_folder_id = translate_id(args[0])
    foldername = args[1]
    client = get_ops_client()
    folder = client.folder(folder_id=parent_folder_id).get()
    print(f'Creating "{foldername}" in "{folder.name}"...')
    folder.create_subfolder(foldername)

def mv_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s mv [options] ids... dest_folder_id',
                                         description='Move files or folders')
    cli_parser.add_argument('ids', nargs='+', help='File or folder IDs to move')
    cli_parser.add_argument('dest_folder_id', help='Destination folder ID')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Item IDs are files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Item IDs are folders')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    item_ids = [translate_id(_id) for _id in options.ids]
    dest_folder_id = translate_id(options.dest_folder_id)
    if dest_folder_id is None or any(id is None for id in item_ids):
        return
    client = get_ops_client()
    folder = client.folder(folder_id=dest_folder_id)
    for item_id in item_ids:
        item = client.file(item_id) if do_files else client.folder(item_id)
        moved_item = item.move(parent_folder=folder)
        print(f'Moved "{moved_item.name}" into "{moved_item.parent.name}"')

def cp_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s cp [options] ids... dest_folder_id',
                                         description='Copy files or folders')
    cli_parser.add_argument('ids', nargs='+', help='File or folder IDs to copy')
    cli_parser.add_argument('dest_folder_id', help='Destination folder ID')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Item IDs are files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Item IDs are folders')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    item_ids = [translate_id(_id) for _id in options.ids]
    dest_folder_id = translate_id(options.dest_folder_id)
    if dest_folder_id is None or any(id is None for id in item_ids):
        return
    client = get_ops_client()
    folder = client.folder(folder_id=dest_folder_id)
    for item_id in item_ids:
        item = client.file(item_id) if do_files else client.folder(item_id)
        copied_item = item.copy(parent_folder=folder)
        print(f'Copied "{copied_item.name}" into "{copied_item.parent.name}"')

def rn_item(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s rn [options] id new_name',
                                         description='Rename a file or folder')
    cli_parser.add_argument('id', help='File or folder ID')
    cli_parser.add_argument('new_name', help='New name for the item')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Item IDs are files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Item IDs are folders')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    item_id = translate_id(options.id)
    new_name = options.new_name
    if item_id is None:
        return
    client = get_ops_client()
    item = client.file(item_id) if do_files else client.folder(item_id)
    oldname = item.get().name
    item = item.rename(new_name)
    print(f'"{oldname}" renamed to "{item.name}"')

def ln_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s ln [options] ids...',
                                         description='Get links for files or folders')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Item IDs are files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Item IDs are folders')
    cli_parser.add_argument('-p', '--password', help='Set a password to access items')
    cli_parser.add_argument('-r', '--remove', action='store_true', help='Remove shared link from items')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    password = options.password
    remove = options.remove
    item_ids = [translate_id(_id) for _id in options.ids]
    if any(id is None for id in item_ids):
        return
    client = get_ops_client()
    if do_files:
        for i, id in enumerate(item_ids):
            file = client.file(id)
            if remove:
                file.remove_shared_link()
                file = file.get()
                print(f'Removed shared link for file "{file.name}"')
            else:
                link = file.get_shared_link(allow_download=True, allow_preview=True, password=password)
                file = file.get()
                direct_link = file.shared_link['download_url']
                if i != 0: print()
                print("== File:", file.name)
                print("   Link:", link)
                print(" Direct:", direct_link)
    elif do_folders:
        for i, id in enumerate(item_ids):
            folder = client.folder(id)
            if remove:
                folder.remove_shared_link()
                folder = folder.get()
                print(f'Removed shared link for folder "{folder.name}"')
            else:
                link = folder.get_shared_link(allow_download=True, allow_preview=True, password=password)
                folder = folder.get()
                if i != 0: print()
                print("== Folder:", folder.name)
                print("     Link:", link)

def stat_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(usage='%(prog)s stat [options] ids...',
                                         description='Get info about files or folders')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Item IDs are files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Item IDs are folders')
    options = cli_parser.parse_args(args)
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    item_ids = [translate_id(_id) for _id in options.ids]
    if any(id is None for id in item_ids):
        return
    client = get_ops_client()
    for i, item_id in enumerate(item_ids):
        item = client.file(item_id) if do_files else client.folder(item_id)
        item = item.get()
        if i != 0: print()
        for field in ('name', 'type', 'id', 'content_created_at', 'content_modified_at',
                      'created_at', 'description', 'modified_at', 'size'):
            print(f"{field:20}: {getattr(item, field)}")
        if item.shared_link:
            print(f"{'url':20}: {item.shared_link['url']}")
            print(f"{'download_url':20}: {item.shared_link['download_url']}")
        if hasattr(item, "item_collection"):
            print(f"{'item_count':20}: {item.item_collection['total_count']}")

# Map command names to the implementing command function  # {{{2
command_funcs = {
    'auth'     : auth_cmd,
    'refresh'  : refresh_cmd,
    'userinfo' : userinfo_cmd,
    'list'     : ls_folder, 'ls' : ls_folder,
    'search'   : search,
    'get'      : get_files,
    'put'      : put_file,
    'rm'       : rm_items, 'del' : rm_items,
    'path'     : itempaths,
    'mkdir'    : mkdir,
    'mv'       : mv_items, 'move' : mv_items,
    'cp'       : cp_items, 'copy' : cp_items,
    'rn'       : rn_item, 'rename' : rn_item,
    'ln'       : ln_items, 'link' : ln_items,
    'stat'     : stat_items
}
# End command functions }}}1

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
