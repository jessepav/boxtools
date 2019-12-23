package com.elektrika.boxtools;

import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonObject;
import org.apache.commons.codec.binary.Base64;
import org.apache.commons.lang3.StringUtils;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.apache.commons.lang3.StringUtils.startsWith;

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
    private int spacesPerIndentLevel;
    private boolean bomFound;

    private JsonObject noteObj;

    public BoxNote() {
        spacesPerIndentLevel = 3;
    }

    public BoxNote(JsonObject noteObj) {
        this();
        this.noteObj = noteObj;
    }

    public void setNoteObj(JsonObject noteObj) {
        this.noteObj = noteObj;
        bomFound = false;
    }

    public void setSpacesPerIndentLevel(int spacesPerIndentLevel) {
        this.spacesPerIndentLevel = spacesPerIndentLevel;
    }

    public String getRawText() {
        final String s = noteObj.get("atext").asObject().get("text").asString();
        if (s.codePointAt(0) == 0xFEFF)  // Unicode byte-order mark
            bomFound = true;
        return s;
    }

    public String getFormattedText() {
        final Map<Integer,Attribute> attributeMap = getAttributeMap();
        final List<AttributeChunk> chunks = getAttributeChunks(attributeMap);
        final String text = getRawText();
        final String ftext = formatText(text, chunks);
        return ftext;
    }

    private String formatText(String text, List<AttributeChunk> chunks) {
        final StringBuilder sb = new StringBuilder(text.length() * 6 / 5);

        int n = 0;  // position in text
        int listNum = 1;
        List<String> urls = new ArrayList<>();
        int runningUrlNo = 0;
        for (AttributeChunk chunk : chunks) {
            if (n == 0 && bomFound && chunk.numChars == 1) {
                n = 1;
                continue;  // don't write out the BOM
            }
            int numberedListLevel = 0;
            int bulletedListLevel = 0;
            int indentLevel = 0;
            int urlNo = 0;
            for (Attribute attr : chunk.attributes) {
                if (attr.startListNumbering != 0)
                    listNum = attr.startListNumbering;
                else if (attr.numberedListLevel != 0)
                    numberedListLevel = attr.numberedListLevel;
                else if (attr.bulletedListLevel != 0)
                    bulletedListLevel = attr.bulletedListLevel;
                else if (attr.indentLevel != 0)
                    indentLevel = attr.indentLevel;
                else if (attr.url != null) {
                    if (attr.urlNo == 0) {
                        urls.add(attr.url);
                        attr.urlNo = urls.size();
                    }
                    urlNo = attr.urlNo;
                }
            }
            if (urlNo != runningUrlNo) {
                if (runningUrlNo != 0)
                    sb.append(" [").append(runningUrlNo).append("]");
                runningUrlNo = urlNo;
            }
            if (numberedListLevel != 0) {
                insertIndent(sb, numberedListLevel - 1);
                formatNumberedListItem(sb, listNum++, numberedListLevel);
                sb.append(". ");
            } else if (bulletedListLevel != 0) {
                insertIndent(sb, bulletedListLevel - 1);
                formatBulletedListItem(sb, bulletedListLevel);
                sb.append(" ");
            } else if (indentLevel != 0) {
                insertIndent(sb, indentLevel);
            } else {
                sb.append(text.substring(n, n + chunk.numChars));
            }
            n += chunk.numChars;
        }
        if (runningUrlNo != 0)
            sb.append(" [").append(runningUrlNo).append("]");

        if (!urls.isEmpty()) {
            sb.append('\n');
            int urlNo = 1;
            for (String url : urls)
                sb.append('[').append(urlNo++).append("] ").append(url).append('\n');
        }
        return sb.toString();
    }

    private void formatNumberedListItem(StringBuilder sb, int listNum, int numberedListLevel) {
        if (listNum <= 0) {
            sb.append(listNum);
            return;
        }
        switch ((numberedListLevel - 1) % 3) {
        case 0:  // normal decimal numbers
            sb.append(listNum);
            break;
        case 1: // a..z, aa, ab, etc.
            if (listNum <= 702) {
                if (listNum > 26)
                    sb.append((char) ('a' + listNum / 26 - 1));
                sb.append((char) ('a' + (listNum-1) % 26));
            } else {
                sb.append(listNum);
            }
            break;
        case 2: // lowercase roman numerals
            if (listNum <= 3999) {
                sb.append(RomanNumerals.format(listNum).toLowerCase());
            } else {
                sb.append(listNum);
            }
            break;
        }
    }

    private static char[] BULLETS = {'*', '+', '-'};

    private void formatBulletedListItem(StringBuilder sb, int bulletedListLevel) {
        sb.append(BULLETS[(bulletedListLevel - 1) % 3]);
    }

    private void insertIndent(StringBuilder sb, int indentLevel) {
        if (indentLevel > 0)
            sb.append(StringUtils.repeat(' ', indentLevel * spacesPerIndentLevel));
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
                    attr.numberedListLevel = Utils.parseInt(val2.substring(6));
                else if (startsWith(val2, "bullet"))
                    attr.bulletedListLevel = Utils.parseInt(val2.substring(6));
                else if (startsWith(val2, "indent"))
                    attr.indentLevel = Utils.parseInt(val2.substring(6));
            } else if (val1.equals("start")) {
                attr.startListNumbering = Utils.parseInt(val2);
            } else if (startsWith(val1, "link-")) {
                attr.url = StringUtils.split(new String(Base64.decodeBase64(val1.substring(5)), StandardCharsets.UTF_8), '-')[1];
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
        public int numberedListLevel;
        public int bulletedListLevel;
        public int indentLevel;
        public int startListNumbering;
        public String url;
        public int urlNo;
    }
}
