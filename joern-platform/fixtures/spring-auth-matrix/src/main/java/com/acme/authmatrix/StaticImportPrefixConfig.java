package com.acme.authmatrix;

import static com.acme.authmatrix.ApiRoutes.SECURED_PREFIX;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * A prefix constant reached by STATIC IMPORT rather than by qualifier
 * (recorded 2026-08-05).
 *
 * <p>{@code ConcatPrefixConfig} pins {@code Routes.CONTEST_PREFIX} — a
 * qualified reference, which resolves by class name and so never depended on
 * the owner. A bare statically-imported name takes the other branch: it is
 * owner-scoped to the type that declared it (§5.2.5, which is what keeps two
 * classes declaring {@code order} apart), and the owner here declares nothing.
 *
 * <p>Measured before the fix: the SAME constant in the SAME graph resolved for
 * endpoint paths (owner = None) and failed for matcher patterns (owner = the
 * config class), leaving nine rules without scope and withholding the auth
 * claim on 729 endpoints of a real system. Owner scoping keeps precedence and
 * only yields when it has nothing to say.
 */
final class ApiRoutes {
    static final String SECURED_PREFIX = "/secured";

    private ApiRoutes() {}
}

@RestController
@RequestMapping(SECURED_PREFIX + "/api")
class StaticImportPrefixController {

    /** Covered by the permitAll below — must read as open, not protected. */
    @GetMapping("/public/ping")
    public String publicPing() {
        return "pong";
    }

    /** Falls through to anyRequest().authenticated(). */
    @GetMapping("/private/data")
    public String privateData() {
        return "data";
    }
}

@Configuration
class StaticImportPrefixSecurity {

    @Bean
    SecurityFilterChain staticImportChain(HttpSecurity http) throws Exception {
        http.securityMatcher(SECURED_PREFIX + "/api/**").authorizeHttpRequests(authorize -> {
            authorize.requestMatchers(HttpMethod.GET, SECURED_PREFIX + "/api/public/**").permitAll();
            authorize.anyRequest().authenticated();
        });
        return http.build();
    }
}
