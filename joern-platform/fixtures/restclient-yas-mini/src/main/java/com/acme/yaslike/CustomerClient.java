package com.acme.yaslike;

import java.net.URI;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

/** The exact yas outbound idiom (§5.4.2 T2): UCB base from a
 * @ConfigurationProperties record accessor, URI-typed local, RestClient. */
@Service
public class CustomerClient {

    private final RestClient restClient;
    private final ServiceUrlConfig serviceUrlConfig;

    public CustomerClient(RestClient restClient, ServiceUrlConfig serviceUrlConfig) {
        this.restClient = restClient;
        this.serviceUrlConfig = serviceUrlConfig;
    }

    public String getCustomerProfile() {
        final URI url = UriComponentsBuilder
                .fromUriString(serviceUrlConfig.customer())
                .path("/storefront/customer/profile")
                .buildAndExpand()
                .toUri();
        return restClient.get()
                .uri(url)
                .retrieve()
                .body(String.class);
    }
}
