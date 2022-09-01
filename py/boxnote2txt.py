#!/usr/bin/env python3

import sys, os.path, json, argparse
from io import StringIO

indent_size = 4

def decode_note_obj(obj, listtype=None, listlevel=0, listitem_cntr=0):
    type_ = obj.get('type')
    content_ = obj.get('content')
    # print(f"Entering {type_ = } with content length = {len(content_) if content_ else 0}")
    if type_ == 'doc' and content_:
        return ''.join(decode_note_obj(x) for x in content_)
    elif type_ == 'paragraph':
        inlines = [decode_note_obj(x) for x in content_] if content_ else []
        inlines.append('\n')
        return ''.join(inlines)
    elif type_ in ('tab_list', 'ordered_list', 'bullet_list') and content_:
        item_content = []
        for i, x in enumerate(content_, start=1):
            item_content.append(decode_note_obj(x, type_, listlevel + 1, i))
        return "".join(item_content)
    elif type_ == 'list_item' and content_:
        item_content = ''.join(decode_note_obj(x) for x in content_)
        if listtype == 'tab_list':
            return " " * (indent_size*listlevel) + item_content
        elif listtype == 'ordered_list':
            return " " * (indent_size*(listlevel-1)) + str(listitem_cntr) + ". " + item_content
        elif listtype == 'bullet_list':
            return " " * (indent_size*(listlevel-1)) + "* " + item_content
    elif type_ == 'text':
        text_ = obj['text']
        if marks_ := obj.get('marks'):
            for mark in marks_:
                mtype_ = mark['type']
                if mtype_ == 'strong':
                    return f'**{text_}**'
                elif mtype_ == 'em':
                    return f'*{text_}*'
        return text_
    else:
        return ""   # Unknown content type


if __name__ == '__main__':
    cli_parser = argparse.ArgumentParser(description='Convert new-style Box Notes to text')
    cli_parser.add_argument('boxnote', help='Box Note JSON input file')
    cli_parser.add_argument('textfile', help='Text output file', nargs='?', default='-')
    cli_parser.add_argument('-i', '--indent', metavar='n', type=int, default=3,
            help='Number of spaces per indent level')
    options = cli_parser.parse_args()

    notefile = options.boxnote
    textfile = options.textfile
    indent_size = options.indent

    with open(notefile, "rt") as f:
        notejson = json.load(f)

    text = decode_note_obj(notejson['doc'])
    if textfile == '-':
        print(text, end='')
    else:
        with open(textfile, "wt") as f:
            f.write(text)
