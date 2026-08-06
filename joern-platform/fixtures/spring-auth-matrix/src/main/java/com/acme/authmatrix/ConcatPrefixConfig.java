package com.acme.authmatrix;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Two defects that compound (recorded 2026-08-05).
 *
 * <p>Writing a route prefix once and reusing it is ordinary, and it defeated
 * two readers at the same time. The endpoint pass took the FIRST quoted string
 * out of the annotation, so the URI truncated to its tail and collided with
 * routes from other controllers. The security pass could not read the matching
 * pattern at all, so the rule had no scope.
 *
 * <p>They compound in the worst direction: you cannot tell which endpoints the
 * public rule covers until the paths resolve, so the auth defect is not even
 * measurable while the URI defect stands.
 */
final class Routes {
    static final String CONTEST_PREFIX = "/contest";

    private Routes() {}
}

@RestController
@RequestMapping(Routes.CONTEST_PREFIX + "/api")
class ConcatPrefixController {

    @GetMapping("/public/list")
    public String publicList() {
        return "public";
    }

    @GetMapping("/secret")
    public String secret() {
        return "secret";
    }
}

@Configuration
class ConcatPrefixSecurity {

    @Bean
    SecurityFilterChain concatChain(HttpSecurity http) throws Exception {
        http.securityMatcher(Routes.CONTEST_PREFIX + "/api/**").authorizeHttpRequests(authorize -> {
            authorize.requestMatchers(Routes.CONTEST_PREFIX + "/api/public/**").permitAll();
            authorize.anyRequest().authenticated();
        });
        return http.build();
    }
}
