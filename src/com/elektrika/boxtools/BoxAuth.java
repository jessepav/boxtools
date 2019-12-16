package com.elektrika.boxtools;

import com.box.sdk.BoxAPIConnection;
import fi.iki.elonen.NanoHTTPD;
import org.apache.commons.lang3.StringUtils;

import java.io.FileWriter;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;

public class BoxAuth
{
    private Properties props;
    private Path propsPath;

    public BoxAuth(Properties props, Path propsPath) {
        this.props = props;
        this.propsPath = propsPath;
    }

    public void retrieveOAuthTokens() throws IOException, URISyntaxException {
        final String clientId = props.getProperty("client-id");
        final String clientSecret = props.getProperty("client-secret");
        final String redirectUri = props.getProperty("redirect-uri");
        final int port = new URI(redirectUri).getPort();
        final URI authorizationUri = new URI(StringUtils.replace(props.getProperty("authorization-url"), "[CLIENT_ID]", clientId, 1));

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
        Utils.sleep(3000);
        server.stop();

        BoxAPIConnection client = new BoxAPIConnection(clientId, clientSecret, server.code);
        saveTokens(propsPath, client);
    }

    public static BoxAPIConnection createAPIConnection(Path authPropsPath) throws IOException {
        final Properties authProps = Utils.loadProps(authPropsPath);
        final Properties tokenProps = Utils.loadProps(authPropsPath.resolveSibling(authProps.getProperty("token-file")));
        final String clientId = authProps.getProperty("client-id");
        final String clientSecret = authProps.getProperty("client-secret");
        final String accessToken = tokenProps.getProperty("access-token");
        final String refreshToken = tokenProps.getProperty("refresh-token");
        return new BoxAPIConnection(clientId, clientSecret, accessToken, refreshToken);
    }

    public static void saveTokens(Path authPropsPath, BoxAPIConnection client) throws IOException {
        final Properties authProps = Utils.loadProps(authPropsPath);
        final Path tokenFilePath = authPropsPath.resolveSibling(authProps.getProperty("token-file"));
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
