package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

/** Reached through a base interface whose parameters are declared in the
 *  opposite order to the marker's: binding is by position, not by name. */
@Entity
public class Ticket {

    @Id
    private String id;

    private String subject;
}
