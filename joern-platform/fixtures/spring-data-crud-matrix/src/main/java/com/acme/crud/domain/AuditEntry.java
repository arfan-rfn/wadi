package com.acme.crud.domain;

/** No @Entity and no @Document: only `AuditEntryRepository` names this type,
 *  so it is an entity by the repository's type argument alone (Q1). */
public class AuditEntry {

    private Long id;

    private String message;

    public String getMessage() {
        return message;
    }
}
