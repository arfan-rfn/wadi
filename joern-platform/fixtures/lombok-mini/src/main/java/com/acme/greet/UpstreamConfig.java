package com.acme.greet;

import lombok.Getter;
import org.springframework.stereotype.Component;

/** Lombok-generated getter with the URL in the (source-visible) initializer —
 * the slicer's getter bridge resolves it without run-delombok. */
@Getter
@Component
public class UpstreamConfig {

    private final String baseUrl = "http://upstream:9000";
}
