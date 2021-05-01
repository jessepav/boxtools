package com.elektrika.boxtools;

import com.box.sdk.*;
import org.apache.commons.lang3.tuple.Pair;

import java.io.*;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class BoxOperations
{
    public static final long LARGE_FILE_THRESHOLD = 30_000_000L;

    private BoxAPIConnection api;
    private Map<String,Map<String,String>> folderContentIdCache;

    public BoxOperations(BoxAPIConnection api) {
        this.api = api;
        folderContentIdCache = new HashMap<>();
    }

    public BoxAPIConnection getApiConnection() {
        return api;
    }

    public void listFolders(List<String> ids) {
        for (String id : ids) {
            final BoxFolder folder = new BoxFolder(api, id);
            System.out.printf("\n=== %s =======================\n\n", folder.getInfo("name").getName());
            for (BoxItem.Info info : folder.getChildren("type", "id", "name"))
                System.out.printf("%-6s %-16s %s\n", info.getType(), info.getID(), info.getName());
            System.out.println();
        }
    }

    public String getFile(String id, Path localDir) throws IOException {
        final BoxFile file = new BoxFile(api, id);
        final String name = file.getInfo("name").getName();
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localDir.resolve(Utils.sanitizeFileName(name))))) {
            file.download(out);
        }
        return name;
    }

    public String deleteFile(String id) {
        final BoxFile file = new BoxFile(api, id);
        final String name = file.getInfo("name").getName();
        file.delete();
        return name;
    }

    public String deleteFolder(String id, boolean recursive) {
        final BoxFolder folder = new BoxFolder(api, id);
        final String name = folder.getInfo("name").getName();
        folder.delete(recursive);
        return name;
    }

    public void getFileDirect(String id, Path localPath) throws IOException {
        final BoxFile file = new BoxFile(api, id);
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localPath))) {
            file.download(out);
        }
    }

    public byte[] getFileContent(String id) {
        BoxFile file = new BoxFile(api, id);
        int size = (int) file.getInfo("size").getSize();
        final ByteArrayOutputStream baos = new ByteArrayOutputStream(size);
        file.download(baos);
        return baos.toByteArray();
    }

    public String putVersion(String id, Path localPath) throws IOException, InterruptedException {
        final long size = Files.size(localPath);
        final boolean large = size > LARGE_FILE_THRESHOLD;
        final String name = localPath.getFileName().toString();
        try (BufferedInputStream in = new BufferedInputStream(Files.newInputStream(localPath))) {
            final BoxFile file = new BoxFile(api, id);
            if (large)
                file.uploadLargeFile(in, size);
            else
                file.uploadNewVersion(in);
            if (!file.getInfo("name").getName().equals(name))
                file.rename(name);
        }
        return name;
    }

    public String putFolder(String id, List<Path> localPaths, boolean verbose) throws IOException, InterruptedException {
        final BoxFolder folder = new BoxFolder(api, id);
        final BoxFolder.Info folderInfo = folder.getInfo("id", "name");
        final String folderId = folderInfo.getID();
        if (verbose)
            System.out.println("Uploading to folder: " + folderInfo.getName());
        ensureFolderCached(folderId);
        for (Path p : localPaths) {
            final String name = p.getFileName().toString();
            final String existingId = getCachedFileId(folderId, name);
            if (verbose)
                System.out.println(name);
            if (existingId != null) {
                if (!existingId.isEmpty())
                    putVersion(existingId, p);
            } else {
                final long size = Files.size(p);
                try (BufferedInputStream in = new BufferedInputStream(Files.newInputStream(p))) {
                    BoxFile.Info info;
                    if (size > LARGE_FILE_THRESHOLD)
                        info = folder.uploadLargeFile(in, name, size);
                    else
                        info = folder.uploadFile(in, name);
                    putCachedFileId(folderId, name, info.getID());
                }
            }
        }
        return folderInfo.getName();
    }

    // This assumes that the size of bytes is not greater than 30MB.
    public void uploadBytesToFolder(String id, byte[] bytes, String name) {
        final BoxFolder folder = new BoxFolder(api, id);
        ensureFolderCached(id);
        final ByteArrayInputStream in = new ByteArrayInputStream(bytes);
        final String existingId = getCachedFileId(id, name);
        if (existingId != null) {
            if (!existingId.isEmpty()) {
                BoxFile file = new BoxFile(api, existingId);
                file.uploadNewVersion(in);
            }
        } else {
            BoxFile.Info info = folder.uploadFile(in, name);
            putCachedFileId(id, name, info.getID());
        }
    }

    public String rename(String id, boolean isFolder, String newName) {
        if (isFolder) {
            BoxFolder folder = new BoxFolder(api, id);
            String oldName = folder.getInfo("name").getName();
            folder.rename(newName);
            return oldName;
        } else {
            BoxFile file = new BoxFile(api, id);
            String oldName = file.getInfo("name").getName();
            file.rename(newName);
            return oldName;
        }
    }

    public String getParentFolderId(String id) {
        BoxFile file = new BoxFile(api, id);
        return file.getInfo("parent").getParent().getID();
    }

    public String getFileName(String id) {
        return new BoxFile(api, id).getInfo("name").getName();
    }

    public String getFolderName(String id) {
        return new BoxFolder(api, id).getInfo("name").getName();
    }

    public void moveAll(String sourceId, String destId, String regex, boolean verbose) {
        final BoxFolder sourceFolder = new BoxFolder(api, sourceId);
        final BoxFolder destFolder = new BoxFolder(api, destId);
        List<String> itemIds = new ArrayList<>(256);
        List<String> itemTypes = new ArrayList<>(256);
        Pattern pattern = null;
        if (regex != null && !regex.isEmpty())
            pattern = Pattern.compile(regex);
        for (BoxItem.Info info : sourceFolder.getChildren("id", "type", "name")) {
            if (pattern != null) {
                Matcher m = pattern.matcher(info.getName());
                if (!m.matches())
                    continue;  // skip items whose names don't match the regex
            }
            itemIds.add(info.getID());
            itemTypes.add(info.getType());
        }
        if (verbose)
            System.out.printf("Moving items from \"%s\" to \"%s\"...\n",
                sourceFolder.getInfo("name").getName(), destFolder.getInfo("name").getName());
        for (int i = 0; i < itemIds.size(); i++) {
            String id = itemIds.get(i);
            String type = itemTypes.get(i);
            BoxItem item = null;
            switch (type) {
            case "file":
                item = new BoxFile(api, id);
                break;
            case "folder":
                item = new BoxFolder(api, id);
                break;
            case "web_link":
                item = new BoxWebLink(api, id);
                break;
            }
            if (item == null) {
                if (verbose)
                    System.out.println("Skipping item of unknown type: " + type);
                continue;
            }
            BoxItem.Info info = item.move(destFolder);
            if (verbose)
                System.out.println(info.getName());
        }
    }

    public void rget(String folderId, Path localRoot, String regex, boolean verbose) {
        Pattern pattern = null;
        if (regex != null && !regex.isEmpty())
            pattern = Pattern.compile(regex);

        final LinkedList<String> pendingFolderIds = new LinkedList<>();
        final LinkedList<Path> localPaths = new LinkedList<>();

        int numFiles = 0;
        long totalSize = 0;
        final long startTime = System.currentTimeMillis();

        pendingFolderIds.addFirst(folderId);
        localPaths.addFirst(localRoot);
        while (!pendingFolderIds.isEmpty()) {
            final BoxFolder folder = new BoxFolder(api, pendingFolderIds.removeFirst());
            final Path currentDir = localPaths.removeFirst();
            if (verbose)
                System.out.println("\n== Entering folder: " + folder.getInfo("name").getName());
            for (BoxItem.Info info : folder.getChildren("type", "name", "id")) {
                final String name = info.getName();
                final String type = info.getType();
                if (pattern != null && !type.equals("folder")) {
                    Matcher m = pattern.matcher(name);
                    if (!m.matches())
                        continue;  // skip items whose names don't match the regex
                }
                try {
                    switch (type) {
                    case "file":
                        BoxFile file = new BoxFile(api, info.getID());
                        if (verbose)
                            System.out.println(name);
                        if (!Files.exists(currentDir))
                            Files.createDirectories(currentDir);
                        final Path filePath = currentDir.resolve(name);
                        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(filePath))) {
                            file.download(out);
                        }
                        totalSize += Files.size(filePath);
                        numFiles++;
                        break;
                    case "folder":
                        if (verbose)
                            System.out.println("Queuing folder: " + name);
                        pendingFolderIds.addLast(info.getID());
                        localPaths.addLast(currentDir.resolve(name));
                        break;
                    case "web_link":
                        if (verbose)
                            System.out.println("Web Link: " + name);
                        BoxWebLink link = new BoxWebLink(api, info.getID());
                        String url = link.getInfo("url").getLinkURL().toString();
                        Files.write(currentDir.resolve(Utils.sanitizeFileName(name) + ".weblink"), url.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        numFiles++;
                        break;
                    default:  // skip the item
                        break;
                    }
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }
        }
        final long endTime = System.currentTimeMillis();
        if (verbose)
            System.out.printf("\nFinished! Downloaded %d files (%d bytes) in %ds.\n",
                numFiles, totalSize, (endTime - startTime) / 1000);
    }

    public void rput(String folderId, Path localDir, String regex, boolean verbose) throws InterruptedException {
        Pattern pattern = null;
        if (regex != null && !regex.isEmpty())
            pattern = Pattern.compile(regex);

        final LinkedList<BoxFolder> pendingFolders = new LinkedList<>();
        final LinkedList<Path> localPaths = new LinkedList<>();

        int numFiles = 0;
        final long startTime = System.currentTimeMillis();
        long totalSize = 0L;

        final BoxFolder.Info baseFolderInfo = new BoxFolder(api, folderId).createFolder(localDir.getFileName().toString());
        pendingFolders.addFirst(baseFolderInfo.getResource());
        localPaths.addFirst(localDir);
        while (!pendingFolders.isEmpty()) {
            final BoxFolder folder = pendingFolders.removeFirst();
            final Path currentDir = localPaths.removeFirst();
            if (verbose)
                System.out.println("\n== Entering directory: " + currentDir.getFileName().toString());
            try {
                try (DirectoryStream<Path> dirStream = Files.newDirectoryStream(currentDir)) {
                    for (Path entry : dirStream) {
                        final String name = entry.getFileName().toString();
                        if (Files.isRegularFile(entry)) {
                            if (pattern != null && !pattern.matcher(name).matches())
                                continue;
                            if (verbose)
                                System.out.println(name);
                            final long size = Files.size(entry);
                            try (BufferedInputStream in = new BufferedInputStream(Files.newInputStream(entry))) {
                                if (size > LARGE_FILE_THRESHOLD)
                                    folder.uploadLargeFile(in, name, size);
                                else
                                    folder.uploadFile(in, name);
                            }
                            totalSize += size;
                            numFiles++;
                        } else if (Files.isDirectory(entry)) {
                            if (verbose)
                                System.out.println("Queuing directory: " + name);
                            pendingFolders.addLast(folder.createFolder(name).getResource());
                            localPaths.addLast(entry);
                        }
                    }
                }
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
        final long endTime = System.currentTimeMillis();
        if (verbose)
            System.out.printf("\nFinished! Uploaded %d files (%d bytes) in %ds.\n",
                numFiles, totalSize, (endTime - startTime) / 1000);
    }

    public void rdel(String folderId, String regex, boolean verbose) {
        final LinkedList<String> pendingFolderIds = new LinkedList<>();
        pendingFolderIds.addFirst(folderId);
        final Pattern pattern = Pattern.compile(regex);

        while (!pendingFolderIds.isEmpty()) {
            final BoxFolder folder = new BoxFolder(api, pendingFolderIds.removeFirst());
            if (verbose)
                System.out.println("\n== Entering folder: " + folder.getInfo("name").getName());
            for (BoxItem.Info info : folder.getChildren("type", "name", "id")) {
                final String name = info.getName();
                final String type = info.getType();
                if (!type.equals("folder") && !pattern.matcher(name).matches())
                    continue;
                switch (type) {
                case "file":
                    if (verbose)
                        System.out.println(name);
                    BoxFile file = new BoxFile(api, info.getID());
                    file.delete();
                    break;
                case "folder":
                    if (verbose)
                        System.out.println("Queuing folder: " + name);
                    pendingFolderIds.addLast(info.getID());
                    break;
                case "web_link":
                    if (verbose)
                        System.out.println("Web Link: " + name);
                    BoxWebLink link = new BoxWebLink(api, info.getID());
                    link.delete();
                    break;
                default:  // skip the item
                    break;
                }
            }

        }
    }

    private void ensureFolderCached(String folderId) {
        Map<String,String> nameIdMap = folderContentIdCache.get(folderId);
        if (nameIdMap == null) {
            nameIdMap = new HashMap<>(32);
            BoxFolder folder = new BoxFolder(api, folderId);
            for (BoxItem.Info info : folder.getChildren("type", "name", "id")) {
                if (info.getType().equals("file"))
                    nameIdMap.put(info.getName(), info.getID());
                else  // this is some non-file item that we can't overwrite
                    nameIdMap.put(info.getName(), "");
            }
            folderContentIdCache.put(folderId, nameIdMap);
        }
    }

    /**
     * Return the cached file ID for a filename in a given folder
     * @param folderId folder ID
     * @param filename filename
     * @return
     * <ul>
     *     <li>file ID if a file with the given name already exists in the folder</li>
     *     <li>null if no item with the given name is in the folder</li>
     *     <li>the empty string "" if a non-file item exists in the folder</li>
     * </ul>
     */
    private String getCachedFileId(String folderId, String filename) {
        Map<String,String> nameIdMap = folderContentIdCache.get(folderId);
        if (nameIdMap == null)
            return null;
        else
            return nameIdMap.get(filename);
    }

    private void putCachedFileId(String folderId, String filename, String fileId) {
        Map<String,String> nameIdMap = folderContentIdCache.get(folderId);
        if (nameIdMap == null) {
            nameIdMap = new HashMap<>(32);
            folderContentIdCache.put(folderId, nameIdMap);
        }
        nameIdMap.put(filename, fileId);
    }

    public void searchName(String query, String type, int limit) {
        BoxSearch search = new BoxSearch(api);
        BoxSearchParameters bsp = new BoxSearchParameters();
        bsp.setQuery(query);
        bsp.setType(type);
        bsp.setContentTypes(Arrays.asList("name"));
        PartialCollection<BoxItem.Info> results = search.searchRange(0, limit, bsp);
        for (BoxItem.Info info : results)
            System.out.printf("%-6s %-16s %s (in %s)\n", info.getType(), info.getID(), info.getName(), info.getParent().getName());
    }

    public String createSharedLink(String id, boolean isFolder) {
        BoxSharedLink.Permissions permissions = new BoxSharedLink.Permissions();
        permissions.setCanDownload(true);
        permissions.setCanPreview(true);
        BoxSharedLink link;
        if (!isFolder) { // aka isFile
            BoxFile file = new BoxFile(api, id);
            link = file.createSharedLink(BoxSharedLink.Access.OPEN, null, permissions);
        } else {
            BoxFolder folder = new BoxFolder(api, id);
            link = folder.createSharedLink(BoxSharedLink.Access.OPEN, null, permissions);
        }
        return link.getURL();
    }

    public Pair<String,String> moveItem(boolean isFolder, String sourceId, String destId) {
        String sourceName, destName;
        final BoxFolder destFolder = new BoxFolder(api, destId);
        destName = destFolder.getInfo("name").getName();
        if (!isFolder) { // aka isFile
            BoxFile file = new BoxFile(api, sourceId);
            sourceName = file.getInfo("name").getName();
            file.move(destFolder);
        } else {
            BoxFolder folder = new BoxFolder(api, sourceId);
            sourceName = folder.getInfo("name").getName();
            folder.move(destFolder);
        }
        return Pair.of(sourceName, destName);
    }
}
