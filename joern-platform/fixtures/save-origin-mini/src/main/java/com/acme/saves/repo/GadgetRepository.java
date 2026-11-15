package com.acme.saves.repo;

import com.acme.saves.domain.Gadget;
import org.springframework.data.jpa.repository.JpaRepository;

public interface GadgetRepository extends JpaRepository<Gadget, String> {
}
