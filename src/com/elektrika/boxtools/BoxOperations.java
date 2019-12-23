package com.elektrika.boxtools;

import com.box.sdk.BoxAPIConnection;
import com.box.sdk.BoxFile;
import com.box.sdk.BoxFolder;
import com.box.sdk.BoxItem;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

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

    public void listFolder(String id) {
        final BoxFolder folder = id.equals("/") ? BoxFolder.getRootFolder(api) : new BoxFolder(api, id);
        System.out.printf("\n=== %s =======================\n\n", folder.getInfo("name").getName());
        for (BoxItem.Info info : folder.getChildren("type", "id", "name"))
            System.out.printf("%-6s %-14s %s\n", info.getType(), info.getID(), info.getName());
        System.out.println();
    }

    public String getFile(String id, Path localDir) throws IOException {
        final BoxFile file = new BoxFile(api, id);
        final String name = file.getInfo("name").getName();
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localDir.resolve(name)))) {
            file.download(out);
        }
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

    public String putFolder(String id, List<Path> localPaths) throws IOException, InterruptedException {
        final BoxFolder folder = id.equals("/") ? BoxFolder.getRootFolder(api) : new BoxFolder(api, id);
        final BoxFolder.Info folderInfo = folder.getInfo("id", "name");
        final String folderId = folderInfo.getID();
        ensureFolderCached(folderId);
        for (Path p : localPaths) {
            final String name = p.getFileName().toString();
            final String existingId = getCachedFileId(folderId, name);
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
        BoxFolder folder;
        if (id.equals("/")) {
            folder = BoxFolder.getRootFolder(api);
            id = folder.getInfo("id").getID();
        } else {
            folder = new BoxFolder(api, id);
        }
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

    public void moveAll(String sourceId, String destId, boolean verbose) {
        final BoxFolder sourceFolder = sourceId.equals("/") ? BoxFolder.getRootFolder(api) : new BoxFolder(api, sourceId);
        final BoxFolder destFolder = destId.equals("/") ? BoxFolder.getRootFolder(api) : new BoxFolder(api, destId);
        List<String> fileIds = new ArrayList<>(256);
        for (BoxItem.Info info : sourceFolder.getChildren("id"))
            fileIds.add(info.getID());
        if (verbose)
            System.out.printf("Moving all items from %s to %s...\n",
                sourceFolder.getInfo("name").getName(), destFolder.getInfo("name").getName());
        for (String id : fileIds) {
            BoxFile f = new BoxFile(api, id);
            BoxItem.Info info = f.move(destFolder);
            if (verbose)
                System.out.println(info.getName());
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
}
