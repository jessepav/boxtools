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
    private static Config config;

    public static void main(String[] args) throws IOException, URISyntaxException, InterruptedException {
        if (args.length < 2)
            showHelpAndExit();

        Utils.initSimpleLogging("com.elektrika.boxtools.BoxTools");

        config = new Config();

        final LinkedList<String> argsList = new LinkedList<>(Arrays.asList(args));
        config.propsPath = Paths.get(argsList.removeFirst());
        config.props = Utils.loadProps(config.propsPath);
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
            "Usage: BoxTools <config properties file> <command> [args]\n\n" +
            "Commands:\n\n" +
            "   -extract <filename.boxnote> <filename.txt>\n" +
            "   -oauth\n" +
            "   -list <folder ID>\n" +
            "   -get <file ID> [<file ID> ...] <local dir>\n" +
            "   -put version <file ID> <local file> [<file ID> <local file> ...]\n" +
            "                                folder <folder ID> <local file> [<local file> ...]\n" +
            "   -rename file|folder <file or folder ID> <new name>\n" +
            "\n" +
            " Use '/' as folder ID to indicate root folder."
        );
        System.exit(1);
    }

    // -extract <filename.boxnote> <filename.txt>
    //
    private static void extractBoxNoteText(LinkedList<String> args) throws IOException {
        if (args.size() != 2)
            showHelpAndExit();

        final Path inPath = Paths.get(args.removeFirst());
        final Path outPath = Paths.get(args.removeFirst());
        final JsonObject obj = Json.parse(new InputStreamReader(Files.newInputStream(inPath), StandardCharsets.UTF_8)).asObject();
        final BoxNote note = new BoxNote(obj);
        final int spaces = Utils.parseInt(config.props.getProperty("list-indent-spaces"), -1);
        if (spaces != -1)
            note.setSpacesPerIndentLevel(spaces);
        final String text = note.getFormattedText();
        Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
    }

    // -oauth
    //
    private static void retrieveOAuthCode(LinkedList<String> args) throws IOException, URISyntaxException {
        BoxAuth auth = new BoxAuth(config);
        auth.retrieveOAuthTokens();
        System.out.println("Tokens retrieved.");
    }

    // -list <folder ID>
    //
    private static void boxList(LinkedList<String> args) throws IOException {
        if (args.size() != 1)
            showHelpAndExit();

        final String id = args.removeFirst();
        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.listFolder(id);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // -get <file ID> [<file ID> ...] <local dir>
    //
    private static void boxGet(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final Path localDir = Paths.get(args.removeLast());
        final List<String> fileIds = args;

        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            for (String id : fileIds)
                System.out.println("Retrieved: " + ops.getFile(id, localDir));
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // -put version <file ID> <local file> [<file ID> <local file> ...]
    //       folder <folder ID> <local file> [<local file> ...]
    //
    private static void boxPut(LinkedList<String> args) throws IOException, InterruptedException {
        if (args.size() < 3)
            showHelpAndExit();

        BoxAuth auth;
        BoxOperations ops;

        switch (args.removeFirst()) {
        case "version":
            auth = new BoxAuth(config);
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
            auth = new BoxAuth(config);
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

    // -rename file|folder <file or folder ID> <new name>
    //
    private static void boxRename(LinkedList<String> args) throws IOException {
        if (args.size() != 3)
            showHelpAndExit();

        final String itemType = args.removeFirst();
        final String id = args.removeFirst();
        final String newName = args.removeFirst();

        boolean isFolder;
        switch (itemType) {
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

        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            String oldName = ops.rename(id, isFolder, newName);
            System.out.printf("Rename %s: %s -> %s\n", itemType, oldName, newName);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    public static class Config
    {
        public Properties props;
        public Path propsPath;
    }
}
