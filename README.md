# boxtools

(Note that this README applies to the current Python version in the `py/` directory)

## `boxnote2txt.py`

This utility converts Box Notes from the new JSON format to text. It supports these types
of objects:

```
    paragraph
    text (plain, strong, and em)
    hard_break
    code_block
    heading
    horizontal_rule
    blockquote
    tab_list, ordered_list, bullet_list, check_list
    list_item, check_list_item
    table, table_row, table_cell †
```

 † Tables are not rendered as formatted text, but rather as HTML tags

`boxnote2txt.py` has no dependency on the `box-python-sdk`, and can be run with any Python
3.9+ version.


## `boxcli`

What started as a way for me to automate certain file operations turned into a client that
I use exclusively, rather than the web interface. I'm not an enterprise user, so there'll
be missing gaps in that regard.

The biggest chore in installing `boxcli` is that you'll need to create an OAuth2 Box App,
just as if you were using the official Box CLI. They've documented this process here:

* https://developer.box.com/guides/cli/quick-start/create-oauth-app/

Once you have the Client ID and Secret, you can go about setting up this Python CLI.
Basically:

1. Symlink the `boxcli` script from `py/` into a directory on your PATH.

2. Run `boxcli` once -- it will create a `~/.boxtools` directory.

3. Edit `~/.boxtools/boxtools.toml` and fill in the client-id and client-secret from the
   Box App that you created.

4. Run `boxcli --help` to see usage and command information.

What sets this Python CLI apart is that it attempts not to replicate the REST API, but to
provide an efficient way of working with Box interactively from the command line. The
modes of referencing items from history, and the stash, are perhaps the two most useful
improvements over the standard CLI. For instance,

```
$ boxcli shell
Type q(uit)/e(xit) to exit the shell, and h(elp)/? for general usage.
> ls 0

Type    Name                     Id
------------------------------------------
folder  Backup ················  […]995872
folder  Books & Literature ····  […]649006
folder  Code ··················  […]936343
folder  Docs ··················  […]929133
folder  Documents ·············  […]951403
folder  Media ·················  […]263706
folder  Misc ··················  […]690675
folder  Transfer ··············  […]939135
folder  Work ··················  […]936975

> ls Doc/03     <-- one of many shortcut styles for referring to a history item

[...]

> ls ..         <-- view the parent folder of the most-recently listed folder

> tree -s -i '.*\.txt' ^Books    <-- recursively go through "Books & Literature" and add
                                     all .txt files to the stash

> mv @@ Tra/35  <-- move all of those stashed .txt files to "Transfer"
```

But the official Box CLI covers the whole API, while this project treats just a subset:

```
    auth          Obtain auth tokens via OAuth2
    refresh       Refresh existing auth tokens
    token         Print access token to stdout

    userinfo      Print authorized user info
    history,hist  Show previous ID history

    ls, list      List contents of a folder
    fd, search    Search for items
    tree          Display a tree of items and add to stash

    get           Download files or representations
    zip           Download a ZIP file of items
    repr          Get represenation information
    put           Upload files
    cat           Write the contents of files or web-links to stdout
    mkdir         Create a new folder
    rm, del       Remove files or folders
    mv, move      Move files or folders
    cp, copy      Copy files or folders
    rn, rename    Rename a file or folder

    ln, link      Get links for files or folders
    readlink      Get the item referred to by a shared link
    path          Get full path of files or folders
    stat          Get info about the item referred to by a shared link
    desc          Print or update the description of a file or folder
    trash         List, view, restore, or purge items in the trash.
    ver, version  List, download, and manipulate file versions
    unspace       Rename items to remove spaces and other odd chars
    stash         Manipulate the item stash

    source        Read commands from a given file
    shell         Enter an interactive shell. Certain commands are handled
```

See [`py/resources/usage.txt`](py/resources/usage.txt) for the built-in help.
