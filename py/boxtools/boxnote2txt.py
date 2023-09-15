#!/usr/bin/env python3

import sys, os.path, json, argparse, re
from io import StringIO

indent_size = 4
code_block_style = ''

def decode_note_obj(obj, listtype=None, listlevel=0, listitem_cntr=0):
    type_ = obj.get('type')
    content_ = obj.get('content')
    if type_ == 'doc' and content_:
        return ''.join(decode_note_obj(x) for x in content_)
    elif type_ == 'paragraph':
        inlines = [decode_note_obj(x) for x in content_] if content_ else []
        inlines.append('\n')
        return ''.join(inlines)
    elif type_ in ('tab_list', 'ordered_list', 'bullet_list', 'check_list') and content_:
        item_content = []
        for i, x in enumerate(content_, start=1):
            item_content.append(decode_note_obj(x, type_, listlevel + 1, i))
        return "".join(item_content)
    elif type_ in ('list_item', 'check_list_item') and content_:
        item_content = ''.join(decode_note_obj(x) for x in content_)
        if listtype == 'tab_list':
            return " " * (indent_size*listlevel) + item_content
        elif listtype == 'ordered_list':
            return " " * (indent_size*(listlevel-1)) + str(listitem_cntr) + ". " + item_content
        elif listtype == 'bullet_list':
            return " " * (indent_size*(listlevel-1)) + "* " + item_content
        elif listtype == 'check_list':
            checked = obj.get('attrs', {}).get('checked', False)
            checkbox = '[x] ' if checked else '[ ] '
            return " " * (indent_size*(listlevel-1)) + checkbox + item_content
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
    elif type_ == 'hard_break':
        return '\n'
    elif type_ == 'code_block':
        if not content_: return '\n'
        code_block_text = '\n'.join(decode_note_obj(x) for x in content_)
        buf = StringIO()
        if code_block_style == 'markdown':
            language = obj.get('attrs', {}).get('language')
            language = language.lower() if language else ''
            buf.write(f"```{language}\n")
            buf.write(code_block_text)
            buf.write("\n```\n")
        else:
            indent = ' ' * indent_size
            for line in code_block_text.splitlines(keepends=True):
                buf.write(indent + line)
            buf.write('\n')
        text = buf.getvalue()
        buf.close()
        return text
    elif type_ == 'heading':
        level = obj['attrs']['level']
        htext = ''.join(decode_note_obj(x) for x in content_) if content_ else ''
        return f"\n{'#' * level}  {htext}\n\n"
    elif type_ == 'horizontal_rule':
        return "\n-------------------\n\n"
    elif type_ == 'blockquote':
        quoted_text = '\n'.join(decode_note_obj(x) for x in content_)
        buf = StringIO()
        buf.write('\n')
        for line in quoted_text.splitlines(keepends=True):
            buf.write('> ' + line)
        buf.write('\n')
        text = buf.getvalue()
        buf.close()
        return text
    else:
        print(f"Unknown content type: '{type_}'", file=sys.stderr)
        return ""

def typography_repl_fn(matchobj):
    s = matchobj[0]
    if s in ['“', '”']:
        return '"'
    elif s == "’":
        return "'"
    elif s == "—":
        return '--'
    elif s == "\u00A0":
        return ' '
    else:
        return s

if __name__ == '__main__':
    import locale
    default_encoding = locale.getpreferredencoding();
    #
    cli_parser = argparse.ArgumentParser(description='Convert new-style Box Notes to text')
    cli_parser.add_argument('boxnote', help='Box Note JSON input file')
    cli_parser.add_argument('textfile', nargs='?', default='-',
            help='Text output file. If omitted or set to "-", we print text to stdout.')
    cli_parser.add_argument('-i', '--indent', metavar='n', type=int, default=3,
            help='Number of spaces per indent level')
    cli_parser.add_argument('-t', '--remove-typography', action='store_true',
            help='Remove "smart" typography (fancy quotes, dashes, etc.), replacing each '
                 'instance with its ASCII equivalent')
    cli_parser.add_argument('-s', '--strip-trailing-lines', action='store_true',
            help='Strip off trailing blank lines')
    cli_parser.add_argument('-m', '--markdown', action='store_true',
            help='Format (some) output as Markdown rather than plain text')
    cli_parser.add_argument('-e', '--input-encoding',
            help=f'Specify the text encoding of the JSON input file (default "{default_encoding}")')
    cli_parser.add_argument('-E', '--output-encoding',
            help=f'Specify the text encoding of the output file (default "{default_encoding}")')
    options = cli_parser.parse_args()
    #
    notefile = options.boxnote
    textfile = options.textfile
    indent_size = options.indent
    remove_typography = options.remove_typography
    strip_trailing = options.strip_trailing_lines
    code_block_style = 'markdown' if options.markdown else 'text'
    input_encoding = options.input_encoding
    output_encoding = options.output_encoding
    #
    with open(notefile, "rt", encoding=input_encoding) as f:
        notejson = json.load(f)
    #
    text = decode_note_obj(notejson['doc'])
    if strip_trailing:
        text = text.rstrip() + '\n'
    if remove_typography:
        text = re.sub(r"[“”’—\u00A0]", typography_repl_fn, text)
    #
    if textfile == '-':
        print(text, end='')
    else:
        with open(textfile, "wt", encoding=output_encoding) as f:
            f.write(text)
