package com.acme.crud.repo;

import com.acme.crud.domain.AuditEntry;
import org.springframework.data.repository.CrudRepository;

/** Store-agnostic marker: the repository kind is neither jpa nor mongo. */
public interface AuditEntryRepository extends CrudRepository<AuditEntry, Long> {
}
