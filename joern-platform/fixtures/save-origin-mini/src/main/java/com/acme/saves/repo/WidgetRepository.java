package com.acme.saves.repo;

import com.acme.saves.domain.Widget;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WidgetRepository extends JpaRepository<Widget, String> {

    /** Returns the entity or null: the null-check guard shapes test it. */
    Widget findByCode(String code);
}
