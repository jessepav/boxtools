package com.elektrika.boxtools;

import org.apache.commons.codec.binary.Base64;
import org.apache.commons.lang3.StringUtils;
import org.apache.commons.lang3.ArrayUtils;

import java.nio.charset.StandardCharsets;
import java.util.*;
import java.io.IOException;
import java.nio.file.*;

import it.sauronsoftware.ftp4j.*;
import java.security.KeyManagementException;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.logging.Level;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

import static com.elektrika.boxtools.Utils.logger;

public final class FTP
{
    private String host;
    private int port;
    private int[] timeouts;   // connect, read-write, close
    private int security;   // one of FTPClient.SECURITY_{FTP/FTPS/FTPES}
    private String username, password;

    private FTPClient client;

    public FTP(Properties props) {
        host = props.getProperty("ftp-server");
        port = Utils.parseInt(props.getProperty("ftp-server-port"));
        timeouts = new int[3];
        String[] sa = StringUtils.split(props.getProperty("timeout", "10"), ", ");
        switch (sa.length) {
        case 1:
            timeouts[0] = timeouts[1] = timeouts[2] = Utils.parseInt(sa[0]);
            break;
        case 2:
            timeouts[0] = timeouts[2] = Utils.parseInt(sa[0]);
            timeouts[1] = Utils.parseInt(sa[1], timeouts[0]);
            break;
        case 3:
            timeouts[0] = Utils.parseInt(sa[0]);
            timeouts[1] = Utils.parseInt(sa[1], timeouts[0]);
            timeouts[2] = Utils.parseInt(sa[2], timeouts[0]);
            break;
        }
        String s = props.getProperty("security", "none").toLowerCase();
        switch (s) {
        case "implicit":
            security = FTPClient.SECURITY_FTPS;
            break;
        case "explicit":
            security = FTPClient.SECURITY_FTPES;
            break;
        case "none":
            security = FTPClient.SECURITY_FTP;
            break;
        default:
            security = -1;
            break;
        }
        String[] creds = decodeCredentials(props.getProperty("credentials", ""));
        if (creds != null) {
            username = creds[0];
            password = creds[1];
        }
    }

    public boolean isValid() {
        return (host != null && port > 0 && timeouts[0] > 0 && security >= 0 &&
            username != null && password != null);
    }

    public FTPClient connect() throws IOException {
        if (!isValid())
            return null;

        if (client == null) {
            client = new FTPClient();
            FTPConnector connector = client.getConnector();
            connector.setConnectionTimeout(timeouts[0]);
            connector.setReadTimeout(timeouts[1]);
            connector.setCloseTimeout(timeouts[2]);
            if (security != FTPClient.SECURITY_FTP) {
                // If we're using SSL security, then create an SSLSocketFactory that accepts
                // all server certificates.
                TrustManager[] trustManager = new TrustManager[] {new X509TrustManager()
                {
                    public X509Certificate[] getAcceptedIssuers() { return null; }
                    public void checkClientTrusted(X509Certificate[] certs, String authType) { }
                    public void checkServerTrusted(X509Certificate[] certs, String authType) { }
                }};
                SSLContext sslContext = null;
                try {
                    sslContext = SSLContext.getInstance("SSL");
                    sslContext.init(null, trustManager, new SecureRandom());
                } catch (NoSuchAlgorithmException|KeyManagementException e) {
                    logger.log(Level.WARNING, "FTP connect()", e);
                }
                SSLSocketFactory sslSocketFactory = sslContext.getSocketFactory();

                client.setSSLSocketFactory(sslSocketFactory);
                client.setSecurity(security);
            }
        }
        if (!client.isConnected()) {
            try {
                client.connect(host, port);
                client.login(username, password);
            } catch (FTPIllegalReplyException|FTPException e) {
                if (client.isConnected() && !client.isAuthenticated())
                    disconnect();  // this was a login failure
                throw new IOException(e);
            }
        }
        return client;
    }

    public void disconnect() throws IOException {
        if (client != null && client.isConnected()) {
            try {
                client.disconnect(true);
            } catch (FTPIllegalReplyException|FTPException e) {
                throw new IOException(e);
            }
        }
    }

    /**
     * Uploads a local file to a remote directory. If {@code remoteDir} is null, then
     * the FTP client's current directory is used.
     * <p/>
     * Note that the filename of the local file is used as the remote file name.
     * <p/>
     * This method leaves the FTP client's current directory as {@code remoteDir}.
     * @param localPath local file to upload
     * @param remoteDir the remote directory
     * @throws IOException
     */
    public void uploadFile(Path localPath, Path remoteDir) throws IOException {
        if (client == null || !client.isConnected())
            return;
        try {
            if (remoteDir != null)
                changeDirectories(remoteDir);
            client.upload(localPath.toFile());
        } catch (FTPException|FTPIllegalReplyException|FTPAbortedException|FTPDataTransferException e) {
            throw new IOException(e);
        }
    }

    /**
     * Downloads a file from a remote path to a local path.
     * <p/>
     * This method leaves the FTP client's current directory as the parent directory of {@code remotePath}.
     * @param remotePath the remote path of the file to download
     * @param localPath where to save the file
     * @throws IOException
     */
    public void downloadFile(Path remotePath, Path localPath) throws IOException {
        if (client == null || !client.isConnected())
            return;
        try {
            Path parent = remotePath.getParent();
            if (parent != null)
                changeDirectories(parent);
            client.download(remotePath.getFileName().toString(), localPath.toFile());
        } catch (FTPException|FTPIllegalReplyException|FTPAbortedException|FTPDataTransferException e) {
            throw new IOException(e);
        }
    }

    /**
     * Deletes a file from the server
     * <p/>
     * This method leaves the FTP client's current directory as the parent directory of {@code path}.
     * @param path file to delete
     * @throws IOException
     */
    public void deleteFile(Path path) throws IOException {
        if (client == null || !client.isConnected())
            return;
        try {
            Path parent = path.getParent();
            if (parent != null)
                changeDirectories(parent);
            client.deleteFile(path.getFileName().toString());
        } catch (FTPException|FTPIllegalReplyException e) {
            throw new IOException(e);
        }
    }

    /**
     * Checks if a remote path exists. Uses the "MLST" command, and thus won't
     * work on servers that don't support it.
     * <p/>
     * This method leaves the FTP client's current directory as the parent directory of {@code path}.
     * @param path the remote path to check for existence
     * @return true if {@code path} exists
     * @throws IOException
     */
    public boolean remotePathExists(Path path) throws IOException {
        if (client == null || !client.isConnected())
            return false;
        try {
            Path parent = path.getParent();
            if (parent != null)
                changeDirectories(parent);
            FTPReply reply = client.sendCustomCommand("MLST " + path.getFileName().toString());
            return reply.isSuccessCode();
        } catch (FTPException|FTPIllegalReplyException e) {
            throw new IOException(e);
        }
    }

    private void changeDirectories(Path dir) throws IOException, FTPIllegalReplyException, FTPException {
        if (dir.getRoot() != null)
            client.changeDirectory("/");
        for (int i = 0; i < dir.getNameCount(); i++)
            client.changeDirectory(dir.getName(i).toString());
    }

    /**
     * Decodes a Base64-encoded credentials string into a username/password array.
     * @param credentials base64-encoded string (UTF-8) of "<username> / <password>"
     * @return String array of username (index 0) and password (index 1), or null
     *         if the credentials string is not valid Base64
     */
    private static String[] decodeCredentials(String credentials) {
        if (!Base64.isBase64(credentials))
            return null;
        String decoded = new String(Base64.decodeBase64(credentials), StandardCharsets.UTF_8);
        String[] creds = StringUtils.splitByWholeSeparator(decoded, " / ", 2);
        if (creds.length != 2)
            return null;
        else
            return creds;
    }
}
