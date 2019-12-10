package com.elektrika.boxtools;

import com.eclipsesource.json.JsonObject;

/**
 * A class that handles the conversion of Box Notes to text. The only attributes that it takes into
 * account are lists, so that list numbers and bullets are not lost, as they are if you select-all and
 * copy-paste out of the Box web app.
 * <hr/>
 * <b>Box Note JSON format</b>
 * <pre>{@code
I learn all this from

  https://github.com/alexwennerberg/boxnotes2html/blob/master/boxnotes2html/boxnote.py

  An attribute chunk is formatted like this:

    *n[*n...]+n[|n+n]
        eg
    *4*1+1|+1
    where *n refers to an attribute to apply from the attribute pool
    and +n is a number of characters to apply that attribute to
    and |n is indicative of a line break (unclear the purpose of this)

  All numbers 'n' are encoded as base-36 integers (i.e. [0-9a-z])
  Note that a chunk may have no attributes, and can just be a character/line span, ex. "|1+1".

Here is a regex that matches a single chunk:

  ((?:\*\w+)*)(?:\|\w+)?(\+\w+)

  $1 = attributes (if any), including the *'s
  $2 = number of characters, including the +

In the .boxnote JSON, the various keys of concern are:

  "atext"->"text": the text itself
  "atext"->"attribs": the attribute chunks
  "pool"->"numToAttrib": mapping from attribute numbers to styles

 * }</pre>
 * <hr/>
 */
public class BoxNote
{
    private JsonObject noteObj;

    public BoxNote(JsonObject noteObj) {
        this.noteObj = noteObj;
    }

    public String getPlainText() {
        return noteObj.get("atext").asObject().get("text").asString();
    }

    public String getFormattedText() {
        final String text = getPlainText();
        return null;
    }
}
