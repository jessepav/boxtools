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
import java.util.Properties;

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

    public void getFile(String id, Path localPath) throws IOException {
        BoxFile file = new BoxFile(api, id);
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localPath))) {
            file.download(out);
        }
    }

    public void putFile(String id, Path localPath, boolean newFile) throws IOException, InterruptedException {
        final long size = Files.size(localPath);
        final boolean large = size > LARGE_FILE_THRESHOLD;
        final String filename = localPath.getFileName().toString();
        try (BufferedInputStream in = new BufferedInputStream(Files.newInputStream(localPath))) {
            if (newFile) {
                BoxFolder folder = new BoxFolder(api, id);
                if (large)
                    folder.uploadLargeFile(in, filename, size);
                else
                    folder.uploadFile(in, filename);
            } else {
                BoxFile file = new BoxFile(api, id);
                if (large)
                    file.uploadLargeFile(in, size);
                else
                    file.uploadNewVersion(in);
                if (!file.getInfo().getName().equals(filename))
                    file.rename(filename);
            }
        }
    }
}
