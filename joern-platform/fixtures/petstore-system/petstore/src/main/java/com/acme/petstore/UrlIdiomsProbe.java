package com.acme.petstore;

import java.text.MessageFormat;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * T2 probes (§5.4.2): URL-construction idioms — ternary branches (both are
 * candidates), statement-form StringBuilder, String.join, MessageFormat,
 * member-held Map.of constant maps, and a constructor-parameter @Value.
 */
@Service
public class UrlIdiomsProbe {

    /** Member-held constant map (the field-held service-registry variant). */
    private static final Map<String, String> HOSTS =
            Map.of("inventory", "http://inventory:8081");

    @Value("${inventory.api.url}")
    private String inventoryApiUrl;

    private final String ctorBase;
    private final RestTemplate restTemplate;

    public UrlIdiomsProbe(
            @Value("${inventory.api.url}") String ctorBase, RestTemplate restTemplate) {
        this.ctorBase = ctorBase;
        this.restTemplate = restTemplate;
    }

    public Integer viaTernary(String id, boolean fallback) {
        String base = fallback ? "http://backup-inventory:9091" : inventoryApiUrl;
        return restTemplate.getForObject(
                base + "/api/v1/inventory/reserved/" + id, Integer.class);
    }

    public Integer viaStringBuilder(String id) {
        StringBuilder sb = new StringBuilder(inventoryApiUrl);
        sb.append("/api/v1/inventory/reserved/");
        sb.append(id);
        return restTemplate.getForObject(sb.toString(), Integer.class);
    }

    public Integer viaJoin(String id) {
        String url = String.join("/", inventoryApiUrl + "/api/v1/inventory/audit", id);
        return restTemplate.getForObject(url, Integer.class);
    }

    public Integer viaMessageFormat(String id) {
        String url = MessageFormat.format("{0}/api/v1/inventory/audit/{1}", inventoryApiUrl, id);
        return restTemplate.getForObject(url, Integer.class);
    }

    public Integer viaConstantMap(String id) {
        return restTemplate.getForObject(
                HOSTS.get("inventory") + "/api/v1/inventory/stock/" + id, Integer.class);
    }

    public Integer viaCtorParam(String id) {
        return restTemplate.getForObject(ctorBase + "/stock/" + id, Integer.class);
    }
}
