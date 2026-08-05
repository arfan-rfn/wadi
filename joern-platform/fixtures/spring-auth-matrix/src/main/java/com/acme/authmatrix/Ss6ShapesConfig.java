package com.acme.authmatrix;

import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AuthorizeHttpRequestsConfigurer;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.util.matcher.RequestMatcher;

/**
 * The Spring Security 6 axis of the matrix (§5.2.10).
 *
 * <p>Every chain here was a SILENT DROP or a wrong answer before this section.
 * The existing {@code SecurityConfig} in this fixture is pure Spring Security
 * 5 — {@code httpBasic().disable()}, {@code authorizeRequests()},
 * {@code antMatchers} — because that is what the corpora the pass was written
 * against use. Those forms are deprecated in 6.1 and removed in 7, so every
 * codebase wadi meets from here on looks like THIS file, and a fixture that
 * models only the old dialect certifies nothing about the new one.
 *
 * <p>Each chain is its own class on purpose: chain scope was pooled per
 * declaring TYPE, so several chains in one class cross-contaminated and an
 * unscoped chain inherited its siblings' patterns.
 */
final class Ss6ShapesConfig {
    private Ss6ShapesConfig() {}
}

/** S6-A — the AuthorizedUrl parked in a local variable. */
@Configuration
class Ss6LocalVariableChain {

    @Autowired private MatrixSecurityProperties props;

    @Bean
    SecurityFilterChain localVariableChain(HttpSecurity http) throws Exception {
        http.securityMatcher("/ss6/local/**")
                .httpBasic(basic -> basic.disable())
                .authorizeHttpRequests(authorize -> {
                    // Config-driven code MUST do this: the access verb is
                    // chosen by an if/else, so the AuthorizedUrl cannot stay
                    // in the fluent chain. This is the exact train-ticket-aitest
                    // shape, and it took all 20 of its services' policies with it.
                    for (MatrixSecurityProperties.Rule rule : props.getRules()) {
                        String[] paths = rule.getPatterns().toArray(new String[0]);
                        AuthorizeHttpRequestsConfigurer.AuthorizedUrl url;
                        if (rule.getMethod() != null) {
                            url = authorize.requestMatchers(
                                    HttpMethod.valueOf(rule.getMethod()), paths);
                        } else {
                            url = authorize.requestMatchers(paths);
                        }
                        if (rule.isPermitAll()) {
                            url.permitAll();
                        } else {
                            url.hasAnyRole("SS6LOCAL");
                        }
                    }
                    authorize.anyRequest().authenticated();
                });
        return http.build();
    }
}

/** S6-B — a literal pattern through a local, and a ternary receiver. */
@Configuration
class Ss6IndirectReceiverChain {

    @Bean
    SecurityFilterChain indirectChain(HttpSecurity http, boolean strict) throws Exception {
        http.securityMatcher("/ss6/indirect/**").authorizeHttpRequests(authorize -> {
            AuthorizeHttpRequestsConfigurer.AuthorizedUrl held =
                    authorize.requestMatchers("/ss6/indirect/held");
            held.hasRole("SS6HELD");

            (strict
                            ? authorize.requestMatchers("/ss6/indirect/strict")
                            : authorize.requestMatchers("/ss6/indirect/loose"))
                    .hasRole("SS6TERNARY");

            scoped(authorize).hasRole("SS6HELPER");
            authorize.anyRequest().authenticated();
        });
        return http.build();
    }

    /** A helper that hands back the AuthorizedUrl — a receiver with no matcher
     * anywhere in the calling expression. */
    private AuthorizeHttpRequestsConfigurer<HttpSecurity>.AuthorizedUrl scoped(
            AuthorizeHttpRequestsConfigurer<HttpSecurity>.AuthorizationManagerRequestMatcherRegistry
                    authorize) {
        return authorize.requestMatchers("/ss6/indirect/helper");
    }
}

/** S6-C — patterns that are not literals: a placeholder, an array, a bean. */
@Configuration
class Ss6PatternSourceChain {

    @Value("${app.matrix.reports-path}")
    private String reportsPath;

    @Bean
    SecurityFilterChain patternSourceChain(HttpSecurity http) throws Exception {
        http.securityMatcher("/ss6/patterns/**").authorizeHttpRequests(authorize -> {
            authorize.requestMatchers(reportsPath).hasRole("SS6VALUE");

            String[] assembled = List.of("/ss6/patterns/assembled").toArray(new String[0]);
            authorize.requestMatchers(assembled).hasRole("SS6ARRAY");

            // Genuinely unreadable, and it must STAY unreadable: a matcher bean
            // names no path, and inventing one would be the fabrication the
            // whole section exists to prevent.
            authorize.requestMatchers(opaqueMatcher()).hasRole("SS6OPAQUE");
            authorize.anyRequest().authenticated();
        });
        return http.build();
    }

    private RequestMatcher opaqueMatcher() {
        return request -> false;
    }
}

/** S6-D — the Spring Security 6.1 method-reference disable shorthand. */
@Configuration
class Ss6MethodRefDisableChain {

    @Bean
    SecurityFilterChain methodRefChain(HttpSecurity http) throws Exception {
        http.securityMatcher("/ss6/methodref/**")
                .formLogin(AbstractMatrixConfigurer::disable)
                .authorizeHttpRequests(authorize -> authorize.anyRequest().authenticated());
        return http.build();
    }
}

/** Stand-in for {@code AbstractHttpConfigurer}, which lives in a jar this
 * fixture deliberately does not have. */
class AbstractMatrixConfigurer {
    static Object disable() {
        return null;
    }
}

/** Field-injected binding — the shape 20 of 20 train-ticket-aitest services
 * use, against the parameter-injected one this fixture already had. */
@Configuration
@ConfigurationProperties(prefix = "security")
class MatrixSecurityProperties {

    private List<Rule> rules = List.of();

    public List<Rule> getRules() {
        return rules;
    }

    static class Rule {
        private List<String> patterns = List.of();
        private String method;
        private boolean permitAll;

        public List<String> getPatterns() {
            return patterns;
        }

        public String getMethod() {
            return method;
        }

        public boolean isPermitAll() {
            return permitAll;
        }
    }
}
