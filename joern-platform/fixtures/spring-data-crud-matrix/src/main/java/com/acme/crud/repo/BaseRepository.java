package com.acme.crud.repo;

import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.repository.NoRepositoryBean;

/** The project base interface (the ICPC shape): `E` binds only through a
 *  subtype, so the entity comes from the receiver's declared type (R1-4). */
@NoRepositoryBean
public interface BaseRepository<E> extends JpaRepository<E, Long> {

    List<E> findAllByIdIn(Collection<Long> ids);
}
