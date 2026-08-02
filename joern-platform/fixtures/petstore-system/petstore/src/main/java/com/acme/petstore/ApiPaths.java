package com.acme.petstore;

/** Constant mapping prefixes (P8 fixture, §5.4.2 — the yas ApiConstant idiom). */
public final class ApiPaths {

    public static final String ADMIN_PETS = "/admin/pets";

    /** Non-literal feign name attribute (T2) — resolved from this constant. */
    public static final String INVENTORY_NAME = "inventory";

    /** Nested constant holder — the exact yas Constants.ApiConstant shape. */
    public final class Nested {

        public static final String VET_PETS = "/vet/pets";
    }

    private ApiPaths() {
    }
}
