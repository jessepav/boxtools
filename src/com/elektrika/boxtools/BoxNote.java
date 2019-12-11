package com.elektrika.boxtools;

import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonObject;
import org.apache.commons.lang3.StringUtils;

import static org.apache.commons.lang3.StringUtils.startsWith;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * A class that handles the conversion of Box Notes to text. The only attributes that it takes into
 * account are lists, so that list numbers, bullets, and indentation are not lost, as they are if you
 * select-all and copy-paste out of the Box web app.
 * <hr/>
 * <b>Box Note JSON format</b>
 * <pre>{@code
I learn (mostly) all of this from

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
    public static final int SPACES_PER_INDENT_LEVEL = 3;

    private JsonObject noteObj;

    public BoxNote(JsonObject noteObj) {
        this.noteObj = noteObj;
    }

    public String getRawText() {
        return noteObj.get("atext").asObject().get("text").asString();
    }

    public String getFormattedText() {
        final String text = getRawText();
        final Map<Integer,Attribute> attributeMap = getAttributeMap();
        final List<AttributeChunk> chunks = getAttributeChunks(attributeMap);
        final String ftext = formatText(text, chunks);
        return ftext;
    }

    private String formatText(String text, List<AttributeChunk> chunks) {
        final StringBuilder sb = new StringBuilder(text.length() * 6 / 5);

        int n = 0;  // position in text
        int listNum = 1;
        for (AttributeChunk chunk : chunks) {
            boolean numberedList = false;
            boolean bulletedList = false;
            int indentLevel = 0;
            for (Attribute attr : chunk.attributes) {
                if (attr.startListNumbering != 0)
                    listNum = attr.startListNumbering;
                else if (attr.numberedList)
                    numberedList = true;
                else if (attr.bulletedList)
                    bulletedList = true;
                else if (attr.indentLevel != 0)
                    indentLevel = attr.indentLevel;
            }
            if (numberedList)
                sb.append(String.format("%d. ", listNum++));
            else if (bulletedList)
                sb.append("* ");
            else if (indentLevel != 0)
                sb.append(StringUtils.repeat(' ', indentLevel * SPACES_PER_INDENT_LEVEL));
            else
                sb.append(text.substring(n, n + chunk.numChars));
            n += chunk.numChars;
        }
        return sb.toString();
    }

    private Map<Integer,Attribute> getAttributeMap() {
        final Map<Integer,Attribute> map = new HashMap<>();
        JsonObject attribPool = noteObj.get("pool").asObject().get("numToAttrib").asObject();
        for (JsonObject.Member member : attribPool) {
            int num = Integer.parseInt(member.getName());
            JsonArray val = member.getValue().asArray();
            String val1 = val.get(0).asString();
            String val2 = null;
            if (val.size() > 1)
                val2 = val.get(1).asString();
            boolean recognized = true;
            Attribute attr = new Attribute();
            if (val1.equals("list")) {
                if (startsWith(val2, "number"))
                    attr.numberedList = true;
                else if (startsWith(val2, "bullet"))
                    attr.bulletedList = true;
                else if (startsWith(val2, "indent"))
                    attr.indentLevel = Integer.valueOf(val2.substring(6));
            } else if (val1.equals("start")) {
                attr.startListNumbering = Integer.parseInt(val2);
            } else {
                recognized = false;
            }
            if (recognized)
                map.put(num, attr);
        }
        return map;
    }

    private List<AttributeChunk> getAttributeChunks(final Map<Integer,Attribute> attributeMap) {
        List<AttributeChunk> chunks = new ArrayList<>(256);
        String attribsStr = noteObj.get("atext").asObject().get("attribs").asString();
        Pattern p = Pattern.compile("((?:\\*\\w+)*)(?:\\|\\w+)?(\\+\\w+)");
        Matcher m = p.matcher(attribsStr);
        while (m.find()) {
            AttributeChunk ac = new AttributeChunk();
            ac.numChars = Integer.parseInt(m.group(2).substring(1), 36);
            String[] attribNums = StringUtils.split(m.group(1), '*');
            if (attribNums != null) {
                for (String s : attribNums) {
                    if (!s.isEmpty()) {
                        Attribute attr = attributeMap.get(Integer.parseInt(s, 36));
                        if (attr != null)
                            ac.attributes.add(attr);
                    }
                }
            }
            chunks.add(ac);
        }
        return chunks;
    }

    public static class AttributeChunk
    {
        public int numChars;
        List<Attribute> attributes;

        public AttributeChunk() {
            attributes = new ArrayList<>();
        }
    }

    public static class Attribute
    {
        public boolean numberedList;
        public boolean bulletedList;
        public int startListNumbering;
        public int indentLevel;
    }
}
