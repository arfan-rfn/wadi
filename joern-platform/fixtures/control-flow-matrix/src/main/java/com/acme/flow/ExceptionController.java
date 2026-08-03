package com.acme.flow;

import java.io.StringWriter;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/** One handler per exception construct. Catch/finally interiors are the
 * statements the current coarsening can silently delete. */
@RestController
public class ExceptionController {

    private final RestTemplate rest = new RestTemplate();

    @GetMapping("/except/try-catch/{text}")
    public String tryCatch(@PathVariable String text) {
        try {
            int parsed = Integer.parseInt(text);
            return "parsed:" + parsed;
        } catch (NumberFormatException e) {
            return "unparseable";
        }
    }

    @GetMapping("/except/multi-catch/{n}")
    public String multiCatch(@PathVariable int n) {
        try {
            int quotient = 100 / n;
            int[] window = new int[4];
            return String.valueOf(quotient + window[n]);
        } catch (ArithmeticException | ArrayIndexOutOfBoundsException e) {
            return "arithmetic-or-bounds";
        }
    }

    @GetMapping("/except/finally/{n}")
    public String withFinally(@PathVariable int n) {
        StringBuilder trace = new StringBuilder();
        try {
            trace.append("try");
            if (n < 0) {
                throw new IllegalArgumentException("negative");
            }
            trace.append(":ok");
        } catch (IllegalArgumentException e) {
            trace.append(":caught");
        } finally {
            trace.append(":done");
        }
        return trace.toString();
    }

    @GetMapping("/except/try-with-resources/{text}")
    public String tryWithResources(@PathVariable String text) {
        try (StringWriter writer = new StringWriter()) {
            writer.write(text);
            return writer.toString();
        } catch (java.io.IOException e) {
            return "io-error";
        }
    }

    @GetMapping("/except/throw/{n}")
    public String explicitThrow(@PathVariable int n) {
        if (n < 0) {
            throw new IllegalArgumentException("negative input");
        }
        return "accepted";
    }

    @GetMapping("/except/sink-in-throw/{n}")
    public String sinkInThrow(@PathVariable int n) {
        // Probe: an http-client sink whose call site sits inside a THROW
        // statement. Wrapped so the endpoint still answers when offline (M4).
        try {
            if (n < 0) {
                throw new IllegalStateException(
                    rest.getForObject("http://inventory:8080/status", String.class));
            }
            return "no-throw";
        } catch (RuntimeException e) {
            return "thrown";
        }
    }
}
