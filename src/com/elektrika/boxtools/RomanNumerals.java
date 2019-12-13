/*
 * Adapted from RomanNumeralFormat.java (https://github.com/fracpete/romannumerals4j)
 * Copyright (C) 2016 University of Waikato, Hamilton, NZ
 * Copyright (C) paxdiablo
 * Copyright (C) Ravindra Gullapalli
 * Copyright (C) chepe lucho
 */

/*
 * This work is licensed under the Creative Commons Attribution-ShareAlike 3.0
 * Unported License. To view a copy of this license,
 * visit http://creativecommons.org/licenses/by-sa/3.0/ or send a letter to
 * Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
 */

package com.elektrika.boxtools;

import java.util.LinkedHashMap;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;

/**
 * Simple format/parse class for Roman Numerals, sourced from several StackOverflow posts. Roman numerals
 * only cover 1 to 3999.
 * @author FracPete (fracpete at waikato dot ac dot nz)
 * @author paxdiablo (regexp - http://stackoverflow.com/a/267405)
 * @author Ravindra Gullapalli (roman to int - http://stackoverflow.com/a/9073310)
 * @author chepe lucho (int to roman - http://stackoverflow.com/a/17376764)
 */
public class RomanNumerals
{
    protected static String[] ROMAN_NUMERALS = {"M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"};
    protected static int[] ROMAN_NUMERAL_VALUES = {1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1};

    /**
     * Return a number as a Roman numeral.
     */
    public static String format(int number) {
        if (number < 1 || number > 3999)
            return "?";

        final StringBuilder result = new StringBuilder();
        int intNum = (int) number;
        for (int i = 0; i < ROMAN_NUMERALS.length; i++) {
            int matches = intNum / ROMAN_NUMERAL_VALUES[i];
            for (int j = 0; j < matches; j++)
                result.append(ROMAN_NUMERALS[i]);
            intNum = intNum % ROMAN_NUMERAL_VALUES[i];
        }
        return result.toString();
    }
}
