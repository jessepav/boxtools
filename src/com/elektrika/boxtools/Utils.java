package com.elektrika.boxtools;

import java.io.FileReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;
import java.util.logging.*;

public final class Utils
{
    /** The global logger, used everywhere. */
    public static Logger logger;

    /**
     * In case someone wants to use use {@link #logger} to print to the console without the full rotating
     * log machinery that we normally set up.
     * @param name name of the logger
     */
    public static void initSimpleLogging(String name) throws IOException {
        System.setProperty("java.util.logging.SimpleFormatter.format", "%4$s: [%1$tF %1$tT] %5$s %6$s%n");
        LogManager.getLogManager().readConfiguration();

        logger = Logger.getLogger(name);
        logger.setLevel(Level.FINE);
        logger.setUseParentHandlers(false);
        Handler handler = new ConsoleHandler();
        handler.setLevel(Level.FINE);
        handler.setFormatter(new SimpleFormatter());
        logger.addHandler(handler);
    }

    public static Properties loadProps(Path path) throws IOException {
        final Properties props = new Properties();
        if (Files.exists(path)) {
            try (FileReader r = new FileReader(path.toFile())) {
                props.load(r);
            }
        }
        return props;
    }

    /**
     * Parses an input string as a decimal integer
     * @param s String representation of an integer
     * @param errorVal if {@code s} is not successfully parsed, we return this value
     * @return int value of {@code s} if parseable, or {@code errorVal} otherwise
     */
    public static int parseInt(String s, int errorVal) {
        int i = errorVal;
        if (s != null && s.length() > 0) {
            try {
                i = Integer.parseInt(s);
            } catch (NumberFormatException ex) {
                i = errorVal;
            }
        }
        return i;
    }

    /**
     * Equivalent to {@link #parseInt(String, int) parseInt(s, 0)}
     */
    public static int parseInt(String s) {
        return parseInt(s, 0);
    }

    public static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }
}
