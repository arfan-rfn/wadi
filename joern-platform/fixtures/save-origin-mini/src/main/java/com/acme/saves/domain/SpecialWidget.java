package com.acme.saves.domain;

import jakarta.persistence.Entity;

/** A subtype entity saved through the parent's repository. */
@Entity
public class SpecialWidget extends Widget {

    public SpecialWidget() {
    }

    public SpecialWidget(String id) {
        super(id);
    }
}
