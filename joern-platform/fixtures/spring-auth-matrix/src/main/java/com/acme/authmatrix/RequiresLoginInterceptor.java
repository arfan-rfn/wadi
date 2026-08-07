package com.acme.authmatrix;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Gates by reading an annotation off the handler (§5.2.12 route c).
 *
 * <p>Its scope is NOT its registered path patterns — it is registered on
 * {@code /**} and gates only the handlers carrying {@link RequiresLogin}.
 * Reporting the registration scope instead would withhold every endpoint in
 * the service, which is the blanket this tranche exists to avoid.
 */
public class RequiresLoginInterceptor implements HandlerInterceptor {

    private final TenantDirectory directory = new TenantDirectory();

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
            Object handler) {
        if (!(handler instanceof HandlerMethod method)) {
            return true;
        }
        if (method.getMethodAnnotation(RequiresLogin.class) == null) {
            return true;
        }
        if (this.directory.getCurrentUserId() == null) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            return false;
        }
        return true;
    }
}
