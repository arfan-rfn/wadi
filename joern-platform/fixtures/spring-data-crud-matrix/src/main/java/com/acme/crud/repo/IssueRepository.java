package com.acme.crud.repo;

import com.acme.crud.domain.Issue;
import java.util.List;
import org.springframework.data.jpa.repository.Query;

/** A repository only through `BaseRepository` (Q10): no marker in its own
 *  extends clause. */
public interface IssueRepository extends BaseRepository<Issue> {

    @Query(name = "Issue.findOpen")
    List<Issue> findOpen();
}
