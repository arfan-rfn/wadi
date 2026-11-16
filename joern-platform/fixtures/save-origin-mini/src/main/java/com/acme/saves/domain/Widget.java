package com.acme.saves.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Inheritance;

@Entity
@Inheritance
public class Widget {

    @Id
    private String id;

    private String code;

    private String name;

    public Widget() {
    }

    public Widget(String id) {
        this.id = id;
    }

    public String getId() {
        return id;
    }

    /** Lombok's `toBuilder` shape: a builder seeded from an EXISTING widget,
     *  so what it builds is not a construction. */
    public Builder toBuilder() {
        Builder builder = new Builder();
        builder.id = id;
        builder.name = name;
        return builder;
    }

    public static class Builder {

        private String id;

        private String name;

        public Builder name(String name) {
            this.name = name;
            return this;
        }

        public Widget build() {
            Widget widget = new Widget(id);
            widget.name = name;
            return widget;
        }
    }
}
