package com.acme.authmatrix;

import java.util.ArrayList;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.stereotype.Component;

/**
 * A SECOND filter chain, scoped by {@code securityMatcher}, whose rules come
 * from {@code application.yaml} rather than from this file (§5.2.9 D5 + chain
 * scoping).
 *
 * <p>Both properties matter. There is not one literal path in the loop below,
 * so a pattern reader that only sees Java literals extracts nothing and every
 * endpoint under it falls to a catch-all — the shape yas ships. And because
 * this chain declares a {@code securityMatcher}, its rules must not be pooled
 * with the other chain's: first-match-wins applies within a chain, never
 * across them.
 */
@Order(1)
public class ConfigDrivenSecurityConfig {

    @Bean
    public SecurityFilterChain reportsChain(HttpSecurity http, ApiSecurityProperties props)
            throws Exception {
        http.securityMatcher("/config-driven/**")
                .authorizeHttpRequests(auth -> {
                    for (ApiSecurityProperties.Rule rule : props.getRules()) {
                        String[] patterns = rule.getPatterns().toArray(new String[0]);
                        if (rule.isPermitAll()) {
                            auth.requestMatchers(patterns).permitAll();
                        } else {
                            auth.requestMatchers(patterns)
                                    .hasAnyRole(rule.getRoles().toArray(new String[0]));
                        }
                    }
                    auth.anyRequest().authenticated();
                });
        return http.build();
    }
}

@Component
@ConfigurationProperties(prefix = "app.api-security")
class ApiSecurityProperties {

    private List<Rule> rules = new ArrayList<>();

    public List<Rule> getRules() {
        return rules;
    }

    public void setRules(List<Rule> rules) {
        this.rules = rules;
    }

    static class Rule {
        private List<String> patterns = new ArrayList<>();
        private List<String> roles = new ArrayList<>();
        private boolean permitAll = false;

        public List<String> getPatterns() {
            return patterns;
        }

        public void setPatterns(List<String> patterns) {
            this.patterns = patterns;
        }

        public List<String> getRoles() {
            return roles;
        }

        public void setRoles(List<String> roles) {
            this.roles = roles;
        }

        public boolean isPermitAll() {
            return permitAll;
        }

        public void setPermitAll(boolean permitAll) {
            this.permitAll = permitAll;
        }
    }
}
