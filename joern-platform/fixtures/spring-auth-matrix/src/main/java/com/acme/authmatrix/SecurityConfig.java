package com.acme.authmatrix;

import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.builders.WebSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * The legacy {@code WebSecurityConfigurerAdapter} chain, written to reproduce
 * the shapes measured on train-ticket that the previous extractor got wrong
 * (§5.2.9). Every line here is load-bearing for one matrix row:
 *
 * <ul>
 *   <li><b>D1 verb leakage</b> — the chain's FIRST verb-scoped matcher is POST.
 *       Reading the verb from the chain's text stamped POST onto every later
 *       rule, so the PUT and DELETE rules matched nothing and their endpoints
 *       fell through to unknown.</li>
 *   <li><b>D2 constant pattern</b> — {@code orders} is a bare instance field,
 *       exactly the train-ticket idiom. Dropping the rule let POST fall through
 *       to the permitAll sweep below and publish "no authentication".</li>
 *   <li><b>D2 unresolvable pattern</b> — {@code reportsPattern()} is a method
 *       call. It can never be resolved, and must therefore be emitted as an
 *       opaque rule so the claim is withheld rather than falling through.</li>
 *   <li><b>D3 partial roles</b> — {@code hasAnyRole(admin, "USER")} mixes a
 *       constant with a literal.</li>
 *   <li><b>D8 vocabulary</b> — {@code fullyAuthenticated()} was not in the
 *       access-call set, so its rule vanished silently.</li>
 * </ul>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig extends WebSecurityConfigurerAdapter {

    String admin = "ADMIN";
    String orders = "/api/v1/orders";

    @Override
    protected void configure(HttpSecurity httpSecurity) throws Exception {
        httpSecurity.httpBasic().disable()
                .csrf().disable()
                .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
                .and()
                .authorizeRequests()
                .antMatchers(HttpMethod.POST, orders).hasAnyRole(admin, "USER")
                .antMatchers(HttpMethod.PUT, orders).hasRole("ADMIN")
                .antMatchers(HttpMethod.DELETE, "/api/v1/orders/*").hasAuthority("ORDER_DELETE")
                .antMatchers(reportsPattern()).hasRole("AUDITOR")
                // Admits nobody. Must NOT read as an ordinary protected route:
                // the endpoint is unreachable, not merely gated.
                .antMatchers("/api/v1/orders/legacy").denyAll()
                .antMatchers("/api/v1/orders/**").permitAll()
                .antMatchers("/internal/**").fullyAuthenticated()
                .anyRequest().authenticated()
                .and()
                .addFilterBefore(new JwtAuthFilter(), UsernamePasswordAuthenticationFilter.class);
    }

    @Override
    public void configure(WebSecurity web) {
        web.ignoring().antMatchers("/static/**", "/favicon.ico");
    }

    /** Deliberately unreadable: the pattern is computed, not declared. */
    private String reportsPattern() {
        return "/api/v1/" + System.getenv("REPORTS_PATH");
    }
}
