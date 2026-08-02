package com.acme.common;

import lombok.Data;

/**
 * The shared-module DTO (P8 fixture, §5.2.6): lives in a sibling library
 * module, appears in DI interface signatures, and its accessors are
 * Lombok-generated — the ts-common shape. Without the staged source union
 * this type is unresolvable from the petstore module.
 */
@Data
public class StockQuery {

    private String id;
}
