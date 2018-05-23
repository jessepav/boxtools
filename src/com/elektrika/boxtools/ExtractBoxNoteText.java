package com.elektrika.boxtools;

import com.github.cliftonlabs.json_simple.JsonException;
import com.github.cliftonlabs.json_simple.JsonKey;
import com.github.cliftonlabs.json_simple.JsonObject;
import com.github.cliftonlabs.json_simple.Jsoner;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public class ExtractBoxNoteText
{
    public static void main(String[] args) throws IOException, JsonException {
        if (args.length != 2) {
            System.out.println(
                "Usage: \n" +
                "   ExtractBoxNoteText <filename.boxnote> <filename.txt>");
            System.exit(1);
        }
        Path inPath = Paths.get(args[0]);
        Path outPath = Paths.get(args[1]);

        JsonObject obj = loadJsonObject(inPath);
        String text = ((JsonObject) obj.getMap(jk("atext"))).getString(jk("text"));
        Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));

        System.exit(0);
    }

    /** Mints a JsonKey from a String (with no default value) for use with the various JsonObject methods */
    public static JsonKey jk(String key) {
        return Jsoner.mintJsonKey(key, null);
    }

    /** Reads a JsonObject from a given path; returns null on error */
    public static JsonObject loadJsonObject(Path p) throws JsonException, IOException {
        JsonObject jo;
        try (Reader r = new BufferedReader(new InputStreamReader(Files.newInputStream(p), StandardCharsets.UTF_8))) {
            jo = (JsonObject) Jsoner.deserialize(r);
        }
        return jo;
    }

}
