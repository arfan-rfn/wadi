package com.acme.tokens;

import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/**
 * The three token-propagation states (§5.2.11 T4), resolved PER CALL SITE.
 *
 * Deliberately one class, and {@link #both} deliberately builds two entities a
 * few lines apart: that is the corpus shape (`ConsignServiceImpl` lines 62 and
 * 95) which a method-level answer smears together. The old detector looked for
 * a literal "Authorization" anywhere in the enclosing method, which on
 * train-ticket appears only inside JWTUtil — where inbound tokens are READ and
 * no outbound sink exists — so it reported null on all 382 calls.
 */
@RestController
public class TokenController {

    private final RestTemplate restTemplate = new RestTemplate();

    /** forwarded: the inbound headers ride along on the outbound entity. */
    @GetMapping("/tokens/forward")
    public String forwards(@RequestHeader HttpHeaders headers) {
        HttpEntity<String> request = new HttpEntity<>(null, headers);
        ResponseEntity<String> re = restTemplate.exchange(
                "http://inventory:8081/stock/1", HttpMethod.GET, request, String.class);
        return re.getBody();
    }

    /** not-forwarded: an entity built with NO headers argument — provable. */
    @GetMapping("/tokens/bare")
    public String bare(@RequestHeader HttpHeaders headers) {
        HttpEntity<String> request = new HttpEntity<>(null);
        ResponseEntity<String> re = restTemplate.exchange(
                "http://inventory:8081/reserved/1", HttpMethod.GET, request, String.class);
        return re.getBody();
    }

    /** Both shapes in one method: each site must answer for itself. */
    @GetMapping("/tokens/both")
    public String both(@RequestHeader HttpHeaders headers) {
        HttpEntity<String> carried = new HttpEntity<>(null, headers);
        ResponseEntity<String> first = restTemplate.exchange(
                "http://inventory:8081/audit/1", HttpMethod.GET, carried, String.class);
        HttpEntity<String> plain = new HttpEntity<>(null);
        ResponseEntity<String> second = restTemplate.exchange(
                "http://inventory:8081/public/1", HttpMethod.GET, plain, String.class);
        return first.getBody() + second.getBody();
    }
}
