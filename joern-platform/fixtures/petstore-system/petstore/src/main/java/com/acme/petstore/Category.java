package com.acme.petstore;

import java.util.List;

/** M5 shape probe (§5.2.7): a self-referencing DTO — the walk must terminate
 * with an explicit cycle node, never recurse. */
public class Category {
    public String name;
    public List<Category> children;
}
