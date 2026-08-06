package com.acme.shapes;

import java.util.List;

/**
 * Declares RAW `Envelope` returns, exactly as TrainTicket's services do. The
 * payload type exists only in the return statements below.
 */
public class EnvelopeService {

    /** Success names the type; the failure branch passes null. */
    public Envelope findAll() {
        List<Item> items = List.of();
        if (items.isEmpty()) {
            // A null payload is an ABSENCE, not a competing claim about T.
            return new Envelope<>(0, "empty", null);
        }
        return new Envelope<>(1, "ok", items);
    }

    /** Two constructions that genuinely disagree: T stays unresolved. */
    public Envelope conflicting(boolean flag) {
        Item item = new Item();
        String note = "note";
        if (flag) {
            return new Envelope<>(1, "ok", item);
        }
        return new Envelope<>(1, "ok", note);
    }
}
