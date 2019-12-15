package com.elektrika.boxtools;

import com.box.sdk.BoxAPIConnection;
import com.box.sdk.BoxFile;
import com.box.sdk.BoxFolder;
import com.box.sdk.BoxItem;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class BoxOperations
{
    public static final long LARGE_FILE_THRESHOLD = 30_000_000L;

    private BoxAPIConnection api;

    public BoxOperations(BoxAPIConnection api) {
        this.api = api;
    }

    public BoxAPIConnection getApiConnection() {
        return api;
    }

    public void listFolder(String id) {
        final BoxFolder folder = new BoxFolder(api, id);
        System.out.printf("\n=== %s =======================\n\n", folder.getInfo().getName());
        for (BoxItem.Info info : folder)
            System.out.printf("%-6s %-14s %s\n", info.getType(), info.getID(), info.getName());
        System.out.println();
    }

    public String getFile(String id, Path localDir) throws IOException {
        final BoxFile file = new BoxFile(api, id);
        final String name = file.getInfo().getName();
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localDir.resolve(name)))) {
            file.download(out);
        }
        return name;
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
            if (!file.getInfo().getName().equals(name))
                file.rename(name);
        }
        return name;
    }

    public String putFolder(String id, List<Path> localPaths) throws IOException, InterruptedException {
        final BoxFolder folder = new BoxFolder(api, id);
        final Map<String,String> nameIdMap = new HashMap<>(32);
        for (BoxItem.Info info : folder) {
            if (info.getType().equals("file"))
                nameIdMap.put(info.getName(), info.getID());
            else
                nameIdMap.put(info.getName(), "");
        }
        for (Path p : localPaths) {
            final String name = p.getFileName().toString();
            final String existingId = nameIdMap.get(name);
            if (existingId != null) {
                if (!existingId.isEmpty())
                    putVersion(existingId, p);
            } else {
                final long size = Files.size(p);
                try (BufferedInputStream in = new BufferedInputStream(Files.newInputStream(p))) {
                    if (size > LARGE_FILE_THRESHOLD)
                        folder.uploadLargeFile(in, name, size);
                    else
                        folder.uploadFile(in, name);
                }
            }
        }
        return folder.getInfo().getName();
    }

    public String rename(String id, boolean isFolder, String newName) {
        if (isFolder) {
            BoxFolder folder = new BoxFolder(api, id);
            String oldName = folder.getInfo().getName();
            folder.rename(newName);
            return oldName;
        } else {
            BoxFile file = new BoxFile(api, id);
            String oldName = file.getInfo().getName();
            file.rename(newName);
            return oldName;
        }
    }
}
