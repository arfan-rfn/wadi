package com.acme.shapes;

import java.util.List;

/**
 * The callee side of recovery. Note these DECLARE their return types: the
 * handler's signature is what is raw, not the service's, which is why the
 * payload is recoverable at all (§5.2.7 amendment).
 */
public class ItemService {

    public Item findOne() {
        return new Item();
    }

    /** Generics live here — recovery must read this text, not the erased type. */
    public List<Item> findAll() {
        return List.of();
    }

    public String describe() {
        return "an item";
    }

    /** The entity-graph root (§5.2.15) — declared, so recovery can reach it. */
    public Contest graphRoot() {
        return new Contest();
    }
}
