#!/usr/bin/env python3

import sys, os.path, json, argparse

indent_size = 2

def decode_note_obj(obj):
    type_ = obj.get('type')
    content_ = obj.get('content')


if __name__ == '__main__':
    cli_parser = argparse.ArgumentParser(description='Convert new-style Box Notes to text')
    cli_parser.add_argument('boxnote', help='Box Note JSON input file')
    cli_parser.add_argument('textfile', help='Text output file')
    options = cli_parser.parse_args()

    notefile = options.boxnote
    textfile = options.textfile

    with open(notefile, "rt") as f:
        notejson = json.load(f)

    doc_content = notejson['doc']['content']
