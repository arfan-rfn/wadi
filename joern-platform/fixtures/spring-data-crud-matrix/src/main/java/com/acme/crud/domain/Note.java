package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** Reached through `NoteRepository extends NoteBaseRepository<Note>`, whose
 *  sub-interface redeclares a base method with `@Query` (review A3). */
@Entity
@Table(name = "notes")
public class Note {

    @Id
    private Long id;

    private String body;
}
