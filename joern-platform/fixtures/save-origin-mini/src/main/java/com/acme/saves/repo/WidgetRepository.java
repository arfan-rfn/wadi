package com.acme.saves.repo;

import com.acme.saves.domain.Widget;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface WidgetRepository extends JpaRepository<Widget, String> {

    /** Returns the entity or null: the null-check guard shapes test it. */
    Widget findByCode(String code);

    /** Returns a list, which is never null: a null test on it decides nothing. */
    List<Widget> findByName(String name);

    /** A `search` prefix is a read, so it is a lookup too (review B4). */
    List<Widget> searchByName(String name);
}
