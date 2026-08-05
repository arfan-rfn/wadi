package com.acme.shapes;

import com.fasterxml.jackson.annotation.JsonProperty;

/** The payload every recovery case must arrive at. */
public class Item {

    private String id;

    @JsonProperty("display_name")
    private String displayName;

    private int quantity;

    public String getId() {
        return id;
    }

    public String getDisplayName() {
        return displayName;
    }

    public int getQuantity() {
        return quantity;
    }
}
