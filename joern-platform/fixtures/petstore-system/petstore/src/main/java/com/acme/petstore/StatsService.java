package com.acme.petstore;

/** Interface → abstract base → impl chain (P8 fixture, §5.2.6). */
public interface StatsService {
    String weekly(String owner);
}
