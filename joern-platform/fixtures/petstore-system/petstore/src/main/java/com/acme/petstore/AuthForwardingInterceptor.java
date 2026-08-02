package com.acme.petstore;

import feign.RequestInterceptor;
import feign.RequestTemplate;
import org.springframework.stereotype.Component;

/** Forwards the caller's Authorization header on every Feign call —
 * token-propagation evidence for the M5 security pack. */
@Component
public class AuthForwardingInterceptor implements RequestInterceptor {

    @Override
    public void apply(RequestTemplate template) {
        template.header("Authorization", CurrentRequest.bearerToken());
    }
}
