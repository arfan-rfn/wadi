package com.acme.tokens;

import org.springframework.http.HttpHeaders;

/** The corpus idiom: headers reach the outbound entity through a helper. */
public final class HeadersUtil {

    private HeadersUtil() {
    }

    public static HttpHeaders prepareForSent(HttpHeaders inbound) {
        HttpHeaders outbound = new HttpHeaders();
        outbound.setAll(inbound.toSingleValueMap());
        return outbound;
    }
}
