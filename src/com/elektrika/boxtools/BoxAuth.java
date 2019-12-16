package com.elektrika.boxtools;

import com.box.sdk.BoxAPIConnection;
import com.box.sdk.BoxConfig;
import com.box.sdk.BoxDeveloperEditionAPIConnection;
import fi.iki.elonen.NanoHTTPD;
import org.apache.commons.lang3.StringUtils;

import java.io.BufferedReader;
import java.io.FileWriter;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;

public final class BoxAuth
{
    private BoxTools.Config config;
    private boolean usingJwt;

    public BoxAuth(BoxTools.Config config) throws IOException {
        setConfig(config);
    }

    public void setConfig(BoxTools.Config config) throws IOException {
        this.config = config;
    }


    public void retrieveOAuthTokens() throws IOException, URISyntaxException {
        final String clientId = config.props.getProperty("client-id");
        final String clientSecret = config.props.getProperty("client-secret");
        final String redirectUri = config.props.getProperty("redirect-uri");
        final int port = new URI(redirectUri).getPort();
        final URI authorizationUri = new URI(StringUtils.replace(config.props.getProperty("authorization-url"), "[CLIENT_ID]", clientId, 1));

        OAuthHttpServer server = new OAuthHttpServer(port);
        server.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false);

        System.out.println("Authorization URI:\n  " + authorizationUri.toString());
        OS.browseURI(authorizationUri);

        synchronized (server) {
            while (server.code == null) {
                try {
                    server.wait();
                } catch (InterruptedException e) { /* ignore */ }
            }
        }
        BoxAPIConnection client = new BoxAPIConnection(clientId, clientSecret, server.code);
        usingJwt = false;
        saveTokens(client);

        Utils.sleep(3000);
        server.stop();
    }

    public BoxAPIConnection createAPIConnection() throws IOException {
        final String jwtConfig = config.props.getProperty("config-json");
        if (jwtConfig == null) { // use OAuth
            usingJwt = false;
            final Properties tokenProps = Utils.loadProps(config.propsPath.resolveSibling(config.props.getProperty("token-file")));
            final String clientId = config.props.getProperty("client-id");
            final String clientSecret = config.props.getProperty("client-secret");
            final String accessToken = tokenProps.getProperty("access-token");
            final String refreshToken = tokenProps.getProperty("refresh-token");
            return new BoxAPIConnection(clientId, clientSecret, accessToken, refreshToken);
        } else {
            usingJwt = true;
            BoxConfig boxConfig;
            try (BufferedReader reader = Files.newBufferedReader(config.propsPath.resolveSibling(jwtConfig), StandardCharsets.UTF_8)) {
                boxConfig = BoxConfig.readFrom(reader);
            }
            BoxDeveloperEditionAPIConnection api = BoxDeveloperEditionAPIConnection.getAppEnterpriseConnection(boxConfig);
            final String userId = config.props.getProperty("auth-user");
            if (userId != null)
                api = BoxDeveloperEditionAPIConnection.getAppUserConnection(userId, boxConfig);
            return api;
        }
    }

    public void saveTokens(BoxAPIConnection client) throws IOException {
        if (usingJwt)
            return;

        final Path tokenFilePath = config.propsPath.resolveSibling(config.props.getProperty("token-file"));
        Properties tokenProps = new Properties();
        tokenProps.setProperty("access-token", client.getAccessToken());
        tokenProps.setProperty("refresh-token", client.getRefreshToken());
        tokenProps.setProperty("can-refresh", Boolean.toString(client.canRefresh()));
        tokenProps.setProperty("expires", Long.toString(client.getExpires()));
        try (FileWriter w = new FileWriter(tokenFilePath.toFile())) {
            tokenProps.store(w, "BoxAPIConnection tokens");
        }
    }

    private static class OAuthHttpServer extends NanoHTTPD
    {
        private String code;

        private OAuthHttpServer(int port) {
            super(port);
        }

        @Override
        public synchronized Response serve(IHTTPSession session) {
            final Map<String,List<String>> parameters = session.getParameters();
            if (parameters.containsKey("code")) {
                code = parameters.get("code").get(0);
                notify();
                return newFixedLengthResponse("<html><body><b>Tokens retrieved - check token file.</b></body></html>");
            } else {
                return newFixedLengthResponse("<html><body><b>No code in parameters!</b></body></html>");
            }
        }

        protected boolean useGzipWhenAccepted(Response r) {
            return false;
        }
    }
}
