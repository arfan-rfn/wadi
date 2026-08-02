package com.acme.petstore;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

/**
 * Census fixture (P8, §5.4.2): a client library wadi does NOT model. The
 * point is honesty, not extraction — the coverage report must carry an
 * unmodelled-mechanism entry for jdk-httpclient so a zero-edge answer from
 * this mechanism is distinguishable from a correct zero (the yas RestClient
 * lesson).
 */
public class LegacyPingProbe {

    private final HttpClient httpClient = HttpClient.newHttpClient();

    public int ping() throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://inventory:8081/ping")).GET().build();
        HttpResponse<Void> response = httpClient.send(request, HttpResponse.BodyHandlers.discarding());
        return response.statusCode();
    }
}
