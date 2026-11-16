package com.acme.crud.domain;

import jakarta.persistence.Embeddable;

/** A composite key: a project type, and not an entity. */
@Embeddable
public class TripId {

    private String line;

    private int day;

    public TripId() {
    }

    public TripId(String line, int day) {
        this.line = line;
        this.day = day;
    }
}
