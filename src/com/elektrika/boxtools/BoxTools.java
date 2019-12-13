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
import java.util.Arrays;
import java.util.LinkedList;
import java.util.Properties;

public final class BoxTools
{
    public static void main(String[] args) throws IOException {
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
            "   -upload <FTP properties file> <local path> <remote dir> [<local path> <remote dir>] ..."
        );
        System.exit(1);
    }

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
}
