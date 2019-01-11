package com.elektrika.boxtools;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonObject;

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
    public static void main(String[] args) throws IOException {
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

    private static void extractBoxNoteText(String[] args, int numArgs, int argsStart) throws IOException {
        if (numArgs != 2)
            showHelpAndExit();

        Path inPath = Paths.get(args[argsStart++]);
        Path outPath = Paths.get(args[argsStart++]);

        JsonObject obj = Json.parse(new InputStreamReader(Files.newInputStream(inPath), StandardCharsets.UTF_8)).asObject();
        String text = obj.get("atext").asObject().get("text").asString();
        Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
    }
}
