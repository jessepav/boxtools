package com.elektrika.boxtools;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonObject;
import org.apache.commons.lang3.StringUtils;
import org.apache.commons.lang3.tuple.Pair;
import org.apache.commons.lang3.tuple.Triple;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

public final class BoxTools
{
    private static Config config;

    private static void showHelpAndExit() {
        System.out.println(
            "Usage: BoxTools <config properties file> <command> [args]\n" +
                "\n" +
                "Commands:\n" +
                "\n" +
                "   extract <filename.boxnote> <filename.txt> [<filename.boxnote> <filename.txt> ...]\n" +
                "   oauth\n" +
                "   list <folder ID> [<folder ID> ...]\n" +
                "   showpath [terse] file|folder <ID> [<ID> ...]\n" +
                "   path file|folder <ID> [<ID> ...] (terse implied)\n" +
                "   get <file ID> [<file ID> ...] <local dir>\n" +
                "   put version <file ID> <local file> [<file ID> <local file> ...]\n" +
                "   put folder <folder ID> <local file> [<local file> ...]\n" +
                "   newfolder <parent folder ID> <folder name>\n" +
                "   del file|folder <ID> [<ID> ...]\n" +
                "   link file|folder [remove] <ID> [<ID> ...]\n" +
                "   rename file|folder <file or folder ID> <new name>\n" +
                "   move file|folder <item ID> <destination folder ID>\n" +
                "   moveall <source folder ID> <destination folder ID> [<name match regex>]\n" +
                "   rget [norecurse] <folder ID> <local dir> [<name match regex>]\n" +
                "   rput [norecurse] <parent folder ID> <local dir> [<name match regex>]\n" +
                "   rdel <folder ID> <name match regex>\n" +
                "   notetext <note ID> <filename.txt|local dir> [<note ID> <filename.txt|local dir> ...]\n" +
                "   convertnote [folder <destination folder ID>] <note ID> [<note ID> ...]\n" +
                "   search [limit n] file|folder|web_link <item name>\n" +
                "\n" +
                " Use '0' as folder ID to indicate the root folder (aka \"All Files\").\n" +
                " For 'put folder', local files may use glob patterns '*', '?', etc."
        );
        System.exit(1);
    }

    public static void main(String[] args) throws IOException, URISyntaxException, InterruptedException {
        if (args.length < 2)
            showHelpAndExit();

        Utils.initSimpleLogging("com.elektrika.boxtools.BoxTools");

        final LinkedList<String> argsList = new LinkedList<>(Arrays.asList(args));
        config = new Config(Paths.get(argsList.removeFirst()));
        final String cmd = argsList.removeFirst();

        switch (cmd) {
        case "extract":
            extractBoxNoteText(argsList);
            break;
        case "oauth":
            retrieveOAuthCode(argsList);
            break;
        case "list":
            boxList(argsList);
            break;
        case "showpath":
        case "path":
            boxShowPath(argsList, cmd.equals("path"));
            break;
        case "get":
            boxGet(argsList);
            break;
        case "put":
            boxPut(argsList);
            break;
        case "newfolder":
            boxNewFolder(argsList);
            break;
        case "del":
            boxDelete(argsList);
            break;
        case "link":
            boxSharedLink(argsList);
            break;
        case "rename":
            boxRename(argsList);
            break;
        case "moveall":
            boxMoveAll(argsList);
            break;
        case "move":
            boxMove(argsList);
            break;
        case "rget":
            rget(argsList);
            break;
        case "rput":
            rput(argsList);
            break;
        case "rdel":
            rdel(argsList);
            break;
        case "notetext":
            retrieveBoxNoteText(argsList);
            break;
        case "convertnote":
            convertNoteToText(argsList);
            break;
        case "search":
            boxSearch(argsList);
            break;
        default:
            showHelpAndExit();
        }
        System.exit(0);
    }

    // extract <filename.boxnote> <filename.txt> [<filename.boxnote> <filename.txt> ...]
    //
    private static void extractBoxNoteText(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final int spaces = Utils.parseInt(config.props.getProperty("list-indent-spaces"), -1);

        while (args.size() >= 2) {
            final Path inPath = Paths.get(args.removeFirst());
            final Path outPath = Paths.get(args.removeFirst());
            final JsonObject obj = Json.parse(new InputStreamReader(Files.newInputStream(inPath), StandardCharsets.UTF_8)).asObject();
            final BoxNote note = new BoxNote(obj);
            if (spaces != -1)
                note.setSpacesPerIndentLevel(spaces);
            final String text = note.getFormattedText();
            Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
        }
    }

    // notetext <file ID> <filename.txt> [<file ID> <filename.txt> ...]
    //
    private static void retrieveBoxNoteText(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final int spaces = Utils.parseInt(config.props.getProperty("list-indent-spaces"), -1);
        final BoxAuth auth = new BoxAuth(config);
        final BoxOperations ops = new BoxOperations(auth.createAPIConnection());

        try {
            while (args.size() >= 2) {
                final String fileId = args.removeFirst();
                Path outPath = Paths.get(args.removeFirst());
                Path parent;
                if (Files.isDirectory(outPath)) {
                    parent = outPath;
                    String filename = ops.getFileName(fileId);
                    if (StringUtils.endsWithIgnoreCase(filename, ".boxnote"))
                        filename = filename.substring(0, filename.length() - 8) + ".txt";
                    outPath = parent.resolve(filename);
                } else {
                    parent = outPath.getParent();
                }
                if (parent == null)
                    parent = Paths.get("");
                final Path tmpFile = Files.createTempFile(parent, "boxtools-", ".boxnote");
                JsonObject obj;
                try {
                    ops.getFileDirect(config.getId(fileId), tmpFile);
                    obj = Json.parse(new InputStreamReader(Files.newInputStream(tmpFile), StandardCharsets.UTF_8)).asObject();
                } finally {
                    Files.delete(tmpFile);
                }
                final BoxNote note = new BoxNote(obj);
                if (spaces != -1)
                    note.setSpacesPerIndentLevel(spaces);
                final String text = note.getFormattedText();
                Files.write(outPath, text.getBytes(StandardCharsets.UTF_8));
                System.out.println("Box Note text written to: " + outPath.getFileName());
            }
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // convertnote [folder <destination folder ID>] <note ID> [<note ID> ...]
    //
    private static void convertNoteToText(LinkedList<String> args) throws IOException {
        String destFolderId = null;

        optargs:
        do {
            String flag = args.peekFirst();
            if (flag == null)
                break;
            switch (flag) {
            case "folder":
                args.removeFirst();  // pop off the flag
                destFolderId = args.removeFirst();
                break optargs;
            default:
                break optargs;
            }
        } while (true);

        final LinkedList<String> ids = args;
        if (ids.isEmpty())
            showHelpAndExit();

        int spaces = Utils.parseInt(config.props.getProperty("list-indent-spaces"), -1);

        final BoxAuth auth = new BoxAuth(config);
        final BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            for (String id : ids) {
                id = config.getId(id);
                String noteName = ops.getFileName(id);
                byte[] noteContent = ops.getFileContent(id);
                InputStreamReader reader = new InputStreamReader(new ByteArrayInputStream(noteContent), StandardCharsets.UTF_8);
                BoxNote note = new BoxNote(Json.parse(reader).asObject());
                if (spaces != -1)
                    note.setSpacesPerIndentLevel(spaces);
                byte[] textContent = note.getFormattedText().getBytes(StandardCharsets.UTF_8);
                String basename;
                int idx = noteName.lastIndexOf(".boxnote");
                if (idx != -1)
                    basename = noteName.substring(0, idx);
                else
                    basename = noteName;
                String textName = basename + ".txt";
                ops.uploadBytesToFolder(
                    destFolderId != null ? config.getId(destFolderId) : ops.getParentFolderId(id),
                    textContent, textName);
                System.out.printf("Saved text of '%s' to '%s'\n", noteName, textName);
            }
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // oauth
    //
    private static void retrieveOAuthCode(LinkedList<String> args) throws IOException, URISyntaxException {
        BoxAuth auth = new BoxAuth(config);
        auth.retrieveOAuthTokens();
        System.out.println("Tokens retrieved.");
    }

    // list <folder ID> [<folder ID> ...]
    //
    private static void boxList(LinkedList<String> args) throws IOException {
        if (args.size() < 1)
            showHelpAndExit();

        final List<String> folderIds = new ArrayList<>(args.size());
        for (String id : args)
            folderIds.add(config.getId(id));
        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.listFolders(folderIds);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // showpath [terse] file|folder <ID> [<ID> ...]
    //             path file|folder <ID> [<ID> ...]
    //
    private static void boxShowPath(LinkedList<String> args, boolean autoTerse) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        boolean terse = autoTerse;
        if (args.peekFirst().equals("terse")) {
            args.removeFirst();
            terse = true;
        }

        final String itemType = args.removeFirst();
        final boolean isFile = itemType.equals("file");
        final boolean isFolder = itemType.equals("folder");
        if (isFile || isFolder) {
            BoxAuth auth = new BoxAuth(config);
            BoxOperations ops = new BoxOperations(auth.createAPIConnection());
            try {
                for (String id : args) {
                    System.out.println();
                    ops.showPath(config.getId(id), isFolder, terse);
                }
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
        } else {
            showHelpAndExit();
        }
    }

    // get <file ID> [<file ID> ...] <local dir>
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
                System.out.println("Retrieved: " + ops.getFile(config.getId(id), localDir));
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // put version <file ID> <local file> [<file ID> <local file> ...]
    //     folder <folder ID> <local file> [<local file> ...]
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
                    System.out.println("Uploaded: " + ops.putVersion(config.getId(id), localPath));
                }
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
            break;
        case "folder":
            final String id = args.removeFirst();
            final List<Path> localPaths = new ArrayList<>();
            for (String name : args) {
                if (StringUtils.containsAny(name, '*', '?', '[', ']', '{', '}')) {
                    int lastSepIdx = StringUtils.lastIndexOfAny(name, "/", "\\");
                    String path, glob;
                    if (lastSepIdx != -1) {
                        path = name.substring(0, lastSepIdx);
                        glob = name.substring(lastSepIdx + 1, name.length());
                    } else {
                        path = "";
                        glob = name;
                    }
                    try (DirectoryStream<Path> dirStream = Files.newDirectoryStream(Paths.get(path), glob)) {
                        for (Path p : dirStream)
                            localPaths.add(p);
                    }
                } else {
                    localPaths.add(Paths.get(name));
                }
            }
            if (!localPaths.isEmpty()) {
                auth = new BoxAuth(config);
                ops = new BoxOperations(auth.createAPIConnection());
                try {
                    final String name = ops.putFolder(config.getId(id), localPaths, true);
                    System.out.printf("Uploaded %d files to folder: %s\n", localPaths.size(), name);
                } finally {
                    auth.saveTokens(ops.getApiConnection());
                }
            }
            break;
        default:
            showHelpAndExit();
            break;
        }
    }

    // newfolder <parent folder ID> <folder name>
    //
    private static void boxNewFolder(LinkedList<String> args) throws IOException {
        if (args.size() != 2)
            showHelpAndExit();
        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            String parentId = args.removeFirst();
            String name = args.removeFirst();
            Pair<String,String> info = ops.newFolder(config.getId(parentId), name);
            System.out.printf("Created folder \"%s\" [ %s ] in \"%s\"\n", name, info.getLeft(), info.getRight());
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // del file|folder <ID> [<ID> ...]
    //
    private static void boxDelete(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();

        final String itemType = args.removeFirst();
        final boolean isFile = itemType.equals("file");
        final boolean isFolder = itemType.equals("folder");
        if (isFile || isFolder) {
            BoxAuth auth = new BoxAuth(config);
            BoxOperations ops = new BoxOperations(auth.createAPIConnection());
            try {
                for (String id : args) {
                    if (isFile)
                        System.out.println("Deleted file: " + ops.deleteFile(config.getId(id)));
                    else
                        System.out.println("Deleted folder: " + ops.deleteFolder(config.getId(id), true));
                }
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
        } else {
            showHelpAndExit();
        }
    }

    // link file|folder [remove] <ID> [<ID> ...]
    //
    private static void boxSharedLink(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();
        final String itemType = args.removeFirst();
        final boolean isFile = itemType.equals("file");
        final boolean isFolder = itemType.equals("folder");
        if (isFile || isFolder) {
            BoxAuth auth = new BoxAuth(config);
            BoxOperations ops = new BoxOperations(auth.createAPIConnection());
            boolean remove = false;
            if (args.peekFirst().equals("remove")) {
                args.removeFirst();
                remove = true;
            }
            try {
                for (String id : args) {
                    Triple<String,String,String> linkInfo = ops.sharedLink(config.getId(id), isFolder, remove);
                    System.out.println("--" + (!isFolder ? "File: " : "Folder: ") + linkInfo.getLeft() + " --");
                    if (remove) {
                        System.out.println("  Link " + linkInfo.getMiddle());
                    } else {
                        System.out.println("  Shared: " + linkInfo.getMiddle());
                        if (!isFolder)
                            System.out.println("  Direct: " + linkInfo.getRight());
                    }
                }
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
        } else {
            showHelpAndExit();
        }
    }

    // rename file|folder <file or folder ID> <new name>
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
            String oldName = ops.rename(config.getId(id), isFolder, newName);
            System.out.printf("Rename %s: %s -> %s\n", itemType, oldName, newName);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // move file|folder <item ID> <destination folder ID>
    //
    private static void boxMove(LinkedList<String> args) throws IOException {
        if (args.size() < 3)
            showHelpAndExit();

        final String itemType = args.removeFirst();
        final boolean isFile = itemType.equals("file");
        final boolean isFolder = itemType.equals("folder");
        if (isFile || isFolder) {
            final String sourceId = args.removeFirst();
            final String destId = args.removeFirst();
            BoxAuth auth = new BoxAuth(config);
            BoxOperations ops = new BoxOperations(auth.createAPIConnection());
            try {
                Pair<String,String> names = ops.moveItem(isFolder, config.getId(sourceId), config.getId(destId));
                System.out.printf("Moved %s \"%s\" to folder \"%s\"",
                    isFile ? "file" : "folder", names.getLeft(), names.getRight());
            } finally {
                auth.saveTokens(ops.getApiConnection());
            }
        } else {
            showHelpAndExit();
        }
    }

    // moveall <source folder ID> <destination folder ID> [<name match regex>]
    //
    private static void boxMoveAll(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();
        final String sourceId = args.removeFirst();
        final String destId = args.removeFirst();
        final String regex = args.isEmpty() ? null : args.removeFirst();

        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.moveAll(config.getId(sourceId), config.getId(destId), regex, true);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // rget [norecurse] <folder ID> <local dir> [<name match regex>]
    //
    private static void rget(LinkedList<String> args) throws IOException {
        if (args.size() < 2)
            showHelpAndExit();
        boolean recurse = true;
        if (args.peekFirst().equals("norecurse")) {
            args.removeFirst();
            recurse = false;
        }
        final String folderId = args.removeFirst();
        final Path localDir = Paths.get(args.removeFirst());
        final String regex = args.isEmpty() ? null : args.removeFirst();
        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.rget(config.getId(folderId), localDir, regex, recurse, true);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // rput [norecurse] <parent folder ID> <local dir> [<name match regex>]
    //
    private static void rput(LinkedList<String> args) throws IOException, InterruptedException {
        if (args.size() < 2)
            showHelpAndExit();
        boolean recurse = true;
        if (args.peekFirst().equals("norecurse")) {
            args.removeFirst();
            recurse = false;
        }
        final String folderId = args.removeFirst();
        final Path localDir = Paths.get(args.removeFirst());
        final String regex = args.isEmpty() ? null : args.removeFirst();
        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.rput(config.getId(folderId), localDir, regex, recurse, true);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // rdel <folder ID> <name match regex>
    //
    private static void rdel(LinkedList<String> args) throws IOException {
        if (args.size() != 2)
            showHelpAndExit();
        final String folderId = args.removeFirst();
        final String regex = args.removeFirst();

        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            ops.rdel(config.getId(folderId), regex, true);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    // search [limit n] file|folder|web_link <item name>
    //
    private static void boxSearch(LinkedList<String> args) throws IOException {
        int limit = 10;

        optargs:
        do {
            String flag = args.peekFirst();
            if (flag == null)
                break;
            switch (flag) {
            case "limit":
                args.removeFirst();  // pop off the flag
                limit = Utils.parseInt(args.removeFirst(), 10);
                break optargs;
            default:
                break optargs;
            }
        } while (true);

        if (args.size() != 2)
            showHelpAndExit();

        final String type = args.removeFirst();
        if (!Arrays.asList("file", "folder", "web_link").contains(type))
            showHelpAndExit();
        final String query = args.removeFirst();

        BoxAuth auth = new BoxAuth(config);
        BoxOperations ops = new BoxOperations(auth.createAPIConnection());
        try {
            List<BoxOperations.SearchResult> sr = ops.searchName(query, type, limit);

            // Okay, okay, let's make the table look pretty
            int idLen = 12, nameLen = 12, parentNameLen = 12, parentIdLen = 12;
            for (BoxOperations.SearchResult r : sr) {
                idLen = Math.max(idLen, r.id.length());
                nameLen = Math.max(nameLen, r.name.length());
                parentNameLen = Math.max(parentNameLen, r.parentName.length());
                parentIdLen = Math.max(parentIdLen, r.parentId.length());
            }
            String fmt = String.format("%%-%ds  %%-%ds  %%-%ds  %%-%ds\n", idLen, nameLen, parentNameLen, parentIdLen);
            System.out.printf(fmt, "ID", StringUtils.capitalize(type) + " Name", "Parent", "Parent ID");
            System.out.println(StringUtils.repeat('-', idLen + nameLen + parentNameLen + parentIdLen + 3));
            for (BoxOperations.SearchResult r : sr)
                System.out.printf(fmt, r.id, r.name, r.parentName, r.parentId);
        } finally {
            auth.saveTokens(ops.getApiConnection());
        }
    }

    public static class Config
    {
        public Properties props;
        public Path propsPath;
        public Map<String,String> aliasMap;

        public Config(Path propsPath) throws IOException {
            this.propsPath = propsPath;
            this.props = Utils.loadProps(propsPath);
            loadAliases();
        }

        private void loadAliases() throws IOException {
            final String aliases = props.getProperty("id-aliases");
            if (aliases != null) {
                aliasMap = new HashMap<>();
                Properties aliasProps = Utils.loadProps(propsPath.resolveSibling(aliases));
                for (String name : aliasProps.stringPropertyNames())
                    aliasMap.put(name, aliasProps.getProperty(name));
            }
        }

        public String getId(String idOrAlias) {
            if (aliasMap == null)
                return idOrAlias;
            String id = aliasMap.get(idOrAlias);
            return id != null ? id : idOrAlias;
        }
    }
}
