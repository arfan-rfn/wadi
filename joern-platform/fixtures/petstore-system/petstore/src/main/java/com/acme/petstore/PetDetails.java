package com.acme.petstore;

import java.math.BigDecimal;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

/** M5 shape probe (§5.2.7): nested DTO with Jackson wire semantics. */
public class PetDetails {

    public String id;

    /** Renamed on the wire — the shape must carry the serialized name. */
    @JsonProperty("display_name")
    public String name;

    /** Never serialized — the shape must omit it (wire contract, not layout). */
    @JsonIgnore
    public String internalNote;

    public StockInfo stock;

    public List<String> tags;

    /** Nested object with a money scalar. */
    public static class StockInfo {
        public int available;
        public BigDecimal price;
    }
}
