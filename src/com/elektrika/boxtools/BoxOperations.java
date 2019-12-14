package com.elektrika.boxtools;

import com.box.sdk.BoxAPIConnection;
import com.box.sdk.BoxFile;

import java.io.BufferedOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

public class BoxOperations
{
    private BoxAPIConnection api;

    public BoxOperations(Properties oauthProps, Properties tokenProps) {
        final String clientId = oauthProps.getProperty("client-id");
        final String clientSecret = oauthProps.getProperty("client-secret");
        final String accessToken = tokenProps.getProperty("access-token");
        final String refreshToken = tokenProps.getProperty("refresh-token");
        api = new BoxAPIConnection(clientId, clientSecret, accessToken, refreshToken);
    }

    public void getFile(String id, Path localPath) throws IOException {
        BoxFile file = new BoxFile(api, id);
        try (BufferedOutputStream out = new BufferedOutputStream(Files.newOutputStream(localPath))) {
            file.download(out);
        }
    }
}
