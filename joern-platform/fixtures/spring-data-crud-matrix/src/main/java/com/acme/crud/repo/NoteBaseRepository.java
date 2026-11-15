package com.acme.crud.repo;

import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.repository.NoRepositoryBean;

/** Declares `search` with no query; `NoteRepository` redeclares it with one.
 *  `findTagged` is varargs, so a call's argument count need not match its
 *  parameter count (review A3). */
@NoRepositoryBean
public interface NoteBaseRepository<E> extends JpaRepository<E, Long> {

    List<E> search(String text, Pageable page);

    List<E> findTagged(String... tags);
}
