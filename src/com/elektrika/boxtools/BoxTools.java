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
import java.util.Properties;

public final class BoxTools
{
    public static void main(String[] args) throws IOException {
        if (args.length == 0)
            showHelpAndExit();

        Utils.initSimpleLogging("com.elektrika.boxtools.BoxTools");
        switch (args[0]) {
        case "-extract":
            extractBoxNoteText(args, args.length - 1, 1);
            break;
        case "-download":
            downloadFile(args, args.length - 1, 1);
            break;
        case "-upload":
            uploadFile(args, args.length - 1, 1);
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
            "   -extract <filename.boxnote> <filename.txt>\n" +
            "   -download <FTP properties file> <remote path> <local path>\n" +
            "   -upload <FTP properties file> <local path> <remote dir>"
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

    private static void downloadFile(String[] args, int numArgs, int argsStart) throws IOException {
        if (numArgs != 3)
            showHelpAndExit();
        final Path propsPath = Paths.get(args[argsStart++]);
        final Path remotePath = Paths.get(args[argsStart++]);
        final Path localPath = Paths.get(args[argsStart++]);

        final Properties props = Utils.loadProps(propsPath);
        FTP ftp = new FTP(props);
        System.out.println("Connecting...");
        ftp.connect();
        System.out.println("Downloading...");
        ftp.downloadFile(remotePath, localPath);
        System.out.println("Disconnecting...");
        ftp.disconnect();
    }

    private static void uploadFile(String[] args, int numArgs, int argsStart) throws IOException {
        if (numArgs != 3)
            showHelpAndExit();
        final Path propsPath = Paths.get(args[argsStart++]);
        final Path localPath = Paths.get(args[argsStart++]);
        final Path remoteDir = Paths.get(args[argsStart++]);

        final Properties props = Utils.loadProps(propsPath);
        FTP ftp = new FTP(props);
        System.out.println("Connecting...");
        ftp.connect();
        System.out.println("Uploading...");
        ftp.uploadFile(localPath, remoteDir);
        System.out.println("Disconnecting...");
        ftp.disconnect();
    }
}
