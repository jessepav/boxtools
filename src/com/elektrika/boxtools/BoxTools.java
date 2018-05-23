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

public class BoxTools
{
    public static void main(String[] args) throws IOException, JsonException {
        if (args.length == 0)
            showHelpAndExit();

        switch (args[0]) {
        case "-extract":
            extractBoxNoteText(args, args.length - 1, 1);
            break;
        default:
            showHelpAndExit();
        }
        System.exit(0);
    }

    private static void showHelpAndExit() {
        System.out.println(
            "Usage: BoxTools <command> [args]\n\n" +
            "Commands:\n" +
            "   -extract <filename.boxnote> <filename.txt>"
        );
        System.exit(1);
    }

    private static void extractBoxNoteText(String[] args, int numArgs, int argsStart)
                throws JsonException, IOException {
        if (numArgs != 2)
            showHelpAndExit();

        Path inPath = Paths.get(args[argsStart++]);
        Path outPath = Paths.get(args[argsStart++]);
        JsonObject obj = loadJsonObject(inPath);
        String text = ((JsonObject) obj.getMap(jk("atext"))).getString(jk("text"));
        Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
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
