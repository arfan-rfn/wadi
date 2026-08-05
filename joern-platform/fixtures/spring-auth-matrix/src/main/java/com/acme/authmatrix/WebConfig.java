package com.acme.authmatrix;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Authorization enforced entirely outside Spring Security (§5.2.9 D9) — the
 * shape the rule pass is structurally blind to, because there is no access
 * call anywhere in it.
 *
 * <p>Two interceptors on purpose. {@link TenantAuthInterceptor} gates: it can
 * answer 401, so an endpoint under its path patterns must have its claim
 * withheld rather than read as unprotected. {@link TimingInterceptor} does
 * not gate, and must be ignored — treating every interceptor as a guard would
 * withhold claims system-wide and make the state meaningless.
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new TenantAuthInterceptor()).addPathPatterns("/api/v1/audit");
        registry.addInterceptor(new TimingInterceptor());
    }
}

/** Gates: it decides access and can answer 401. */
class TenantAuthInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
            Object handler) {
        if (request.getHeader("X-Tenant") == null) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            return false;
        }
        return true;
    }
}

/** Does not gate — measures. Must never be reported as an auth enforcement. */
class TimingInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
            Object handler) {
        request.setAttribute("startedAt", System.nanoTime());
        return true;
    }
}
