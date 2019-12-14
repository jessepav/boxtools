package com.elektrika.boxtools;

import java.awt.Desktop;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Path;


/**
 * Provides integration with the host OS -- a bit like java.awt.Desktop
 */
class OS
{
    private static Desktop desktop;

    static void browseURI(URI uri) throws IOException {
        if (!ensureDesktop())
            return;
        desktop.browse(uri);
    }

    static void openPath(Path path) throws IOException {
        if (!ensureDesktop())
            return;
        desktop.open(path.toFile());
    }

    static void printPath(Path path) throws IOException {
        if (!ensureDesktop())
            return;
        desktop.print(path.toFile());
    }

    private static boolean ensureDesktop() {
        if (desktop == null) {
            if (Desktop.isDesktopSupported()) {
                desktop = Desktop.getDesktop();
            }
        }
        return desktop != null;
    }
}
