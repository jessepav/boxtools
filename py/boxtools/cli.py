import os, os.path, sys, argparse, pprint, re, shutil, logging, readline
from collections import OrderedDict
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
app_state_file = os.path.join(config_dir, "app-state.pickle")
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
    config_table = config.get('config', {})
    id_history_size = config_table.get('id-history-size', 500)
    chunked_upload_size_threshold = config_table.get('chunked-upload-size-threshold', 20_971_520)
    chunked_upload_num_threads = config_table.get('chunked-upload-num-threads', 2)
    rclone_remote_name = config_table.get('rclone-remote-name', 'box')

if os.path.exists(app_state_file):
    with open(app_state_file, 'rb') as f:
        _app_state = pickle.load(f)
        item_history_map = _app_state['item_history_map']
        last_id = _app_state['last_id']
        del _app_state
else:
    item_history_map = OrderedDict()
    last_id = None

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

# }}}1

# Support functions {{{1

def save_tokens(access_token, refresh_token):  # {{{2
    with open(tokens_file, 'wt') as f:
        json.dump({ 'access_token' : access_token, 'refresh_token' : refresh_token }, f,
                  indent=2)
        f.write('\n')  # We want the file to end in a newline, like a usual text file

def load_tokens_or_die():  # {{{2
    if not os.path.exists(tokens_file):
        print("You must first retrieve auth tokens by using the 'auth' command")
        sys.exit(1)
    with open(tokens_file, 'rt') as f:
        tokendict = json.load(f)
    return tokendict['access_token'], tokendict['refresh_token']

def get_ops_client():  # {{{2
    # Retrieves and caches a Box Client object
    global ops_client, BoxAPIException
    if ops_client is None:
        access_token, refresh_token = load_tokens_or_die()
        from .auth import get_client
        ops_client = get_client(client_id, client_secret, access_token, refresh_token, save_tokens)
        # Prevent the Box SDK from spewing logging messages
        logging.getLogger('boxsdk').setLevel(logging.CRITICAL)
        import boxsdk.config
        boxsdk.config.API.CHUNK_UPLOAD_THREADS = chunked_upload_num_threads
        from boxsdk.exception import BoxAPIException
    return ops_client

ops_client = None

def print_table(items, fields, colgap=2,                                 # {{{2
                *,print_header=True, is_dict=False, is_sequence=False):
    numcols = len(fields)
    # Helper function so we can work with all sorts of items
    def _get_field_val(item, idx, field):
        if is_dict:
            v = item[field]
        elif is_sequence:
            v = item[idx]
        else:
            v = getattr(item, field)
        return "(N/A)" if v is None else v
    #
    def _print_column_val(val, colidx, leader=" "):
        print(val, end="")
        if colidx == numcols - 1:
            print()
        else:
            r = max_field_len[colidx] - len(val)
            if r > 3:  # We do r > 3 because we want at least two leader characters
                print("  " + leader*(r-2), end="")
            else:
                print(" " * r, end="")
            print(" " * colgap, end="")
    #
    max_field_len = [len(field) for field in fields]
    for item in items:
        for i, field in enumerate(fields):
            max_field_len[i] = max(max_field_len[i], len(_get_field_val(item, i, field)))
    total_width = sum(max_field_len) + colgap*(numcols-1)
    if print_header:
        for i, field in enumerate(fields):
            _print_column_val(field.capitalize(), i)
        print("-" * total_width)
    for item in items:
        for i, field in enumerate(fields):
            _print_column_val(_get_field_val(item, i, field), i, leader='·')
    return total_width

def print_stat_info(item):  # {{{2
    add_history_item(item)
    for field in ('name', 'type', 'id', 'content_created_at', 'content_modified_at',
                    'created_at', 'description', 'modified_at', 'size'):
        print(f"{field:20}: {getattr(item, field)}")
    if item.shared_link:
        print(f"{'url':20}: {item.shared_link['url']}")
        print(f"{'download_url':20}: {item.shared_link['download_url']}")
    if hasattr(item, "item_collection"):
        print(f"{'item_count':20}: {item.item_collection['total_count']}")
    if item.parent:
        add_history_item(item.parent)
        print(f"{'parent_name':20}: {item.parent.name}")
        print(f"{'parent_id':20}: {item.parent.id}")

def translate_id(id_):  # {{{2
    global last_id
    if id_ == '=':
        retid = last_id
    elif id_ in id_aliases:
        retid = str(id_aliases[id_])
    elif id_.startswith('%'):
        term = id_[1:]
        retid = _choose_history_entry(id_, lambda entry : term in entry['name'])
    elif id_.startswith('='):
        term = id_[1:]
        retid = _choose_history_entry(id_, lambda entry : term == entry['name'])
    elif id_.startswith('^'):
        term = id_[1:]
        retid = _choose_history_entry(id_, lambda entry : entry['name'].startswith(term))
    elif id_.endswith('$'):
        term = id_[0:-1]
        retid = _choose_history_entry(id_,
                    lambda entry : any(entry[k].endswith(term) for k in ('name', 'id')))
    elif len(id_) >= 3 and id_[0] == '/' and id_[-1] == '/':  # a regex
        matched_ids = []
        regexp = re.compile(id_[1:-1], re.IGNORECASE)
        retid = _choose_history_entry(id_,
                    lambda entry : any(regexp.search(entry[k]) for k in ('name', 'id')))
    elif (slash_count := id_.count('/')) == 2 and len(id_) >= 4 and id_[0] == '/':  # /p/s
        p, s = id_[1:].split('/')
        retid = _choose_history_entry(id_,
                    lambda entry : s in entry['name'] and p in entry['parent_name'])
    elif len(id_) >= 3 and slash_count == 1:
        s, n = id_.split('/')
        retid = _choose_history_entry(id_,
                    lambda entry : s in entry['name'] and entry['id'].endswith(n))
    elif id_.isdigit():
        retid = id_
    else:
        term = id_.casefold()
        retid = _choose_history_entry(id_, lambda entry : term == entry['name'].casefold())
    if retid:
        last_id = retid
    return retid

def _choose_history_entry(id_, entry_filter_func):
    matched_ids = list(filter(entry_filter_func, item_history_map.values()))
    numchoices = len(matched_ids)
    if numchoices == 0:
        print(f'"{id_}" did not match any previous IDs')
        return None
    elif numchoices > 1:
        print(f'"{id_}" matched multiple previous IDs (listed from old to new):\n')
        choices = []
        for i, entry in enumerate(matched_ids, start=1):
            choices.append({'n'      : str(i),
                            'id'     : entry['id'],
                            'name'   : entry['name'] + ('/' if entry['type'] == 'folder' else ''),
                            'parent_name' : entry['parent_name']})
        print_table(choices, ('n', 'name', 'id', 'parent_name'), is_dict=True)
        print()
        try:
            choice = int(input(f'choice # (1-{numchoices})> ')) - 1
            if choice >= 0 and choice < numchoices:
                return matched_ids[choice]['id']
            else:
                return None
        except EOFError:
            print()
        except ValueError:
            return None
    else:
        return matched_ids[0]['id']

def add_history_item(item, parent=None):  # {{{2
    p = parent or getattr(item, 'parent', None)
    entry = {'id': item.id, 'name': item.name, 'type': item.type,
             'parent_id' : p.id if p else None,
             'parent_name' : p.name if p else None }
    if item.id in item_history_map:
        item_history_map.move_to_end(item.id)
    item_history_map[item.id] = entry
    if (n := len(item_history_map) - id_history_size) > 0:
        for i in range(n):
            item_history_map.popitem(last=False)

# def retrieve_folder_items(...) and co {{{2

BOX_GET_ITEMS_LIMIT = 1000

# Retrieves `limit` items from `folder` starting at `start_offset`. If limit is None,
# retrieves all items from the folder. Items are returned as a list. This function
# paginates requests as necessary to accommodate Box's max per-request limit.
def retrieve_folder_items(client, folder, fields=['type', 'name', 'id', 'parent'],
                          limit=None, start_offset=0, sort=None, pagesize_limit=BOX_GET_ITEMS_LIMIT,
                          filter_func=None, break_on_filter=False):
    if not getattr(folder, 'item_collection', None):
        folder = folder.get()
    total_items = folder.item_collection['total_count']
    num_items = total_items if limit is None else min(limit, total_items - start_offset)
    offset = start_offset
    items = []
    try:
        while num_items > 0:
            pagesize = min(num_items, pagesize_limit)
            item_iter = folder.get_items(fields=fields, limit=pagesize, offset=offset, sort=sort)
            for i in range(pagesize):
                item = next(item_iter, None)
                if not item:
                    raise IndexError('Premature end to folder item_collection')
                if filter_func and not filter_func(item):
                    if break_on_filter:
                        raise StopIteration()
                else:
                    items.append(item)
            num_items -= pagesize
            offset += pagesize
    except IndexError as ex:
        print('retrieve_folder_items():', ex, file=sys.stderr)
    except StopIteration:
        pass
    return items

# }}}1

# Define command functions {{{1

def auth_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s auth [options]',
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

def history(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s history [options]',
                                         description='Show previous ID history')
    cli_parser.add_argument('-l', '--limit', type=int, default=0,
                            help='Maximum number of (most-recent) items to return')
    options = cli_parser.parse_args(args)
    limit = options.limit
    print_table(list(item_history_map.values())[-limit:], ('name', 'id', 'parent_name'), is_dict=True)

def ls_folder(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s ls [options] id [id...]',
                                         description='List a folder')
    cli_parser.add_argument('id', nargs='+', help='Folder ID(s)')
    cli_parser.add_argument('-H', '--no-header', action='store_true',
                            help='Do not print header text for the listing')
    cli_parser.add_argument('-l', '--limit', type=int, default=None,
                            help='Maximum number of items to return')
    cli_parser.add_argument('-o', '--offset', type=int, default=0,
                            help='The number of results to skip before displaying results')
    cli_parser.add_argument('-F', '--only-files', action='store_true', help='Only list files')
    cli_parser.add_argument('-D', '--only-folders', action='store_true', help='Only list folders')
    options = cli_parser.parse_args(args)
    folder_ids = [translate_id(_id) for _id in options.id]
    if any(id is None for id in folder_ids):  # translate_id() failed
        return
    print_header = not options.no_header
    limit = options.limit
    offset = options.offset
    if options.only_files and options.only_folders:
        print("-F/--only-files and -D/--only-folders are mutually exclusive")
        return
    elif options.only_files:
        filter_func = lambda item: item.type == 'file'
    elif options.only_folders:
        filter_func = lambda item: item.type == 'folder'
    else:
        filter_func = None
    client = get_ops_client()
    for i, folder_id in enumerate(folder_ids):
        folder = client.folder(folder_id=folder_id).get()
        items = retrieve_folder_items(client, folder, limit=limit, start_offset=offset,
                                      filter_func=filter_func)
        add_history_item(folder)
        if _parent := folder.parent:
            _parent = _parent.get(fields=['id', 'name', 'type', 'parent'])
            add_history_item(_parent)
        for item in items:
            add_history_item(item, parent=folder)
        if i != 0:
            print()
        if print_header:
            folder_header_info = f"==== {folder.name} ({folder.id}) ===="
            if _parent:
                folder_header_info += f"\n  ==== Parent: {_parent.name} ({_parent.id}) =="
            elif folder_id != '0':
                folder_header_info += "\n  ==== Parent: All Files (0) =="
            print(folder_header_info, end="\n\n")
        print_table(items, ('type', 'name', 'id'), print_header=print_header)

def search(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s fd [options] term',
                                         description='Search for items')
    cli_parser.add_argument('term', help='Search term')
    cli_parser.add_argument('-f', '--files', action='store_true', help='Search for files')
    cli_parser.add_argument('-d', '--folders', action='store_true', help='Search for folders')
    cli_parser.add_argument('-l', '--limit', type=int, default=10,
                            help='Maximum number of items to return')
    cli_parser.add_argument('-o', '--offset', type=int, default=0,
                            help='The number of results to skip before displaying results')
    cli_parser.add_argument('-n', '--name-only', action='store_true',
                            help='Search only in item names rather than in all content')
    cli_parser.add_argument('-P', '--no-parent', action='store_true',
                            help="Don't include parent folder information in output")
    cli_parser.add_argument('-a', '--ancestors',
                            help="Comma-separated list of ancestor folders for results")
    cli_parser.add_argument('-e', '--extensions',
                            help="Comma-separated list of extensions considered in search")
    options = cli_parser.parse_args(args)
    term = options.term
    do_files, do_folders = options.files, options.folders
    if do_files == do_folders:
        print("You must supply exactly one of --files/-f or --folders/-d")
        return
    limit = options.limit
    offset = options.offset
    name_only = options.name_only
    no_parent = options.no_parent
    if options.ancestors:
        ancestor_ids = [translate_id(id.strip()) for id in options.ancestors.split(",")]
        if any(id is None for id in ancestor_ids):
            return
    else:
        ancestor_ids = None
    extensions = [ext.strip(" .") for ext in options.extensions.split(",")] \
                    if options.extensions else None
    fields=['name', 'id', 'parent']
    client = get_ops_client()
    ancestors = [client.folder(id) for id in ancestor_ids] if ancestor_ids else None
    results = client.search().query(query=term, limit=limit, offset=offset,
                                    ancestor_folders=ancestors, file_extensions=extensions,
                                    result_type='file' if do_files else 'folder',
                                    content_types=['name'] if name_only else None, fields=fields)
    # We can't just throw the iterator returned by query() into a list(), because it stalls,
    # so we need to manually retrieve 'limit' items
    items = []
    for i, r in enumerate(results, start=1):
        item = { 'name' : r.name,
                 'id'   : r.id }
        add_history_item(r)
        if _p := r.parent:
            item['parent'], item['parent_id']  = _p.name, _p.id
            add_history_item(_p)
        else:
            item['parent'] = item['parent_id'] = None
        items.append(item)
        if i == limit: break
    print_table(items,
                ('name', 'id', 'parent', 'parent_id') if not no_parent else ('name', 'id'),
                is_dict=True)

def tree(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s tree [options] folder_id',
                                         description='Display a tree of folders')
    cli_parser.add_argument('folder_id', help='Folder ID')
    cli_parser.add_argument('-L', '--max-levels', type=int, default=999,
                            help='Maximum number of levels to recurse (>= 1)')
    cli_parser.add_argument('-i', '--re-filter', metavar='RE',
                help='Only display and recurse into sub-folders whose names fully match RE')
    options = cli_parser.parse_args(args)
    folder_id = translate_id(options.folder_id)
    if not folder_id:
        return
    max_levels = options.max_levels
    if max_levels <= 0:
        print('--max-levels must be >= 1')
        return
    re_pattern = options.re_filter and re.compile(options.re_filter)
    indent_str = " " * 2
    client = get_ops_client()
    tree_entries = []
    ####
    def _tree_helper(folder, level):
        add_history_item(folder)
        name_part, id_part = None, folder.id
        if level == 0:
            name_part = f"{folder.fullpath}"
        else:
            marker = _tree_item_markers[level % len(_tree_item_markers)]
            name_part = (indent_str * level) + f"{marker} {folder.name}"
        tree_entries.append((name_part, id_part))
        if sys.stdout.isatty():  # Display a progress report
            sys.stdout.write('\033[2K\033[1G') # erase and go to beginning of line
            print('*', folder.name, end="", flush=True)
        if level < max_levels:
            # Since folders are always returned before other item types, we can break_on_filter;
            # also, we specify a small pagesize_limit so that we don't retrieve the whole
            # BOX_GET_ITEMS_LIMIT page from a folder, most of which will be files.
            folder_items = retrieve_folder_items(client, folder, sort='name', pagesize_limit=30,
                                filter_func=lambda it: it.type == 'folder', break_on_filter=True)
            for f in folder_items:
                if not re_pattern or re_pattern.fullmatch(f.name):
                    _tree_helper(f, level + 1)
        if level == 0 and sys.stdout.isatty():
            sys.stdout.write('\033[2K\033[1G')

    ####
    initial_folder = client.folder(folder_id).get()
    path_entries = [folder.name for folder in initial_folder.path_collection['entries'][1:]]
    path_entries.append(initial_folder.name)
    initial_folder.fullpath = "/" + "/".join(path_entries)
    _tree_helper(initial_folder, 0)
    print_table(tree_entries, ('name_part', 'id_part'), print_header=False, is_sequence=True)

_tree_item_markers = ['*', '-']

def get_files(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s get [options] ids... directory',
                                         description='Download files or thumbnails')
    cli_parser.add_argument('ids', nargs='+', help='File or Folder IDs')
    cli_parser.add_argument('directory', help='Destination directory')
    cli_parser.add_argument('-t', '--thumbnails', action='store_true',
                            help="Download thumbnail images rather than the files themselves")
    cli_parser.add_argument('-s', '--thumbnail-size', metavar='N', type=int,
                            help="Retrieve a thumbnail with dimensions NxN. For .png thumbnails, "
                                 "valid sizes are 1024 and 2048. For .jpg thumbnails, valid sizes "
                                 "are 32, 94, 160, 320, 1024, and 2048. Attempting to use "
                                 "an invalid size will result in an empty thumbnail file.")
    # https://developer.box.com/guides/representations/thumbnail-representation/#supported-file-sizes
    cli_parser.add_argument('-e', '--thumbnail-ext', metavar='EXT', default="jpg",
                            help="Set the format for thumbnails (either 'png' or 'jpg'). "
                                 "(Note that it seems png thumbnails don't work.)")
    cli_parser.add_argument('-d', '--folders', action='store_true',
                            help="Item IDs specify folders from which to download files")
    cli_parser.add_argument('-i', '--re-filter', metavar='RE',
                            help="Applies when -d/--folders is used: rather than downloading all files "
                                 "from the specified folders, only download those files whose names "
                                 "fully match the regular expression RE")
    options = cli_parser.parse_args(args)
    item_ids = [translate_id(id) for id in options.ids]
    if any(id is None for id in item_ids):
        return
    target_dir = os.path.expanduser(options.directory)
    if not os.path.isdir(target_dir):
        print(f"{target_dir} is not a directory!")
        return
    do_thumbnails = options.thumbnails
    thumbnail_size = options.thumbnail_size
    thumbnail_ext = options.thumbnail_ext.lstrip(".").lower()
    if thumbnail_ext not in ('jpg', 'png'):
        print(f"Invalid extensions: {thumbnail_ext}")
        return
    if not thumbnail_size:
        thumbnail_size = 1024 if thumbnail_ext == 'png' else 320
    do_folders = options.folders
    re_pattern = options.re_filter and re.compile(options.re_filter)
    client = get_ops_client()
    for item_id in item_ids:
        if do_folders:
            folder = client.folder(folder_id=item_id).get()
            print(f'== Retrieving files from "{folder.name}" ==')
            def _filter_func(item):
                if item.type != 'file':
                    return False
                elif re_pattern and not re_pattern.fullmatch(item.name):
                    return False
                else:
                    return True
            file_ids = [item.id for item in retrieve_folder_items(
                            client, folder, fields=['type', 'name', 'id'], filter_func=_filter_func)]
        else:
            file_ids = [item_id]
        for file_id in file_ids:
            file = client.file(file_id)
            filename = file.get(fields=['name']).name
            if do_thumbnails:
                root, ext = os.path.splitext(filename)
                filename = f"{root}-{thumbnail_size}x{thumbnail_size}.{thumbnail_ext}"
                print(f'Downloading "{filename}"...')
                imgbytes = file.get_thumbnail_representation(
                        dimensions=f"{thumbnail_size}x{thumbnail_size}",
                        extension=thumbnail_ext)
                with open(os.path.join(target_dir, filename), "wb") as f:
                    f.write(imgbytes)
            else:
                print(f"Downloading {filename}...")
                with open(os.path.join(target_dir, filename), "wb") as f:
                    file.download_to(f)

def put_file(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s put [options] file(s)',
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
    file_id = file_id and translate_id(file_id)
    folder_id = folder_id and translate_id(folder_id)
    if not any((file_id, folder_id)):
        return
    client = get_ops_client()
    if file_id:
        file = client.file(file_id)
        box_filename = file.get(fields=['name']).name
        filepath = files[0]
        use_chunked = os.path.getsize(filepath) > chunked_upload_size_threshold
        chunked_msg = " (chunked)" if use_chunked else ""
        print(f'Uploading{chunked_msg} "{filepath}" as a new version of "{box_filename}"...', end="", flush=True)
        if use_chunked:
            file.get_chunked_uploader(filepath).start()
        else:
            file.update_contents(filepath)
        print("done")
    elif folder_id:
        folder = client.folder(folder_id)
        foldername = folder.get(fields=['name']).name
        for filepath in files:
            use_chunked = os.path.getsize(filepath) > chunked_upload_size_threshold
            chunked_msg = " (chunked)" if use_chunked else ""
            print(f'Uploading{chunked_msg} "{filepath}" to "{foldername}"...', end="", flush=True)
            try:
                if use_chunked:
                    folder.get_chunked_uploader(filepath).start()
                else:
                    folder.upload(filepath)
                print("done")
            except BoxAPIException as ex:
                if ex.status == 409:
                    _file_id = ex.context_info['conflicts']['id']
                    print('(new version)...', end="", flush=True)
                    file = client.file(_file_id)
                    if use_chunked:
                        file.get_chunked_uploader(filepath).start()
                    else:
                        file.update_contents(filepath)
                    print("done")
                else:
                    raise ex

def rm_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s rm [options] ids...',
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
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s path [options] ids...',
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
            print('{rclone_remote_name}:/') if rclone else print('/')
        else:
            if verbose:
                if i != 0: print()
                path_items = item.path_collection['entries'][1:]
                path_items.append(item)
                for j, path_item in enumerate(path_items):
                    print(" " * (j*2) + '/ ', end="")
                    print(f"{path_item.name} [{path_item.id}]")
                    add_history_item(path_item)
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
    folder = client.folder(folder_id=parent_folder_id).get(fields=['id', 'name', 'type', 'parent'])
    print(f'Creating "{foldername}" in "{folder.name}"...')
    folder.create_subfolder(foldername)

def mv_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s mv [options] ids... dest_folder_id',
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
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s cp [options] ids... dest_folder_id',
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
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s rn [options] id new_name',
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
    oldname = item.get(fields=['id', 'name', 'type', 'parent']).name
    item = item.rename(new_name)
    print(f'"{oldname}" renamed to "{item.name}"')

def ln_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s ln [options] ids...',
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
                file = file.get(fields=['id', 'name', 'type', 'parent'])
                print(f'Removed shared link for file "{file.name}"')
            else:
                link = file.get_shared_link(allow_download=True, allow_preview=True, password=password)
                file = file.get(fields=['id', 'name', 'type', 'parent'])
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
                folder = folder.get(fields=['id', 'name', 'type', 'parent'])
                print(f'Removed shared link for folder "{folder.name}"')
            else:
                link = folder.get_shared_link(allow_download=True, allow_preview=True, password=password)
                folder = folder.get(fields=['id', 'name', 'type', 'parent'])
                if i != 0: print()
                print("== Folder:", folder.name)
                print("     Link:", link)

def readlink(args):  # {{{2
    if len(args) != 1 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} readlink shared_url\n\n"
               "Get info about the item referred to by a shared link.\n\n"
               'Note that this only works for "Shared URLs", not "Download URLs"')
        return
    shared_url = args[0]
    client = get_ops_client()
    item = client.get_shared_item(shared_url)
    print_stat_info(item)

def stat_items(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         usage='%(prog)s stat [options] ids...',
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
        print_stat_info(item)

def shell(args):  # {{{2
    import shlex
    print("Type 'quit' to exit the shell, 'help' for general usage.")
    while True:
        try:
            cmdline = input("> ")
        except EOFError:
            print()
            break
        if cmdline == 'quit':
            break
        elif cmdline == 'help':
            print(general_usage, end="")
        elif len(cmdline) == 0 or cmdline.isspace():
            continue
        else:
            cmd, *args = shlex.split(cmdline)
            if cmd in command_funcs:
                try:
                    command_funcs[cmd](args)
                except (SystemExit, argparse.ArgumentError):
                    # We catch these so that the shell doesn't exit when argparse.parse_args()
                    # gets a '--help' or incorrect arguments.
                    pass
            else:
                print(f"Unknown command '{cmd}'")

# Map command names to the implementing command function  # {{{2
command_funcs = {
    'auth'     : auth_cmd,
    'refresh'  : refresh_cmd,
    'userinfo' : userinfo_cmd,
    'history'  : history,
    'ls'       : ls_folder, 'list' : ls_folder,
    'fd'       : search, 'search' : search,
    'tree'     : tree,
    'get'      : get_files,
    'put'      : put_file,
    'rm'       : rm_items, 'del' : rm_items,
    'path'     : itempaths,
    'mkdir'    : mkdir,
    'mv'       : mv_items, 'move' : mv_items,
    'cp'       : cp_items, 'copy' : cp_items,
    'rn'       : rn_item, 'rename' : rn_item,
    'ln'       : ln_items, 'link' : ln_items,
    'readlink' : readlink,
    'stat'     : stat_items,
    'shell'    : shell,
}
# End command functions }}}1

# Run the appropriate command function {{{1

command = sys.argv[1]
command_args = sys.argv[2:]

if command not in command_funcs:
    print(f"Unknown command '{command}'")
else:
    try:
        command_funcs[command](command_args)
    except argparse.ArgumentError:
        pass
    finally:
        with open(app_state_file, "wb") as f:
            pickle.dump(file=f,
                        obj={ 'item_history_map' : item_history_map,
                              'last_id' : last_id })

# }}}1
