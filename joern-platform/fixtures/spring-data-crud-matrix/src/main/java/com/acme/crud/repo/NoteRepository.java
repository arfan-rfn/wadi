package com.acme.crud.repo;

import com.acme.crud.domain.Note;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Query;

public interface NoteRepository extends NoteBaseRepository<Note> {

    /** Redeclares the base method with a query: at runtime this declaration
     *  is the one Spring Data reads, so it is the nearest that decides. */
    @Query("select n from Note n where n.body like ?1")
    @Override
    List<Note> search(String text, Pageable page);
}
