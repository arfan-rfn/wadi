package com.acme.orders;

import lombok.Getter;
import lombok.Setter;

/**
 * Two shapes the classifier used to get wrong (§5.4.2 T5).
 *
 * <p><b>Prefix boundary.</b> {@code settle} begins with the letters "set" but
 * is not a setter. Testing the prefix alone made any such name on a Lombok
 * type report {@code lombok-generated}, which states in the UI that no source
 * exists — about a method written by hand, right here.
 *
 * <p><b>Annotation direction.</b> The class carries {@code @Getter} only, so
 * Lombok generates no setters for it; the setter that does exist is asked for
 * per field. A direction-aware check has to read BOTH levels, or it swaps one
 * mislabel for another.
 */
@Getter
public class OrderFormatter {

    @Setter
    private String prefix;

    /** Hand-written, and NOT an accessor despite the leading "set". */
    public String settle(String id) {
        return prefix + ":" + id;
    }

    /** Overload #1 — see {@link #format(String, int)}. */
    public String format(String id) {
        return settle(id);
    }

    /** Overload #2. Two same-named first-party methods are what
     * {@code ambiguous-overload} is for: when the receiver cannot be pinned to
     * one of them, the map declines to choose rather than guessing a body. */
    public String format(String id, int count) {
        return settle(id) + "x" + count;
    }
}
