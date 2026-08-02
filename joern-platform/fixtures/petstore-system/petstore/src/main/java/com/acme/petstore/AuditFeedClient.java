package com.acme.petstore;

import org.springframework.web.service.annotation.GetExchange;
import org.springframework.web.service.annotation.HttpExchange;

/**
 * T2 probe (§5.4.2): Spring 6 declarative HTTP interface — @GetExchange
 * methods are outbound sinks like feign contracts; the type-level absolute
 * url supplies the authority here (the proxy-factory base join is the
 * recorded limitation for relative interfaces).
 */
@HttpExchange(url = "https://audit.example.com")
public interface AuditFeedClient {

    @GetExchange("/feed/{id}")
    String feed(String id);
}
