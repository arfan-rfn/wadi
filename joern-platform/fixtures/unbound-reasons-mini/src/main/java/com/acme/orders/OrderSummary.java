package com.acme.orders;

/** Plain first-party class with a real body: the control case. Calls into
 *  `describe` must bind normally and carry NO unbound reason. */
public class OrderSummary {

    public String describe(String id, int statusCount) {
        if (id == null) {
            return "unknown";
        }
        return id + ":" + statusCount;
    }
}
