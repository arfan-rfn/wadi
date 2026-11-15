package com.acme.crud.service;

import com.acme.crud.domain.Issue;
import com.acme.crud.repo.IssueRepository;
import org.springframework.stereotype.Service;

@Service
public class IssueArchiver extends AbstractArchiver<Issue> {

    public IssueArchiver(IssueRepository issueRepository) {
        super(issueRepository);
    }
}
