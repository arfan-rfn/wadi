package com.acme.crud.repo;

import com.acme.crud.crm.Account;
import org.springframework.data.jpa.repository.JpaRepository;

/** `Account` resolves through this file's import, to the crm class (C2). */
public interface CrmAccountRepository extends JpaRepository<Account, Long> {
}
