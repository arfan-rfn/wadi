package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.NamedQueries;
import jakarta.persistence.NamedQuery;

/** Reached only through a project base interface (`IssueRepository extends
 *  BaseRepository<Issue>`), with its query text held in a `@NamedQueries`
 *  container: both are the ICPC shape. */
@Entity
@NamedQueries({
    @NamedQuery(name = "Issue.findOpen", query = "select i from Issue i where i.closed = false"),
    @NamedQuery(name = "Issue.findClosed", query = "select i from Issue i where i.closed = true")
})
public class Issue {

    @Id
    private Long id;

    private String title;

    private boolean closed;

    public String getTitle() {
        return title;
    }
}
