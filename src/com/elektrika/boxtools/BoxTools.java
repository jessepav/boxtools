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
        case "-download":
            downloadFile(argsList);
            break;
        case "-upload":
            uploadFile(argsList);
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
            "   -download <FTP properties file> <remote path> [<local path>]\n" +
            "   -download <FTP properties file> <remote path> <local path> [<remote path> <local path>] ...\n" +
            "   -upload <FTP properties file> <local path> <remote dir> [<local path> <remote dir>] ...\n" +
            "   -oauth <OAuth properties file>\n" +
            "   -list <OAuth properties file> <folder ID>\n" +
            "   -get <OAuth properties file> <file ID> [<file ID> ...] <local dir>\n" +
            "   -put <OAuth properties file> version <file ID> <local file> [<file ID> <local file> ...]\n" +
            "                                folder <folder ID> <local file> [<local file> ...]\n" +
            "   -rename <OAuth properties file> file|folder <file or folder ID> <new name>"
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

    private static void downloadFile(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final Properties props = Utils.loadProps(propsPath);
        final FTP ftp = new FTP(props);
        System.out.println("Connecting...");
        ftp.connect();
        try {
            System.out.println("Downloading...");
            while (!args.isEmpty()) {
                final Path remotePath = Paths.get(args.removeFirst());
                final Path localPath = args.isEmpty() ? remotePath.getFileName() : Paths.get(args.removeFirst());
                ftp.downloadFile(remotePath, localPath);
            }
        } finally {
            System.out.println("Disconnecting...");
            ftp.disconnect();
        }
    }

    private static void uploadFile(LinkedList<String> args) throws IOException {
        if (args.size() < 3 || args.size() % 2 != 1)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final Properties props = Utils.loadProps(propsPath);
        final FTP ftp = new FTP(props);
        System.out.println("Connecting...");
        ftp.connect();
        try {
            System.out.println("Uploading...");
            while (!args.isEmpty()) {
                final Path localPath = Paths.get(args.removeFirst());
                final Path remoteDir = Paths.get(args.removeFirst());
                ftp.uploadFile(localPath, remoteDir);
            }
        } finally {
            System.out.println("Disconnecting...");
            ftp.disconnect();
        }
    }

    // -oauth <OAuth properties file>
    //
    private static void retrieveOAuthCode(LinkedList<String> args) throws IOException, URISyntaxException {
        final Path propsPath = Paths.get(args.removeFirst());
        final Properties props = Utils.loadProps(propsPath);
        BoxOAuth oauth = new BoxOAuth(props, propsPath);
        oauth.retrieveTokens();
        System.out.println("Tokens retrieved.");
    }

    // -list <OAuth properties file> <folder ID>
    //
    private static void boxList(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final String id = args.removeFirst();
        BoxOperations ops = new BoxOperations(BoxOAuth.createAPIConnection(propsPath));
        try {
            ops.listFolder(id);
        } finally {
            BoxOAuth.saveTokens(propsPath, ops.getApiConnection());
        }
    }

    // -get <OAuth properties file> <file ID> [<file ID> ...] <local dir>
    //
    private static void boxGet(LinkedList<String> args) throws IOException {
        if (args.size() < 3)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        final Path localDir = Paths.get(args.removeLast());
        final List<String> fileIds = args;

        BoxOperations ops = new BoxOperations(BoxOAuth.createAPIConnection(propsPath));
        try {
            for (String id : fileIds)
                System.out.println("Retrieved: " + ops.getFile(id, localDir));
        } finally {
            BoxOAuth.saveTokens(propsPath, ops.getApiConnection());
        }
    }

    // -put <OAuth properties file> version <file ID> <local file> [<file ID> <local file> ...]
    //                              folder <folder ID> <local file> [<local file> ...]
    //
    private static void boxPut(LinkedList<String> args) throws IOException, InterruptedException {
        if (args.size() < 4)
            showHelpAndExit();

        final Path propsPath = Paths.get(args.removeFirst());
        BoxOperations ops;

        switch (args.removeFirst()) {
        case "version":
            ops = new BoxOperations(BoxOAuth.createAPIConnection(propsPath));
            try {
                while (args.size() >= 2) {
                    final String id = args.removeFirst();
                    final Path localPath = Paths.get(args.removeFirst());
                    System.out.println("Uploaded: " + ops.putVersion(id, localPath));
                }
            } finally {
                BoxOAuth.saveTokens(propsPath, ops.getApiConnection());
            }
            break;
        case "folder":
            ops = new BoxOperations(BoxOAuth.createAPIConnection(propsPath));
            try {
                final String id = args.removeFirst();
                final List<Path> localPaths = new ArrayList<>(args.size());
                for (String name : args)
                    localPaths.add(Paths.get(name));
                final String name = ops.putFolder(id, localPaths);
                System.out.printf("Uploaded %d files to folder: %s\n", localPaths.size(), name);
            } finally {
                BoxOAuth.saveTokens(propsPath, ops.getApiConnection());
            }
            break;
        default:
            showHelpAndExit();
            break;
        }
    }

    // -rename <OAuth properties file> file|folder <file or folder ID> <new name>
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

        BoxOperations ops = new BoxOperations(BoxOAuth.createAPIConnection(propsPath));
        try {
            String oldName = ops.rename(id, isFolder, newName);
            System.out.printf("Rename %s: %s -> %s\n", command, oldName, newName);
        } finally {
            BoxOAuth.saveTokens(propsPath, ops.getApiConnection());
        }
    }
}
