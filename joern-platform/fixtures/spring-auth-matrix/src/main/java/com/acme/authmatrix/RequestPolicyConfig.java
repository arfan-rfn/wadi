package com.acme.authmatrix;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * The THIRD category a SecurityConfig declares (§5.2.10 T6): policy that gates
 * which requests may REACH the service, without deciding which principal may.
 *
 * Kept in its own class rather than folded into {@link SecurityConfig}, whose
 * every line is tuned to one authorization-matrix row. These facts must never
 * move an authenticated/withheld number — a CORS policy answers "which origin",
 * CSRF answers "which request shape", and neither answers "which principal".
 * They are published so those questions become answerable at all (P10).
 */
@Configuration
public class RequestPolicyConfig implements WebMvcConfigurer {

    /** CORS with an explicit scope: the origin list hangs off addMapping. */
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/v1/**").allowedOrigins("https://app.acme.test");
    }

    @Bean
    SecurityFilterChain policyChain(HttpSecurity http) throws Exception {
        return http
                // CSRF stays ON here, with two exemptions — the shape that
                // proves `csrf-exempt` is a per-path fact, not a global one.
                .csrf(csrf -> csrf.ignoringRequestMatchers("/webhooks/**", "/api/v1/public"))
                // How rejection is answered: a 401 challenge and a 403 page.
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint(new BearerEntryPoint())
                        .accessDeniedHandler(new AuditingAccessDeniedHandler()))
                .build();
    }
}
