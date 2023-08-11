import os, os.path, sys, argparse, re, io, ast, time
import shutil, shlex, subprocess, logging, readline, pprint
from collections import OrderedDict, deque
import json, pickle

import tomli

# Preliminaries {{{1

# The invoking shell script must set $BOXTOOLS_APP_DIR {{{2
app_dir = os.environ.get("BOXTOOLS_APP_DIR")
if not app_dir:
    print("You must set $BOXTOOLS_APP_DIR before running this program!")
    sys.exit(1)

progname = os.environ.get("BOXTOOLS_PROGNAME", os.path.basename(sys.argv[0]))


# The user can override the default ~/.boxtools directory by setting $BOXTOOLS_DIR {{{2
config_dir = os.environ.get("BOXTOOLS_DIR", os.path.expanduser("~/.boxtools"))

# Load the resources kept in separate files for easy editing {{{2
with open(os.path.join(app_dir, 'resources/usage.txt'), "rt") as f:
    general_usage = f.read(). \
        format(progname=progname, app_dir=app_dir, config_dir=config_dir)

if not os.path.exists(config_dir):
    print(f"Creating {config_dir}...")
    os.mkdir(config_dir)

# Derive paths for configuration files {{{2
config_file = os.path.join(config_dir, "boxtools.toml")
tokens_file = os.path.join(config_dir,
        f"auth-{_authname}-tokens.json" if (_authname := os.environ.get("BOXTOOLS_AUTH_NAME"))
                                        else "auth-tokens.json")
app_state_file = os.path.join(config_dir, "app-state.pickle")
aliases_file = os.path.join(config_dir, "id-aliases.txt")
readline_history_file = os.path.join(config_dir, "readline-history")

# Print help and exit if appropriate {{{2
if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
    print(general_usage, end="")
    sys.exit(1)

# If no config file exists, write the default and exit {{{2
if not os.path.exists(config_file):
    print(f"Edit the default config file at '{config_file}'")
    shutil.copyfile(os.path.join(app_dir, 'resources/boxtools.toml'), config_file)
    sys.exit(1)

# Read the config file {{{2
with open(config_file, 'rb') as f:
    config = tomli.load(f)
auth_table = config['auth']
client_id = auth_table['client-id']
client_secret = auth_table['client-secret']
redirect_urls = {'internal' : auth_table['internal-redirect-url'],
                 'external' : auth_table['external-redirect-url']}
config_table = config.get('config', {})
id_history_size = config_table.get('id-history-size', 500)
readline_history_size = config_table.get('readline-history-size', 500)
ls_history_size = config_table.get('ls-history-size', 10)
chunked_upload_size_threshold = config_table.get('chunked-upload-size-threshold', 20_971_520)
chunked_upload_num_threads = config_table.get('chunked-upload-num-threads', 2)
rclone_remote_name = config_table.get('rclone-remote-name', 'box')
representation_max_attempts = config_table.get('representation-max-attempts', 15)
representation_wait_time = config_table.get('representation-wait-time', 2.0)
representation_aliases = dict(config_table.get('representation-aliases', []))

# Get terminal size for use in default lengths {{{2
screen_cols = shutil.get_terminal_size(fallback=(0, 0))[0] if sys.stdout.isatty() else 80

# Default and minimum name and id lengths for commands that allow clipping field values {{{2
MIN_NAME_LEN = 8
MIN_ID_LEN   = 5

def _decode_length_val(val):
    _type = type(val)
    if _type is int:
        return val
    elif _type is str:
        return int(eval(val, {'cols' : screen_cols}))
    else:
        return 0

default_max_name_length = _decode_length_val(config_table.get('default-max-name-length', 0))
default_max_id_length   = _decode_length_val(config_table.get('default-max-id-length',   0))

del _decode_length_val

# Restore app state and readline history if available {{{2

ls_history_deque = deque(maxlen = ls_history_size)

if os.path.exists(app_state_file):
    with open(app_state_file, 'rb') as f:
        _app_state = pickle.load(f)
    item_history_map = _app_state['item_history_map']
    last_id = _app_state['last_id']
    _lshist = _app_state.get('ls_history', [])
    if _lshist and len(_lshist[0]) == 4:  # Don't restore invalid ls history
        ls_history_deque.extend(_lshist[:ls_history_size])
    item_stash = _app_state.get('item_stash', {})
    del _app_state
else:
    item_history_map = OrderedDict()
    last_id = None
    item_stash = {}
current_cmd_last_id = last_id

readline.set_history_length(readline_history_size)
if os.path.exists(readline_history_file):
    readline.read_history_file(readline_history_file)

# Load ID aliases {{{2
ID_ALIAS_RE = re.compile(r'(\S+)\s*=\s*(\d+)\s*(#.*)?')

id_aliases = {}
if os.path.exists(aliases_file):
    with open(aliases_file, 'rt') as f:
        for line in f:
            if mo := ID_ALIAS_RE.fullmatch(line.strip()):
                _alias, _id, _comment = mo.group(1, 2, 3)
                id_aliases[_alias] = (_id, _comment)

# Ensure the set a custom client id and secret in the config file {{{2
if client_id == "(your client-id)" or client_secret == "(your client-secret)":
    print(f"Edit '{config_file}' to supply a valid client ID and secret")
    sys.exit(1)

# }}}1

# Support functions and classes {{{1

# LimitReachedException {{{2

# Used to unwind the call stack when a limit of some kind has been reached
class LimitReachedException(Exception):
    pass

# save_tokens() {{{2

# Write tokens as JSON to our tokens_file

def save_tokens(access_token, refresh_token):
    with open(tokens_file, 'wt') as f:
        json.dump({ 'access_token' : access_token, 'refresh_token' : refresh_token }, f,
                  indent=2)
        f.write('\n')  # We want the file to end in a newline, like a usual text file

# load_tokens_or_die() {{{2

# Load tokens from our tokens_file or exit if attempt fails

def load_tokens_or_die():
    if not os.path.exists(tokens_file):
        print("You must first retrieve auth tokens by using the 'auth' command")
        sys.exit(1)
    with open(tokens_file, 'rt') as f:
        tokendict = json.load(f)
    return tokendict['access_token'], tokendict['refresh_token']

# get_ops_client() {{{2

# Uses our client ID/secret and tokens to get a Box Client object. It caches the client
# object so that the function can be called multiple times without a performance hit.
# It also is the first import of boxsdk and sub-modules, which is done lazily (as opposed
# to at the top of the module) because importing these modules is slow.

ops_client = None

def get_ops_client():
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

# print_table()    {{{2

# Print a pretty table of `fields` in `items`.
#
#   items            : a sequence of objects (i.e. namespaces), dicts, or (sub)sequences
#   fields           : a sequence of field names
#   colgap           : number of spaces between each column
#   print_header     : print the names of the fields above the rows
#   clip_fields      : a map from field name to a tuple of (max_value_len, clip_side). If a
#                      field name appears in clip_fields, we ensure that its printed value
#                      doesn't exceed max_value_len + 3 characters, truncating characters on
#                      clip_side if necessary.  A max_value_len of 0 or None means no limit;
#                      clip_side is either 'l' or 'r'.
#   no_leader_fields : A sequence of field names. These fields will not have leaders appended.
#   is_dict          : True if the elements of `items` are dicts
#   is_sequence      : True if the elements of `items` are sequences
#   field_val_func   : If provided, will be called when retrieving the field value for each item,
#                      so that the value may be transformed, if desired. (See code below for usage)
#   output_file      : the file object where output will be printed; default sys.stdout
#
# If both is_dict and is_sequence are False, `items` will be treated as a namespace,
# and fields will be accessed via getattr()
#
# Returns the total width, in characters, of the table.

def print_table(items, fields, *, colgap=2, print_header=True,
                clip_fields=None, no_leader_fields=(),
                is_dict=False, is_sequence=False,
                field_val_func=None, output_file=sys.stdout):
    numcols = len(fields)
    # Helper function so we can work with all sorts of items
    def _get_field_val(item, idx, field):
        v = item[field] if is_dict else \
            item[idx] if is_sequence else \
            getattr(item, field)
        if field_val_func:
            v = field_val_func(v, item, idx, field)
        if v is None:
            return "(N/A)"
        elif clip_fields and field in clip_fields:
            _maxlen, _clip_dir = clip_fields[field]
            if _maxlen and len(v) > _maxlen:
                return v[:_maxlen] + '[…]' if _clip_dir == 'r' else '[…]' + v[-_maxlen:]
            else:
                return v
        else:
            return v
    #
    def _print_column_val(val, colidx, leader=" "):
        print(val, end="", file=output_file)
        if colidx == numcols - 1:
            print(file=output_file)
        else:
            r = max_field_len[colidx] - len(val)
            if colidx not in no_leader_colidxs and r > 1:
                print(" " + leader*(r-1), end="", file=output_file)
            else:
                print(" " * r, end="", file=output_file)
            print(" " * colgap, end="", file=output_file)
    #
    max_field_len = [len(field) for field in fields]
    no_leader_colidxs = {i for i, field in enumerate(fields) if field in no_leader_fields}
    for item in items:
        for i, field in enumerate(fields):
            max_field_len[i] = max(max_field_len[i], len(_get_field_val(item, i, field)))
    total_width = sum(max_field_len) + colgap*(numcols-1)
    if print_header:
        for i, field in enumerate(fields):
            _print_column_val(field.capitalize(), i)
        print("-" * total_width, file=output_file)
    for item in items:
        for i, field in enumerate(fields):
            _print_column_val(_get_field_val(item, i, field), i,
                              leader=' ' if field in no_leader_fields else '·')
    return total_width

# print_stat_info() {{{2

# Print item info as for the stat command.
#
#  `add_history` determines if the item is added to item history
#  `fields`, if given, should be a sequence of field names that we'll print
#

def print_stat_info(item, add_history=True, fields=None):
    fieldset = None if fields is None else set(fields)
    statlist = []
    #
    def add_field(field, value):
        if fieldset is None or field in fieldset:
            statlist.append((field + ':', value))
    #
    if add_history:
        add_history_item(item)
    for field in ('name', 'type', 'id', 'content_created_at', 'content_modified_at',
                    'created_at', 'modified_at', 'size', 'sha1'):
        add_field(field, str(getattr(item, field, 'N/A')))
    owner = item.owned_by
    add_field('owned_by', f"{owner.name} ({owner.login})")
    if item.shared_link:
        add_field('url', item.shared_link['url'])
        add_field('download_url', item.shared_link['download_url'])
    if hasattr(item, "item_collection"):
        add_field('item_count', str(item.item_collection['total_count']))
    if item.parent:
        if add_history:
            add_history_item(item.parent)
        add_field('parent_name', item.parent.name)
        add_field('parent_id', item.parent.id)
    if desc := item.description:
        desc = desc.replace("\n", "↵")
        if len(desc) > screen_cols//2:
            desc = desc[0:screen_cols//2] + '...'
        add_field('description', desc)
    print_table(statlist, ('field', 'value'), print_header=False, no_leader_fields=('field',), is_sequence=True)

# translate_id() and co. {{{2

# Turn a typed ID, in any of the supported shortcuts documented in usage.txt, into a
# Box ID number, by searching ID aliases, item history, and ls history.

def translate_id(id_):
    global current_cmd_last_id
    #
    if not id_:
        return None
    use_most_recent = False
    if id_[-1] == '!':
        use_most_recent = True
        id_ = id_[:-1]
    #
    if id_ == '@':
        retid = last_id
    elif id_[0] == '@':
        _alias = id_aliases.get(id_[1:])
        retid = _alias[0] if _alias is not None else None
        if retid is None:
            print(f"{id_} is not a known alias")
    elif id_ == '/':
        retid = '0'
    elif id_ in ('.', '..'):
        retid = None
        if len(ls_history_deque):
            _histentry = ls_history_deque[-1]
            if id_ == '.':
                retid = _histentry[1]
            else:
                if (retid := _histentry[3]) is None:
                    print("ls parent directory unavailable")
        else:
            print("ls history is empty!")
    elif id_ in '%=^$/':
        print(f"'{id_}' is composed only of operators!")
        retid = None
    elif id_[0] == '%' or id_[-1] == '%':
        term = id_.strip('%')
        retid = _choose_history_entry(id_, lambda entry : term in entry['name'], use_most_recent)
    elif id_[0] == '=' or id_[-1] == '=':
        term = id_.strip('=')
        retid = _choose_history_entry(id_, lambda entry : term == entry['name'], use_most_recent)
    elif id_[0] == '^' or id_[-1] == '^':
        term = id_.strip('^')
        retid = _choose_history_entry(id_, lambda entry : entry['name'].startswith(term), use_most_recent)
    elif id_[0] == '$' or id_[-1] == '$':
        term = id_.strip('$')
        retid = _choose_history_entry(id_,
                    lambda entry : any(entry[k].endswith(term) for k in ('name', 'id')), use_most_recent)
    elif len(id_) >= 3 and id_[0] == '/' and id_[-1] == '/':  # a regex
        matched_ids = []
        regexp = re.compile(id_[1:-1], re.IGNORECASE)
        retid = _choose_history_entry(id_,
                    lambda entry : any(regexp.search(entry[k]) for k in ('name', 'id')), use_most_recent)
    elif (slash_count := id_.count('/')) == 2 and len(id_) >= 4 and id_[0] == '/':  # /p/s
        p, s = id_[1:].split('/')
        retid = _choose_history_entry(id_,
                    lambda entry : (_parent := entry['parent_name']) and
                                    s in entry['name'] and p in _parent, use_most_recent)
    elif len(id_) >= 3 and slash_count == 1:
        s, n = id_.split('/')
        retid = _choose_history_entry(id_,
                    lambda entry : s in entry['name'] and entry['id'].endswith(n), use_most_recent)
    elif id_.isdigit():
        retid = id_
    else:
        term = id_.casefold()
        retid = _choose_history_entry(id_, lambda entry : term == entry['name'].casefold(), use_most_recent)
    if retid:
        current_cmd_last_id = retid
    return retid

def _choose_history_entry(id_, entry_filter_func, use_most_recent):
    if not id_:
        return None
    matched_ids = list(filter(entry_filter_func, item_history_map.values()))
    numchoices = len(matched_ids)
    if numchoices == 0:
        print(f'"{id_}" did not match any previous IDs')
        return None
    elif numchoices > 1:
        if use_most_recent:
            return matched_ids[-1]['id']
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

# add_history_item() {{{2

# Add a Box item to our item_history_map

def add_history_item(item, parent=None):
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

# determine_item_type() {{{2

# Makes a API requests to determine the type of an item.
#
# Returns a tuple of (type, object), where `type` is 'file', 'folder', or 'web_link',
# and the `object` is a File, Folder, or WebLink object from a boxsdk sub-package
#
# If the item_id is invalid, returns (None, None)

def determine_item_type(client, item_id):
    for _type in ('file', 'folder', 'web_link'):
        try:
            # cstr will be a bound method like client.file(), etc
            cstr = getattr(client, _type)
            # Just calling the constructor function isn't enough: we need the get() to hit the API.
            obj = cstr(item_id).get(fields=['id', 'name'])
            return (_type, obj)
        except BoxAPIException:
            continue
    else:
        print(f"** Item ID {item_id} not found **")
        return (None, None)

# get_api_item() {{{2

# Return a tuple of (type, object) [as documented in determine_item_type()]

def get_api_item(client, item_id):
    # Check first if our history has the item type
    histentry = item_history_map.get(item_id)
    if histentry:
        _type = histentry['type']
        item = getattr(client, _type)(item_id)
        item.id = item_id  # So that all returned items have at least id, name, and type
        item.name = histentry['name']
        item.type = _type
        return (_type, item)
    else:
        return determine_item_type(client, item_id)

# retrieve_folder_items() and co {{{2

BOX_GET_ITEMS_LIMIT = 1000

# Retrieves `limit` items from `folder` starting at `start_offset`. If limit is None,
# retrieves all items from the folder. Items are returned as a list. This function
# paginates requests as necessary to accommodate Box's max per-request limit.

def retrieve_folder_items(client, folder, fields=['type', 'name', 'id', 'parent'],
                          limit=None, start_offset=0, sort=None, direction=None,
                          pagesize_limit=BOX_GET_ITEMS_LIMIT,
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
            item_iter = folder.get_items(fields=fields, limit=pagesize, offset=offset,
                                         sort=sort, direction=direction)
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

# expand_all() {{{2

# Expand both environment variables and the user home dir '~' in path

def expand_all(path):
    return os.path.expandvars(os.path.expanduser(path)) if path else None

# print_name_header() {{{2

# Prints a boxed header spanning the width of the terminal.
#
#   leading_blank - if True, print a blank line before the header
#   context_info  - if not empty, will be printed after the itemname

def print_name_header(itemname, leading_blank=False, context_info=""):
    if leading_blank: print()
    remaining_cols = max(0, screen_cols - len(itemname) - len(context_info) - 6)
    print( " ┌─", '─' * len(itemname), '─┐', sep='')
    print(f"─┤ {itemname} ├─", context_info, '─' * remaining_cols, sep='')
    print( " └─", '─' * len(itemname), '─┘', sep='')

# define_alias() {{{2

# Handles command lines of the form "@alias = ID"

def define_alias(cmdline):
    if len(cmdline) >= 3 and len(cmdline[0]) >= 2 and cmdline[0][0] == '@' and cmdline[1] == '=':
        alias = cmdline[0][1:]
        if (len(cmdline[2]) == 0 or cmdline[2].lower() == 'none'):
            if alias in id_aliases:
                oldid = id_aliases.pop(alias)[0]
                print(f"@{alias} deleted (was {oldid})")
            else:
                print(f'Alias "@{alias}" did not exist')
        else:
            id = translate_id(cmdline[2])
            if id is not None:
                if len(cmdline) >= 4 and cmdline[3][0] == '#':
                    comment = " ".join(cmdline[3:])
                else:
                    hist_entry = item_history_map.get(id)
                    if hist_entry:
                        comment = "# " + hist_entry['name']
                        if hist_entry['type'] == 'folder':
                            comment += '/'
                    else:
                        comment = None
                id_aliases[alias] = (id, comment)
                commentstr = "  " + comment if comment else ""
                print(f"@{alias} = {id}{commentstr}")
    else:
        print("Incorrect alias definition syntax! ( @alias = ID  # comment )")

# list_aliases() {{{2

# Prints all currently defined ID aliases

def list_aliases(filter_term=None):
    items = id_aliases.items()
    if filter_term:
        if filter_term.startswith('^'):
            filter_term = filter_term[1:]
            items = filter(lambda item : item[0].startswith(filter_term), items)
        else:
            items = filter(lambda item : filter_term in item[0], items)
    entries = [(alias, id, comment if comment else "") for (alias, (id, comment)) in items]
    print_table(entries, fields=('alias', 'ID', 'comment'), no_leader_fields=('alias', 'ID'), is_sequence=True)

# process_cmdline() {{{2

# Top-level handler for interpreting command lines.
#
#   cmdline - either a str as entered, or a sequence of tokens as returned,
#             for example, by shlex.split()

def process_cmdline(cmdline):
    global last_id
    #
    if len(cmdline) == 0:
        return
    if type(cmdline) == str:
        try:
            cmdline = shlex.split(cmdline)
        except ValueError as ex:
            print('shlex error:', ex)
            return
    #
    if cmdline == ['@']:
        print(f"Last ID: {last_id}")
    elif cmdline == ['@@']:
        print_item_stash()
    elif len(cmdline) in (1,2) and cmdline[0] == '@list':
        list_aliases(cmdline[1] if len(cmdline) == 2 else None)
    elif cmdline[0].startswith('@'):
        define_alias(cmdline)
    else:
        cmd, *args = cmdline
        if cmd in command_funcs:
            try:
                command_funcs[cmd](args)
            except SystemExit:
                # We catch this so that the program doesn't exit when argparse.parse_args()
                # gets a '--help' or incorrect arguments.
                pass
            except argparse.ArgumentError as e:
                print(e)
            except BoxAPIException as e:
                print("# BoxAPIException #\n")
                print(f"Message: {e.message}",
                      f" Status: {e.status}",
                      sep='\n')
            last_id = current_cmd_last_id
        else:
            print(f"Unknown command '{cmd}'")

# save_state() {{{2

# Writes all persistent program state to their respective files.

def save_state():
    # Save "app state"
    _lshist = list(ls_history_deque)
    with open(app_state_file, "wb") as f:
        pickle.dump(file=f,
                    obj={ 'item_history_map' : item_history_map,
                          'last_id'          : last_id,
                          'ls_history'       : _lshist,
                          'item_stash'       : item_stash })
    # Save readline history
    readline.write_history_file(readline_history_file)
    # Save ID aliases
    with open(aliases_file, "wt") as f:
        for (alias, (id, comment)) in id_aliases.items():
            if len(alias) > 1 and alias[0] != '_' and not alias.isdigit():
                _commentstr = "  " + comment if comment else ""
                print(f"{alias} = {id}{_commentstr}", file=f)

# get_name_len() and get_id_len() {{{2

# Used to determine max name and ID length for commands like ls, search, etc.
# that accept --max-name-length and --max-id-length arguments.

def get_name_len(argval):
    if argval is None:
        return default_max_name_length
    elif argval == 0:
        return 0
    else:
        return max(argval, MIN_NAME_LEN)

def get_id_len(argval):
    if argval is None:
        return default_max_id_length
    elif argval == 0:
        return None
    else:
        return max(argval, MIN_ID_LEN)

# unspace_name() {{{2

# Removes spaces and other troublesome characters from 'name'

def unspace_name(name):
    global _unspace_regexps
    if not _unspace_regexps:
        _unspace_regexps = (re.compile(r'[ ,\(\)\-\[\]]+'),
                            re.compile(r"""['"‘’“”]"""),
                            re.compile(r'-?&-?'))
    newname = name
    newname = _unspace_regexps[0].sub('-', newname)   # replace runs of troublesome characters with a dash
    newname = _unspace_regexps[1].sub('', newname)    # Get rid of quotes
    newname = _unspace_regexps[2].sub('+', newname)   # Ampersands turn into plusses
    newname = newname.replace('-.', '.')              # Don't leave a dash right before the file extension
    newname = newname.strip('-')                      # Get rid of leading and trailing dashes
    return newname

_unspace_regexps = None

# get_repr_map(), get_repr_info(), download_repr() {{{2

# For a given Box file, determine available representations and return a dict that maps
#
#   representation_name -> {'url'   : representation info URL,
#                           'paged' : boolean indicating if its a paged representation }

def get_repr_map(file):
    representations = file.get_representation_info()
    repr_map = {}
    for rep in representations:
        url = rep['info']['url']
        name = url[url.rindex('/') + 1:]
        repr_map[name] = {'url' : url,
                          'paged' : rep['properties'].get('paged') == 'true'}
    return repr_map

# `rep` is a dict as found in the values of the name->rep dict returned by get_repr_map()
# This function polls the URL of the representation until the state is no longer pending,
# and returns a tuple of the final state and a dict of the API response.
# If `silent` is True, no messages will be printed.

def get_repr_info(client, rep, silent=False):
    state = None
    attempts = 0
    while attempts < representation_max_attempts and state != 'success':
        response = client.session.get(rep['url']).json()
        state = response['status']['state']
        if state == 'pending':
            if not silent:
                if attempts == 0:
                    print("Representation is pending - waiting..", end='', flush=True)
                print('.', end='', flush=True)
            time.sleep(representation_wait_time)
            attempts += 1
        else:
            break
    if not silent and attempts != 0: print()   # Go to next line if we've printed "waiting" messages
    return state, response

# Download a file representation, either single or paged.
#
#   client - Box client object
#   repr_info - a dict of the API response to a representation info request. This is the second
#               item in the tuple returned by get_repr_info()
#   item_name - the name of the Box file. It will be unspaced before use.
#   savedir   - the directory where representation file(s) will be saved
#   silent    - if True, no messages are printed
#

def download_repr(client, repr_info, item_name, savedir, silent=False):
    repformat = repr_info['representation']
    if "text" in repformat:
        ext = ".txt"
    else:
        ext = '.' + repformat
    basename = unspace_name(os.path.splitext(item_name)[0])
    pages = repr_info.get('metadata', {}).get('pages')
    url = repr_info['content']['url_template']
    if pages is None:
        filename = basename + ext
        if not silent: print(f"Downloading {filename}...", end='', flush=True)
        response = client.session.get(url.replace('{+asset_path}', ''), expect_json_response=False)
        with open(os.path.join(savedir, filename), "wb") as f:
            f.write(response.content)
        if not silent: print('done.')
    else:
        if not silent: print(f"{pages} pages total")
        ndigits = len(str(pages))
        for page in range(1, pages + 1):
            filename = basename + '-' + str(page).rjust(ndigits, '0') + ext
            if not silent: print(f"Downloading {filename}...", end='', flush=True)
            response = client.session.get(url.replace('{+asset_path}', str(page) + ext), expect_json_response=False)
            with open(os.path.join(savedir, filename), "wb") as f:
                f.write(response.content)
            if not silent: print('done.')

# expand_item_ids() {{{2

# Used in commands that accept multiple Box item IDs. Expands a list of IDs as
# entered by the user to numeric Box IDs, handling the stash, history operators, etc.
# If any invalid IDs were entered, returns None.

def expand_item_ids(ids):
    item_ids = []
    for id in ids:
        if id == '@@':
            item_ids.extend(v[1] for v in item_stash.values())
        else:
            if (tid := translate_id(id)) is not None:
                item_ids.append(tid)
            else:
                return None
    return item_ids

# print_item_stash() {{{2

# Prints a table of items currently in the stash.

def print_item_stash():
    items = tuple(v for v in item_stash.values())
    print_table(items, ('Name', 'Id', 'Type'), is_sequence=True)

# }}}1

# Define command functions {{{1

def auth_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s auth [options]',
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

def token_cmd(args):  # {{{2
    if len(args):
        print(f"usage: {progname} token\n\n"
               "Print access token to stdout")
        return
    client = get_ops_client()
    print(client.session._oauth.access_token)

def userinfo_cmd(args):  # {{{2
    if len(args):
        print(f"usage: {os.path.basename(sys.argv[0])} userinfo\n\n"
               "Print authorized user information")
        return
    client = get_ops_client()
    user = client.user().get()
    print_table((user,), ('name', 'login', 'id'), colgap=4)

def history_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s history [options] [filter]',
                                         description='Show previous ID history')
    cli_parser.add_argument('filter', nargs='?',
                            help='If given, only entries whose names match (case-insensitively) will be shown.')
    cli_parser.add_argument('-Q', '--clear', action='store_true', help='Clear history')
    cli_parser.add_argument('-d', '--delete', metavar='ID', action='append',
                            help='Delete the given item ID from history')
    cli_parser.add_argument('-n', '--max-count', type=int, default=0,
                            help='Maximum number of (most-recent) items to return')
    cli_parser.add_argument('-l', '--limit', type=int, default=0,
                            help='Same as --max-count')
    cli_parser.add_argument('-P', '--no-parent', action='store_true',
                            help="Don't include parent folder information in output")
    cli_parser.add_argument('-m', '--max-name-length', metavar='N', type=int,
                            help='Clip the names of items in the displayed table to N characters')
    cli_parser.add_argument('-M', '--max-id-length', metavar='N', type=int,
                            help='Clip the item IDs in the displayed table to N characters')
    options = cli_parser.parse_args(args)
    filter_word = options.filter
    # First let's handle any of the clear/delete options if need be, since we can then exit
    if options.clear:
        n = len(item_history_map)
        item_history_map.clear()
        print(f"Removed {n} entries from our item history")
        return
    elif options.delete:
        for _id in options.delete:
            if (item_id := translate_id(_id)) is None:
                continue  # A message was already printed by translate_id()
            elif item_id not in item_history_map:
                print(f"Item with ID {_id} not found in history")
            else:
                entry = item_history_map.pop(item_id)
                name = entry['name']
                print(f'Removed item {item_id} "{name}" from history')
        return
    # Done with clear/delete
    max_count = options.max_count or options.limit
    no_parent = options.no_parent
    max_name_len = get_name_len(options.max_name_length)
    max_id_len = get_id_len(options.max_id_length)
    if filter_word and len(filter_word) <= 2 and filter_word.isdigit():
        # I just forgot to type the '-n', but meant to limit the count
        max_count = int(filter_word)
        filter_word = None
    #
    history_view = item_history_map.values()
    if max_count:
        history_view = reversed(history_view)
    if filter_word:
        history_view = filter(lambda entry : filter_word.lower() in entry['name'].lower(),
                              history_view)
    if max_count:
        history_items = []
        for i in range(max_count):
            if item := next(history_view, None):
                history_items.append(item)
            else:
                break
        history_items.reverse()
    else:
        history_items = list(history_view)
    fields = ['name', 'id']
    if not no_parent: fields.append('parent_name')
    print_table(history_items, fields, is_dict=True,
                clip_fields={'name' : (max_name_len, 'r'), 'id' : (max_id_len, 'l'),
                             'parent_name' : (max_name_len, 'r')})

def ls_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(
         exit_on_error=False,
         prog=progname, usage='%(prog)s ls [options] [id...]',
         description='List one or more folders. If no folder IDs are given, use '
                     'the ID of the folder most recently listed, if available.'
    )
    cli_parser.add_argument('id', nargs='*', help='Folder ID(s)')
    cli_parser.add_argument('-H', '--no-header', action='store_true',
                            help='Do not print header text for the listing')
    cli_parser.add_argument('-l', '--limit', type=int, default=None,
                            help='Maximum number of items to return')
    cli_parser.add_argument('-o', '--offset', type=int, default=0,
                            help='The number of results to skip before displaying results')
    cli_parser.add_argument('-f', '--only-files', action='store_true', help='Only list files')
    cli_parser.add_argument('-d', '--only-folders', action='store_true', help='Only list folders')
    cli_parser.add_argument('-n', '--sort-name', action='store_true', help='Sort by name (A->Z)')
    cli_parser.add_argument('-t', '--sort-date', action='store_true', help='Sort by date (Old->New)')
    cli_parser.add_argument('-r', '--reverse', action='store_true', help='Reverse sort direction')
    cli_parser.add_argument('-m', '--max-name-length', metavar='N', type=int,
                            help='Clip the names of items in the displayed table to N characters')
    cli_parser.add_argument('-M', '--max-id-length', metavar='N', type=int,
                            help='Clip the item IDs in the displayed table to N characters')
    cli_parser.add_argument('-q', '--history', action='store_true',
                            help='Display queue of ls folder history')
    cli_parser.add_argument('-Q', '--clear-history', action='store_true',
                            help='Clear queue of ls folder history')
    options = cli_parser.parse_args(args)
    folder_ids = [translate_id(_id) for _id in options.id]
    if any(id is None for id in folder_ids):  # translate_id() failed
        return
    print_header = not options.no_header
    limit = options.limit
    offset = options.offset
    if options.only_files and options.only_folders:
        print("-f/--only-files and -d/--only-folders are mutually exclusive")
        return
    filter_func = (lambda item: item.type == 'file') if options.only_files else \
                  (lambda item: item.type == 'folder') if options.only_folders else \
                  None
    sort = 'name' if options.sort_name else \
           'date' if options.sort_date else \
           None
    direction = 'DESC' if options.reverse else 'ASC'
    max_name_len = get_name_len(options.max_name_length)
    max_id_len = get_id_len(options.max_id_length)
    if options.clear_history:
        ls_history_deque.clear()
        print("ls history cleared")
        return
    if options.history:
        print_table(ls_history_deque, is_sequence=True,
                    fields=('name', 'id', 'parent'), no_leader_fields=('ID',),
                    clip_fields={'name': (max_name_len, 'r'), 'id': (max_id_len, 'l'), 'parent': (max_name_len, 'r')})
        return
    if len(folder_ids) == 0:
        if len(ls_history_deque) > 0:
            global current_cmd_last_id
            current_cmd_last_id = ls_history_deque[-1][1]
            folder_ids = (current_cmd_last_id,)
        else:
            print("No folder ID given and history is empty")
            return
    client = get_ops_client()
    for i, folder_id in enumerate(folder_ids):
        folder = client.folder(folder_id=folder_id).get()
        items = retrieve_folder_items(client, folder, limit=limit, start_offset=offset,
                                      fields=['type', 'name', 'id', 'parent', 'description'],
                                      sort=sort, direction=direction, filter_func=filter_func)
        add_history_item(folder)
        if len(ls_history_deque) == 0 or ls_history_deque[-1][1] != folder.id:
            if _p := folder.parent:
                _parname, _parid = _p.name, _p.id
            else:
                _parname, _parid = None, None
            ls_history_deque.append((folder.name, folder.id, _parname, _parid))
        if _parent := folder.parent:
            _parent = _parent.get(fields=['id', 'name', 'type', 'parent'])
            add_history_item(_parent)
        for item in items:
            add_history_item(item, parent=folder)
        if print_header:
            print_name_header(f"{folder.name} [{folder.id}]", leading_blank=i != 0,
                              context_info=f'(Parent: {_parent.name} [{_parent.id}])' if _parent else
                                            '(Parent: All Files [0])')
            if desc := folder.description:
                print("~~ Description", '~' * (screen_cols//2 - 15))
                print(desc)
                print('~' * (screen_cols//2))
        elif i != 0:
            print()
        # We use the field_val_func to indicate if an item has a description, similar to the web interface
        print_table(items, ('type', 'name', 'id'), print_header=print_header, no_leader_fields=('type',),
                    clip_fields={'name': (max_name_len, 'r'), 'id': (max_id_len, 'l')},
                    field_val_func =
                        lambda v, item, idx, field :
                            v + " (i)" if field == 'name' and item.description else v)

def search_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s fd [options] term',
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
    cli_parser.add_argument('-m', '--max-name-length', metavar='N', type=int,
                            help='Clip the names of items in the displayed table to N characters')
    cli_parser.add_argument('-M', '--max-id-length', metavar='N', type=int,
                            help='Clip the item IDs in the displayed table to N characters')
    options = cli_parser.parse_args(args)
    term = options.term
    do_files, do_folders = options.files, options.folders
    if do_files and do_folders:
        print("You can supply exactly one of --files/-f or --folders/-d")
        return
    result_type = 'file' if do_files else 'folder' if do_folders else None
    limit = options.limit
    offset = options.offset
    content_types=['name'] if options.name_only else None
    no_parent = options.no_parent
    if options.ancestors:
        ancestor_ids = [translate_id(id.strip()) for id in options.ancestors.split(",")]
        if any(id is None for id in ancestor_ids):
            return
    else:
        ancestor_ids = None
    extensions = [ext.strip(" .") for ext in options.extensions.split(",")] \
                    if options.extensions else None
    fields=['name', 'id', 'type', 'parent']
    max_name_len = get_name_len(options.max_name_length)
    max_id_len = get_id_len(options.max_id_length)
    client = get_ops_client()
    ancestors = [client.folder(id) for id in ancestor_ids] if ancestor_ids else None
    results = client.search().query(query=term, limit=limit, offset=offset,
                                    ancestor_folders=ancestors, file_extensions=extensions,
                                    result_type=result_type, content_types=content_types, fields=fields)
    # We can't just throw the iterator returned by query() into a list(), because it stalls,
    # so we need to manually retrieve 'limit' items
    items = []
    for i, result_item in enumerate(results, start=1):
        item = { 'type' : result_item.type,
                 'name' : result_item.name,
                 'id'   : result_item.id }
        add_history_item(result_item)
        if _p := result_item.parent:
            item['parent'], item['parent_id']  = _p.name, _p.id
            add_history_item(_p)
        else:
            item['parent'] = item['parent_id'] = None
        items.append(item)
        if i == limit: break
    fields = ['name', 'id']
    if result_type is None:
        fields.insert(0, 'type')
    if not no_parent:
        fields.extend(('parent', 'parent_id'))
    print_table(items, is_dict=True, fields=fields, no_leader_fields=('type',),
                clip_fields={'name'   : (max_name_len, 'r'), 'id'        : (max_id_len, 'l'),
                             'parent' : (max_name_len, 'r'), 'parent_id' : (max_id_len, 'l')})

def tree_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s tree [options] folder_id',
                                         description='Display a tree of items')
    cli_parser.add_argument('folder_id', help='Folder ID')
    cli_parser.add_argument('-L', '--max-levels', type=int, default=999, metavar='LEVELS',
                            help='Maximum number of levels to recurse (>= 1)')
    cli_parser.add_argument('-d', '--directories-only', action='store_true', help='Only show directories')
    cli_parser.add_argument('-C', '--max-count', metavar='N', type=int, default=0,
        help='Gather at most N items for display. Useful to prevent unintended deep folder recursion.')
    cli_parser.add_argument('-i', '--re-include', metavar='RE',
                help='Only display items and recurse into sub-folders whose names fully match RE')
    cli_parser.add_argument('-x', '--re-exclude', metavar='RE',
                help='Exclude items and sub-folders whose names fully match RE')
    cli_parser.add_argument('-F', '--force-recurse', action='store_true',
                            help='Recurse into directories regardless of regexp filters')
    cli_parser.add_argument('-H', '--no-header', action='store_true',
                            help='Do not print the full folder path before the tree')
    cli_parser.add_argument('-s', '--stash-files', action='store_true',
                            help='Add encountered files to the item stash')
    cli_parser.add_argument('-S', '--stash-folders', action='store_true',
                            help='Add encountered folders to the item stash')
    cli_parser.add_argument('-I', '--stash-initial-folder', action='store_true',
                            help='With -S, --stash-folders: also add the initial folder to the stash')
    cli_parser.add_argument('-a', '--append-stash', action='store_true',
                            help='Append items to the current stash, rather than replacing it')
    options = cli_parser.parse_args(args)
    folder_id = translate_id(options.folder_id)
    if not folder_id:
        return
    max_levels = options.max_levels
    if max_levels <= 0:
        print('--max-levels must be >= 1')
        return
    max_count = options.max_count
    re_include_pattern = options.re_include and re.compile(options.re_include)
    re_exclude_pattern = options.re_exclude and re.compile(options.re_exclude)
    force_recurse = options.force_recurse
    dirs_only = options.directories_only
    no_header = options.no_header
    stash_files = options.stash_files
    stash_folders = options.stash_folders
    stash_initial_folder = options.stash_initial_folder
    append_stash = options.append_stash
    if (stash_files or stash_folders) and not append_stash:
        item_stash.clear()
    indent_str = " " * 2
    client = get_ops_client()
    tree_entries = []
    ####
    def _item_passes_filters(item):
        return (not re_include_pattern or re_include_pattern.fullmatch(item.name)) and \
               (not re_exclude_pattern or not re_exclude_pattern.fullmatch(item.name))
    ####
    def _tree_helper(folder, level):
        add_history_item(folder)
        name_part, id_part = None, folder.id
        if level == 0:
            name_part = folder.name + '/'
        else:
            marker = _tree_item_markers[level % len(_tree_item_markers)]
            name_part = (indent_str * level) + f"{marker} {folder.name}/"
        tree_entries.append((name_part, id_part))
        if stash_folders:
            if level != 0:
                # We could have arrived here because --force-recurse was used, but we only want to add the folder
                # to the stash if it actually passes any filters that may be active.
                if not force_recurse or _item_passes_filters(folder):
                    item_stash[folder.id] = (folder.name, folder.id, 'folder')
            elif stash_initial_folder:
                item_stash[folder.id] = (folder.name, folder.id, 'folder')
        if level < max_levels:
            if sys.stdout.isatty():  # Display a progress report
                sys.stdout.write('\033[2K\033[1G') # erase and go to beginning of line
                print('*', folder.name + '/', end="", flush=True)
            limit = max_count - len(tree_entries) if max_count else None
            if dirs_only:
                # Since folders are always returned before other item types, we can break_on_filter;
                # also, we specify a small pagesize_limit so that we don't retrieve the whole
                # BOX_GET_ITEMS_LIMIT page from a folder, most of which will be files.
                items = retrieve_folder_items(client, folder, sort='name', pagesize_limit=30,
                                              filter_func=lambda it: it.type == 'folder',
                                              break_on_filter=True, limit=limit)
            else:
                items = retrieve_folder_items(client, folder, sort='name', limit=limit)
            level += 1
            file_entry_prefix = (indent_str * level) + _tree_item_markers[level % len(_tree_item_markers)] + ' '
            for item in items:
                if max_count and len(tree_entries) >= max_count:
                    break
                elif force_recurse and item.type == 'folder':
                    _tree_helper(item, level)
                elif not _item_passes_filters(item):
                    continue
                elif item.type == 'folder':
                    _tree_helper(item, level)
                else:  # What we have is a file or web-link that passes our filters
                    add_history_item(item)
                    tree_entries.append((file_entry_prefix + item.name, item.id))
                    if stash_files and item.type == 'file':
                        item_stash[item.id] = (item.name, item.id, 'file')
            level -= 1
        if level == 0 and sys.stdout.isatty():
            sys.stdout.write('\033[2K\033[1G')  # Erase the progress report text
    ####
    initial_folder = client.folder(folder_id).get()
    if not no_header:
        path_entries = [f.name for f in initial_folder.path_collection['entries'][1:]]
        path_entries.append(initial_folder.name)
        full_path = '/' + '/'.join(path_entries) + '/'
        _hr = "─" * (len(full_path) + 2)
        print(_hr, full_path, _hr, sep='\n')
    try:
        _tree_helper(initial_folder, 0)
    except KeyboardInterrupt:
        sys.stdout.write('\033[2K\033[1G')
        print("Cancelled")
        # But we'll print out what we have anyway, so the user knows why it was taking a long time
    print_table(tree_entries, ('name_part', 'id_part'), print_header=False, is_sequence=True)

_tree_item_markers = ['*', '-']

def unspace_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                    prog=progname, usage='%(prog)s unspace ids',
                    description='Rename items to remove spaces and other troublesome characters')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    client = get_ops_client()
    for item_id in item_ids:
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        item = item.get(fields=['id', 'name', 'type', 'parent'])
        newname = unspace_name(item.name)
        if item.name != newname:
            print(f'Renaming "{item.name}" -> "{newname}"')
            item.rename(newname)
            item.name = newname
            add_history_item(item)

def stash_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                    prog=progname, usage='%(prog)s stash [options]',
                    description='Manipulate the item stash')
    group = cli_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-l', '--list', action='store_true', help='Print items in stash')
    group.add_argument('-a', '--add', nargs='+', metavar='IDS', help='Add IDS to the item stash')
    group.add_argument('-r', '--remove', nargs='+', metavar='IDS', help='Remove IDS from the item stash')
    group.add_argument('-Q', '--clear', action='store_true', help='Clear the item stash')
    options = cli_parser.parse_args(args)
    if options.list:
        print_item_stash()
    elif options.add:
        ids = expand_item_ids(options.add)
        if not ids: return
        client = get_ops_client()
        for item_id in ids:
            _type, item = get_api_item(client, item_id)
            item_stash[item.id] = (item.name, item.id, item.type)
            print("Added:", item.name)
    elif options.remove:
        ids = expand_item_ids(options.remove)
        if not ids: return
        for item_id in ids:
            entry = item_stash.pop(item_id, None)
            if entry is not None:
                print("Removed:", entry[0])
    elif options.clear:
        item_stash.clear()
        print("Stash cleared")

def get_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s get [options] ids... directory',
                                         description='Download files or representations')
    cli_parser.add_argument('ids', nargs='+', help='File or Folder IDs')
    cli_parser.add_argument('directory', help='Destination directory')
    cli_parser.add_argument('-d', '--folders', action='store_true',
                            help="Item IDs specify folders from which to download files")
    cli_parser.add_argument('-i', '--re-include', metavar='RE',
                            help="Applies when -d/--folders is used: rather than downloading all files "
                                 "from the specified folders, only download those files whose names "
                                 "fully match the regular expression RE")
    cli_parser.add_argument('-x', '--re-exclude', metavar='RE',
                            help="Applies when -d/--folders is used: exclude files whose names fully match RE")
    cli_parser.add_argument('-r', '--representation', metavar='REPR',
                            help="Rather than downloading the file itself, download the representation given "
                                 "by REPR. (Use the 'repr' command to find possible values of REPR)")
    cli_parser.add_argument('-n', '--include-repname', action='store_true',
                            help="With --representation, include the representation name in the downloaded file name")
    cli_parser.add_argument('-u', '--unspace', action='store_true', help='unspace file names when saving locally')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    target_dir = expand_all(options.directory)
    if not os.path.isdir(target_dir):
        print(f"{target_dir} is not a directory!")
        return
    repname = options.representation
    include_repname = options.include_repname
    if repname:
        repname = representation_aliases.get(repname, repname)
    do_folders = options.folders
    include_pattern = options.re_include and re.compile(options.re_include)
    exclude_pattern = options.re_exclude and re.compile(options.re_exclude)
    unspace = options.unspace
    client = get_ops_client()
    for item_id in item_ids:
        if do_folders:
            folder = client.folder(folder_id=item_id).get()
            print(f'== Retrieving files from "{folder.name}" ==')
            def _filter_func(item):
                if item.type != 'file':
                    return False
                elif include_pattern and not include_pattern.fullmatch(item.name):
                    return False
                elif exclude_pattern and exclude_pattern.fullmatch(item.name):
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
            if unspace:
                filename = unspace_name(filename)
            if repname:
                repr_map = get_repr_map(file)
                rep = repr_map.get(repname)
                if rep is None:
                    print(f'Representation "{repname}" not available for {filename}')
                    continue
                state, repr_info = get_repr_info(client, rep)
                if state != 'success':
                    print(f'Failed to retrieve representation info for {filename}')
                    continue
                if include_repname:
                    root, ext = os.path.splitext(filename)
                    repr_filename = root + '-' + repname + ext
                else:
                    repr_filename = filename
                download_repr(client, repr_info, repr_filename, target_dir)
            else:
                print(f"Downloading {filename}...")
                with open(os.path.join(target_dir, filename), "wb") as f:
                    file.download_to(f)

def zip_cmd(args): # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s zip [options] ids... zipfile',
                                         description='Download a ZIP file of items')
    cli_parser.add_argument('ids', nargs='+', help='File or Folder IDs')
    cli_parser.add_argument('zipfile', help='ZIP file destination')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    zipfile = expand_all(options.zipfile)
    if not zipfile.lower().endswith(".zip"):
        zipfile += ".zip"
    client = get_ops_client()
    items = [get_api_item(client, id)[1] for id in item_ids]
    zipname = os.path.basename(zipfile)
    print(f"Downloading items to {zipname} (this may take a while)...\n", flush=True)
    for item in items:
        print("  * ", item.name, '/' if item.type == 'folder' else "", sep="")
    print(flush=True)
    with open(zipfile, 'wb') as f:
        status_dict = client.download_zip(zipname, items, f)
    total, downloaded, skipped = \
        (status_dict[k] for k in ('total_file_count', 'downloaded_file_count', 'skipped_file_count'))
    print(f"Total Files: {total} ({downloaded} downloaded, {skipped} skipped)")


def repr_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s repr [options]',
                                         description='Get representation information')
    group = cli_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-l', '--list', dest='file_id', metavar='ID',
                       help='List available representations for a file')
    group.add_argument('-a', '--aliases', action='store_true', help='Print representation aliases')
    options = cli_parser.parse_args(args)
    if options.aliases:
        aliases = list(representation_aliases.items())
        print_table(aliases, ('Alias', 'Representation'), no_leader_fields = ('Alias',), is_sequence=True)
    else:
        file_id = translate_id(options.file_id)
        if file_id is None:
            return
        client = get_ops_client()
        file = client.file(file_id).get()
        repr_map = get_repr_map(file)
        print(f'Available representations for "{file.name}":', end='\n\n')
        for (repname, rep) in repr_map.items():
            print(f"  {repname}{' (paged)' if rep['paged'] else ''}")
        print()

def put_cmd(args):  # {{{2
    import glob
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s put [options] file(s)',
                                         description='Upload files')
    cli_parser.add_argument('files', nargs='+', help='File(s) to upload')
    cli_parser.add_argument('-f', '--file-version', metavar='file_id',
                            help='Upload a new version of a file')
    cli_parser.add_argument('-d', '--folder', metavar='folder_id',
                            help='Upload a file into a given folder')
    options = cli_parser.parse_args(args)
    file_id = options.file_version
    folder_id = options.folder
    files = [file for pathspec in options.files for file in glob.glob(expand_all(pathspec))]
    if not any((file_id, folder_id)) or all((file_id, folder_id)):
        print("You must supply exactly one of --file-version/-f or --folder/-d")
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
            file = file.get_chunked_uploader(filepath).start()
        else:
            file = file.update_contents(filepath)
        if os.path.basename(filepath) != box_filename:
            file = file.rename(os.path.basename(filepath))
        add_history_item(file)
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
                    file = folder.get_chunked_uploader(filepath).start()
                else:
                    file = folder.upload(filepath)
                add_history_item(file)
                print("done")
            except BoxAPIException as ex:
                if ex.status == 409:
                    _file_id = ex.context_info['conflicts']['id']
                    print('(new version)...', end="", flush=True)
                    file = client.file(_file_id)
                    if use_chunked:
                        file = file.get_chunked_uploader(filepath).start()
                    else:
                        file = file.update_contents(filepath)
                    add_history_item(file)
                    print("done")
                else:
                    raise ex

def cat_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s cat [options] ids...',
                                         description='Write the contents of files or web-links to stdout')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs to print')
    cli_parser.add_argument('-H', '--headers', action='store_true',
                            help="Print a header before each items's contents")
    cli_parser.add_argument('-c', '--byte-count', metavar='N', type=int, default=4096,
                            help='Print the first N bytes of files (default %(default)s)')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    byte_count = options.byte_count
    headers = options.headers
    client = get_ops_client()
    for i, item_id in enumerate(item_ids):
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        if _type == 'web_link':
            web_link = item.get(fields=['name', 'url'])
            if headers:
                print_name_header(web_link.name, leading_blank=i != 0)
            print(web_link.url)
        elif _type == 'file':
            file = item.get(fields=['name'])
            filename = file.name
            if headers:
                print_name_header(filename, leading_blank=i != 0)
            content = file.content(byte_range=(0, byte_count))
            str_rep = content.decode(errors='backslashreplace')
            print(str_rep, end='' if str_rep[-1] == '\n' else '\n')
        else:
            print(f"You cannot cat a {_type}")

def rm_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s rm [options] ids...',
                                         description='Remove items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs to remove')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    client = get_ops_client()
    for item_id in item_ids:
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        item = item.get(fields=['id', 'name'])
        print(f"Deleting {_type} {item.name}...")
        item.delete()
        item_history_map.pop(item_id, None)

def path_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s path [options] ids...',
                                         description='Get full path of items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    cli_parser.add_argument('-R', '--rclone', action='store_true', help='Format paths for use with rclone')
    cli_parser.add_argument('-v', '--verbose', action='store_true', help="Verbose output format")
    options = cli_parser.parse_args(args)
    rclone = options.rclone
    verbose = options.verbose
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    client = get_ops_client()
    for i, id in enumerate(item_ids):
        if id == '0':
            print('{rclone_remote_name}:/') if rclone else print('/')
        else:
            _type, item = get_api_item(client, id)
            if not _type: continue
            item = item.get()
            if verbose:
                if i != 0: print()
                path_items = item.path_collection['entries'].copy()
                path_items.append(item)
                for j, path_item in enumerate(path_items[1:]):
                    print(" " * (j*2) + '/ ', end="")
                    print(f"{path_item.name} [{path_item.id}]")
                    add_history_item(path_item, parent=path_items[j])
            else:
                path_entries = [folder.name for folder in item.path_collection['entries'][1:]]
                path_entries.append(item.name)
                path = "/" + "/".join(path_entries)
                if rclone:
                    print('box:', end="")
                print(path)

def mkdir_cmd(args):  # {{{2
    if len(args) < 2 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} mkdir parent_folder_id folder_name\n\n"
               "Create a new folder")
        return
    parent_folder_id = translate_id(args[0])
    foldername = args[1]
    client = get_ops_client()
    folder = client.folder(folder_id=parent_folder_id).get(fields=['id', 'name', 'type', 'parent'])
    print(f'Creating "{foldername}" in "{folder.name}"...', end='')
    newfolder = folder.create_subfolder(foldername)
    print('ID:', newfolder.id)
    add_history_item(newfolder, folder)

def mv_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s mv [options] ids... dest_folder_id',
                                         description='Move items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs to move')
    cli_parser.add_argument('dest_folder_id', help='Destination folder ID')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    dest_folder_id = translate_id(options.dest_folder_id)
    if dest_folder_id is None:
        return
    client = get_ops_client()
    dest_folder = client.folder(folder_id=dest_folder_id)
    for item_id in item_ids:
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        moved_item = item.move(parent_folder=dest_folder)
        print(f'Moved {_type} "{moved_item.name}" into "{moved_item.parent.name}"')
        add_history_item(moved_item)

def cp_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s cp [options] ids... dest_folder_id',
                                         description='Copy items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs to copy')
    cli_parser.add_argument('dest_folder_id', help='Destination folder ID')
    options = cli_parser.parse_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    dest_folder_id = translate_id(options.dest_folder_id)
    if dest_folder_id is None:
        return
    client = get_ops_client()
    dest_folder = client.folder(folder_id=dest_folder_id)
    for item_id in item_ids:
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        copied_item = item.copy(parent_folder=dest_folder)
        print(f'Copied {_type} "{copied_item.name}" into "{copied_item.parent.name}"')
        add_history_item(copied_item)

def rn_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s rn [options] id new_name',
                                         description='Rename an item')
    cli_parser.add_argument('id', help='Item ID')
    cli_parser.add_argument('new_name', help='New name for the item')
    options = cli_parser.parse_args(args)
    item_id = translate_id(options.id)
    new_name = options.new_name
    if item_id is None:
        return
    client = get_ops_client()
    _type, item = get_api_item(client, item_id)
    if not _type:
        return
    item = item.get(fields=['id', 'name', 'type', 'parent'])
    oldname = item.name
    item = item.rename(new_name)
    add_history_item(item)
    print(f'{_type.capitalize()} "{oldname}" renamed to "{item.name}"')

def desc_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                    prog=progname, usage='%(prog)s desc [options] ids',
                    description='Print or update the description of an item',
                    epilog='If -d, --description is not given, print the descriptions for given items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    cli_parser.add_argument('-d', '--description', metavar='DESC',
                            help='Set description for single item to DESC. Use a blank string for DESC '
                                 'to remove an existing description.')
    cli_parser.add_argument('-e', '--enable-escapes', action='store_true',
                            help='When setting description, enable Python string literal backslash escapes')
    cli_parser.add_argument('-a', '--append', action='store_true',
                            help='When setting description, append to current description rather than replace it.')
    options = cli_parser.parse_intermixed_args(args)
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    description = options.description
    enable_escapes = options.enable_escapes
    append = options.append
    if description is not None and len(item_ids) != 1:
        print("You can set the description for only one item at a time.")
        return
    client = get_ops_client()
    if description is not None:
        _type, item = get_api_item(client, item_ids[0])
        if not _type: return
        if enable_escapes:
            description = ast.literal_eval('"' + description.replace('"', '\\"') + '"')
        if append:
            item = item.get(fields=('name', 'description'))
            if item.description:
                description = item.description + description
        item = item.update_info(data = {'description' : description})
        print(f'Updated the description of {_type} "{item.name}"')
    else:
        for i, item_id in enumerate(item_ids):
            _type, item = get_api_item(client, item_id)
            if not _type: continue
            item = item.get(fields=('name', 'description'))
            if i != 0: print()
            if item.description:
                print_name_header(item.name)
                print(item.description)
            else:
                print(f'{_type.capitalize()} "{item.name}" has no description attached')

def ln_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s ln [options] ids...',
                                         description='Get links for files or folders')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    cli_parser.add_argument('-p', '--password', help='Set a password to access items')
    cli_parser.add_argument('-r', '--remove', action='store_true', help='Remove shared link from items')
    options = cli_parser.parse_args(args)
    password = options.password
    remove = options.remove
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    client = get_ops_client()
    for i, item_id in enumerate(item_ids):
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        if remove:
            item.remove_shared_link()
            item = item.get(fields=['id', 'name', 'type', 'parent'])
            print(f'Removed shared link for {_type} "{item.name}"')
        else:
            link = item.get_shared_link(allow_download=True, allow_preview=True, password=password)
            item = item.get(fields=['id', 'name', 'type', 'parent', 'shared_link'])
            if i != 0: print()
            if _type == 'file':
                print("== File:", item.name)
                print("   Link:", link)
                print(" Direct:", item.shared_link['download_url'])
            elif _type == 'folder':
                print("== Folder:", item.name)
                print("     Link:", link)
            else:
                print(f"Unable to get link for type \"{_type}\"")

def readlink_cmd(args):  # {{{2
    if len(args) != 1 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} readlink shared_url\n\n"
               "Get info about the item referred to by a shared link.\n\n"
               'Note that this only works for "Shared URLs", not "Download URLs"')
        return
    shared_url = args[0]
    client = get_ops_client()
    item = client.get_shared_item(shared_url)
    print_stat_info(item)

def stat_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s stat [options] ids...',
                                         description='Get info about items')
    cli_parser.add_argument('ids', nargs='+', help='Item IDs')
    fieldgroup = cli_parser.add_mutually_exclusive_group()
    fieldgroup.add_argument('-f', '--fields', help='Specify fields to show, as a comma-separated list')
    fieldgroup.add_argument('-d', '--only-dates', action='store_true',
                            help='Only show the name and date fields')
    fieldgroup.add_argument('-m', '--only-mtime', action='store_true',
                            help='Only show the name and content_modified_at fields')
    fieldgroup.add_argument('-c', '--only-size-count', action='store_true',
                            help='Only show the name, size, and item_count fields (for folders)')
    options = cli_parser.parse_args(args)
    fields = None
    if options.fields:
        fields = tuple(f.strip() for f in options.fields.split(','))
    elif options.only_dates:
        fields = ('name', 'content_created_at', 'content_modified_at', 'created_at', 'modified_at')
    elif options.only_mtime:
        fields = ('name', 'content_modified_at')
    elif options.only_size_count:
        fields = ('name', 'size', 'item_count')
    item_ids = expand_item_ids(options.ids)
    if not item_ids:
        return
    client = get_ops_client()
    for i, item_id in enumerate(item_ids):
        _type, item = get_api_item(client, item_id)
        if not _type: continue
        item = item.get()
        if i != 0: print()
        print_stat_info(item, fields=fields)

def trash_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(
        exit_on_error=False,
        prog=progname, usage='%(prog)s trash [options] action ids',
        description='List, view, restore, or purge items in the trash.',
        epilog='To get a reasonable listing of recently deleted items, use "trash list -trl 10", '
                'which will show the 10 most-recently-deleted items, newest first.'
    )
    cli_parser.add_argument('action', help='Action to perform: l[ist]/ls, s[tat], r[estore], p[urge]')
    cli_parser.add_argument('ids', nargs='*', help='Item ID(s)')
    cli_parser.add_argument('-l', '--limit', type=int, default=BOX_GET_ITEMS_LIMIT,
                            help='Maximum number of items to return')
    cli_parser.add_argument('-o', '--offset', type=int, default=0,
                            help='The number of results to skip before displaying results')
    sort_group = cli_parser.add_mutually_exclusive_group()
    sort_group.add_argument('-n', '--sort-name', action='store_true', help='Sort listing by name (A->Z)')
    sort_group.add_argument('-t', '--sort-date', action='store_true', help='Sort listing by date (Old->New)')
    cli_parser.add_argument('-r', '--reverse', action='store_true', help='Reverse listing sort direction')
    cli_parser.add_argument('-m', '--max-name-length', metavar='N', type=int,
                            help='Clip the names of listed items to N characters')
    cli_parser.add_argument('-M', '--max-id-length', metavar='N', type=int,
                            help='Clip the item IDs of listed items to N characters')
    cli_parser.add_argument('-s', '--name-suffix', metavar='SUFFIX',
        help='When restoring, the item will be renamed by appending "-SUFFIX" to its basename')
    # We use parse_intermixed_args() here so that we can type natural command lines like
    # "trash restore -s restored 1234", which doesn't work with parse_args().
    options = cli_parser.parse_intermixed_args(args)
    do_list1, do_list2, do_stat, do_restore, do_purge = (_a.startswith(options.action) for _a in
                                                ('list', 'ls', 'stat', 'restore', 'purge'))
    do_list = any((do_list1, do_list2))
    if not (do_list or do_stat or do_restore or do_purge):
        print("Valid actions are l[ist]/ls, s[tat], r[estore], p[urge]")
        return
    item_ids = [translate_id(id) for id in options.ids]
    if any(id is None for id in item_ids):
        return
    limit = options.limit
    offset = options.offset
    sort = 'name' if options.sort_name else \
           'date' if options.sort_date else \
           None
    direction = 'DESC' if options.reverse else 'ASC'
    max_name_len = get_name_len(options.max_name_length)
    max_id_len = get_id_len(options.max_id_length)
    name_suffix = options.name_suffix
    client = get_ops_client()
    if do_list:
        items = []
        trashed_items = client.trash().get_items(limit=limit, offset=offset, sort=sort, direction=direction)
        for i, trashed_item in enumerate(trashed_items):
            if i == limit: break
            add_history_item(trashed_item)
            items.append((trashed_item.type, trashed_item.name, trashed_item.id))
        print_table(items, is_sequence=True, fields=('type', 'name', 'id'), no_leader_fields=('type',),
                    clip_fields={'name': (max_name_len, 'r'), 'id': (max_id_len, 'l')})
    else:
        for i, item_id in enumerate(item_ids):
            _type, item = get_api_item(client, item_id)
            if not _type: continue
            item_from_trash = client.trash().get_item(item)
            if do_stat:
                if i != 0: print()
                print_stat_info(item_from_trash, add_history=False)
            elif do_restore:
                if name_suffix:
                    root, ext = os.path.splitext(item_from_trash.name)
                    new_name = root + '-' + name_suffix + ext
                else:
                    new_name = None
                restored_item = client.trash().restore_item(item, name=new_name)
                add_history_item(restored_item)
                print(f'Restored {restored_item.type} "{restored_item.name}" to "{restored_item.parent.name}"')
            elif do_purge:
                print(f'Permanently deleting {_type} "{item_from_trash.name}"...', end='')
                client.trash().permanently_delete_item(item)
                print("done")

def ver_cmd(args):  # {{{2
    cli_parser = argparse.ArgumentParser(exit_on_error=False,
                                         prog=progname, usage='%(prog)s ver [options] id',
                                         description='List, download, and manipulate file versions')
    cli_parser.add_argument('id', help='File ID')
    action_group = cli_parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument('-t', '--list', action='store_true', help='List file versions')
    action_group.add_argument('-d', '--delete', metavar='VERSION', help='Delete file version')
    action_group.add_argument('-r', '--restore', metavar='VERSION', help='Restore a deleted file version')
    action_group.add_argument('-p', '--promote', metavar='VERSION', help='Promote file version')
    action_group.add_argument('-g', '--get', nargs=2, metavar=('VERSION', 'PATH'),
        help='Get (download) a specific file version. The first argument is the version ID, '
             'and the second is a local path where the version contents will be saved.')
    cli_parser.add_argument('-l', '--limit', type=int, default=BOX_GET_ITEMS_LIMIT,
                            help='Maximum number of versions to list')
    cli_parser.add_argument('-o', '--offset', type=int, default=0,
                            help='The number of versions to skip before displaying results')
    options = cli_parser.parse_args(args)
    file_id = translate_id(options.id)
    if file_id is None:
        return
    do_list, do_delete, do_restore, do_promote, do_get = (False,) * 5
    if options.list:
        do_list = True
        limit = options.limit
        offset = options.offset
    elif version_id := options.delete:
        do_delete = True
    elif version_id := options.restore:
        do_restore = True
    elif version_id := options.promote:
        do_promote = True
    elif options.get:
        do_get = True
        version_id, filepath = options.get
    client = get_ops_client()
    file = client.file(file_id).get(fields=['id', 'name', 'created_at', 'file_version'])
    if do_list:
        versions = [{'version_id' : file.file_version.id, 'created' : file.created_at, 'name' : file.name}]
        versions_iter = file.get_previous_versions(limit=limit, offset=offset)
        has_trashed = False
        for ver in versions_iter:
            _id = ver.id
            if ver.trashed_at:
                _id += '*'
                has_trashed = True
            versions.append({'version_id' : _id, 'created' : ver.created_at, 'name' : ver.name})
        buf = io.StringIO()
        table_width = print_table(versions, ('version_id', 'created', 'name'), no_leader_fields=('version_id',),
                                  is_dict=True, output_file=buf)
        print('-' * table_width)
        print(buf.getvalue(), end="")
        del buf
        if has_trashed:
            print("\n* = version has been trashed")
    elif do_delete:
        version_to_delete = client.file_version(version_id)
        file.delete_version(version_to_delete)
        print(f'Version {version_id} of file "{file.name}" trashed')
    elif do_restore:
        # We're going to have to do this manually, like the titans of old.
        try:
            response = client.session.put(f'https://api.box.com/2.0/files/{file_id}/versions/{version_id}',
                                          data='{ "trashed_at" : null }')
        except BoxAPIException as e:
            raise  # Send it upward for handling
        except Exception as e:
            # Everything else we'll just print, since we don't want our loop to exit
            print("An exception occured with our PUT request:\n")
            print(e)
        else:
            if response.status_code == 200:
                version_rsrc = response.json()
                print(f'Version {version_rsrc["id"]} of file "{version_rsrc["name"]}" was restored')
            else:
                print(f'Error: status code {response.status_code}')
    elif do_promote:
        version_to_promote = client.file_version(version_id)
        new_version = file.promote_version(version_to_promote)
        print(f'Promoted version {version_id} of file "{file.name}"',
              f'(new name "{new_version.name}")' if new_version.name != file.name else "")
    elif do_get:
        filepath = expand_all(filepath)
        file_version = client.file_version(version_id)
        print(f'Downloading version {version_id} of "{file.name}" to "{os.path.basename(filepath)}"...')
        with open(filepath, "wb") as f:
            file.download_to(f, file_version=file_version)

def shell_cmd(args):  # {{{2
    print("Type q(uit)/e(xit) to exit the shell, and h(elp)/? for general usage.")
    while True:
        try:
            cmdline = input("> ").strip()
        except KeyboardInterrupt:
            print('^C')
            cmdline = ''
        except EOFError:
            print()
            break
        if len(cmdline) == 0 or cmdline.isspace():
            continue
        elif cmdline in ('quit', 'q', 'exit', 'x'):
            break
        elif cmdline in ('help', 'h', '?'):
            print(general_usage, end="")
        elif cmdline == "cd" or cmdline.startswith("cd "):
            cmdargs = shlex.split(cmdline[2:])
            _n = len(cmdargs)
            if _n == 0:
                _dir = os.path.expanduser("~")
            elif _n == 1:
                _dir = expand_all(cmdargs[0])
            else:
                print("Usage: cd [dir]")
                continue
            try:
                os.chdir(_dir)
                print(os.getcwd())
            except OSError as err:
                print(err)
        elif cmdline == "pwd":
            print(os.getcwd())
        elif cmdline[0] == '!':
            subprocess.run(cmdline[1:], shell=True)
        else:
            # If a KeyboardInterrupt occurs during process_cmdline(), we allow it to terminate
            # the program, so that if an API call spazzes out the user can stop it.
            process_cmdline(cmdline)

def source_cmd(args):  # {{{2
    if len(args) != 1 or '-h' in args or '--help' in args:
        print(f"usage: {os.path.basename(sys.argv[0])} source file\n\n"
               "Read commands from a given file")
        return
    cmdfile = expand_all(args[0])
    if not os.path.exists(cmdfile):
        print(f'"{cmdfile}" is not a file.')
    else:
        with open(cmdfile, "rt") as f:
            for cmdline in f:
                cmdline = cmdline.strip()
                if len(cmdline) == 0 or cmdline[0] == '#':
                    continue
                process_cmdline(cmdline)

# Map command names to the implementing command function  # {{{2
command_funcs = {
    'auth'     : auth_cmd,
    'refresh'  : refresh_cmd,
    'token'    : token_cmd,
    'userinfo' : userinfo_cmd,
    'history'  : history_cmd, 'hist' : history_cmd,
    'ls'       : ls_cmd, 'list' : ls_cmd,
    'fd'       : search_cmd, 'search' : search_cmd, 'find' : search_cmd,
    'tree'     : tree_cmd,
    'unspace'  : unspace_cmd,
    'stash'    : stash_cmd,
    'get'      : get_cmd,
    'zip'      : zip_cmd,
    'repr'     : repr_cmd,
    'put'      : put_cmd,
    'cat'      : cat_cmd,
    'rm'       : rm_cmd, 'del' : rm_cmd,
    'path'     : path_cmd,
    'mkdir'    : mkdir_cmd,
    'mv'       : mv_cmd, 'move' : mv_cmd,
    'cp'       : cp_cmd, 'copy' : cp_cmd,
    'rn'       : rn_cmd, 'rename' : rn_cmd,
    'desc'     : desc_cmd,
    'ln'       : ln_cmd, 'link' : ln_cmd,
    'readlink' : readlink_cmd,
    'stat'     : stat_cmd,
    'trash'    : trash_cmd,
    'ver'      : ver_cmd, 'version' : ver_cmd,
    'shell'    : shell_cmd,
    'source'   : source_cmd,
}
# End command functions }}}1

# main {{{1

if __name__ == '__main__':
    cmdline = sys.argv[1:]
    if len(cmdline) == 0:
        cmdline = ['shell']
    try:
        process_cmdline(cmdline)
    finally:
        save_state()

# }}}1
