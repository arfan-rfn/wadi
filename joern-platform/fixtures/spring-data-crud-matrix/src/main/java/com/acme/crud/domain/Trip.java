package com.acme.crud.domain;

import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

/** Reached through `KeyedJpaRepository<TripId, Trip>`, a project base whose
 *  name contains a marker's. The entity is `Trip`, never the key (review A4). */
@Entity
@Table(name = "trips")
public class Trip {

    @EmbeddedId
    private TripId id;

    private String route;
}
