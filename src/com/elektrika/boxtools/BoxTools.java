package com.elektrika.boxtools;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonObject;

import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

public final class BoxTools
{
    public static void main(String[] args) throws IOException, URISyntaxException, InterruptedException {
        if (args.length == 0)
            showHelpAndExit();

        Utils.initSimpleLogging("com.elektrika.boxtools.BoxTools");

        final LinkedList<String> argsList = new LinkedList<>(Arrays.asList(args));
        final String cmd = argsList.removeFirst();

        switch (cmd) {
        case "-extract":
            extractBoxNoteText(argsList);
            break;
        case "-oauth":
            retrieveOAuthCode(argsList);
            break;
        case "-list":
            boxList(argsList);
            break;
        case "-get":
            boxGet(argsList);
            break;
        case "-put":
            boxPut(argsList);
            break;
        case "-rename":
            boxRename(argsList);
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
            "   -extract [-s spaces-per-indent-level] <filename.boxnote> <filename.txt>\n" +
            "   -oauth <auth properties file>\n" +
            "   -list <auth properties file> <folder ID>   (use '/' as folder ID to list root folder)\n" +
            "   -get <auth properties file> <file ID> [<file ID> ...] <local dir>\n" +
            "   -put <auth properties file> version <file ID> <local file> [<file ID> <local file> ...]\n" +
            "                                folder <folder ID> <local file> [<local file> ...]\n" +
            "   -rename <auth properties file> file|folder <file or folder ID> <new name>"
        );
        System.exit(1);
    }

    // -extract [-s spaces-per-indent-level] <filename.boxnote> <filename.txt>
    //
    private static void extractBoxNoteText(LinkedList<String> args) throws IOException {
        int spacesPerIndentLevel = 0;

        while (args.size() > 2) {
            String opt = args.removeFirst();
            switch (opt) {
            case "-s":
                spacesPerIndentLevel = Utils.parseInt(args.removeFirst());
                break;
            }
        }

        if (args.size() != 2)
            showHelpAndExit();

        final Path inPath = Paths.get(args.removeFirst());
        final Path outPath = Paths.get(args.removeFirst());
        final JsonObject obj = Json.parse(new InputStreamReader(Files.newInputStream(inPath), StandardCharsets.UTF_8)).asObject();
        final BoxNote note = new BoxNote(obj);
        if (spacesPerIndentLevel != 0)
            note.setSpacesPerIndentLevel(spacesPerIndentLevel);
        final String text = note.getFormattedText();
        Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
    }

    // -oauth <auth properties file>
    //
    private static void retrieveOAuthCode(LinkedList<String> args) throws IOException, URISyntaxException {
        final Path propsPath = Paths.get(args.removeFirst());
        BoxAuth auth = new BoxAuth(propsPath);
        auth.retrieveOAuthTokens();
        System.out.println("Tokens retrieved.");
    }

    // -list <auth properties file> <folder ID>
    //
    private static void boxList(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final String id = args.removeFirst();
        BoxAuth auth = new BoxAuth(propsPath);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.listFolder(id);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // -get <auth properties file> <file ID> [<file ID> ...] <local dir>
    //
    private static void boxGet(LinkedList<String> args) throws IOException {
        if (args.size() < 3)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final Path localDir = Paths.get(args.removeLast());
        final List<String> fileIds = args;

        BoxAuth auth = new BoxAuth(propsPath);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            for (String id : fileIds)
                System.out.println("Retrieved: " + ops.getFile(id, localDir));
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // -put <auth properties file> version <file ID> <local file> [<file ID> <local file> ...]
    //                              folder <folder ID> <local file> [<local file> ...]
    //
    private static void boxPut(LinkedList<String> args) throws IOException, InterruptedException {
        if (args.size() < 4)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        BoxAuth auth;
        BoxOperations ops;

        switch (args.removeFirst()) {
        case "version":
            auth = new BoxAuth(propsPath);
            ops = new BoxOperations(auth.createAPIConnection());
            try {
                while (args.size() >= 2) {
                    final String id = args.removeFirst();
                    final Path localPath = Paths.get(args.removeFirst());
                    System.out.println("Uploaded: " + ops.putVersion(id, localPath));
                }
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
            break;
        case "folder":
            auth = new BoxAuth(propsPath);
            ops = new BoxOperations(auth.createAPIConnection());
            try {
                final String id = args.removeFirst();
                final List<Path> localPaths = new ArrayList<>(args.size());
                for (String name : args)
                    localPaths.add(Paths.get(name));
                final String name = ops.putFolder(id, localPaths);
                System.out.printf("Uploaded %d files to folder: %s\n", localPaths.size(), name);
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
            break;
        default:
            showHelpAndExit();
            break;
        }
    }

    // -rename <auth properties file> file|folder <file or folder ID> <new name>
    //
    private static void boxRename(LinkedList<String> args) throws IOException {
        if (args.size() != 4)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final String command = args.removeFirst();
        final String id = args.removeFirst();
        final String newName = args.removeFirst();

        boolean isFolder;
        switch (command) {
        case "file":
            isFolder = false;
            break;
        case "folder":
            isFolder = true;
            break;
        default:
            showHelpAndExit();
            return;
        }

        BoxAuth auth = new BoxAuth(propsPath);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            String oldName = ops.rename(id, isFolder, newName);
            System.out.printf("Rename %s: %s -> %s\n", command, oldName, newName);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }
}
