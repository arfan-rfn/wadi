package com.acme.crud.billing;

import org.springframework.data.jpa.repository.JpaRepository;

/** `Account` resolves through the same package, with no import (C2). */
public interface AccountRepository extends JpaRepository<Account, Long> {
}
