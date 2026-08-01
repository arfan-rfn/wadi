# Security Guidelines

## Authentication Security

This application uses **Better Auth** for authentication, which provides enterprise-grade security out of the box.

### ✅ Built-in Security Features

1. **Secure Token Storage**
   - Session tokens stored in httpOnly cookies (inaccessible to JavaScript)
   - Encrypted cookie content
   - Secure flag enabled on HTTPS
   - SameSite=Lax for CSRF protection

2. **CSRF Protection**
   - Origin header validation
   - SameSite cookie attribute
   - OAuth state parameter validation
   - PKCE for OAuth code exchange

3. **XSS Protection**
   - httpOnly cookies prevent token theft
   - React auto-escapes rendered content
   - No dangerous DOM operations
   - No token exposure to client-side storage

4. **Session Management**
   - Server-side session storage
   - Automatic session expiration (7 days default)
   - Session invalidation on logout
   - Database-backed session tracking

5. **Password Security**
   - scrypt algorithm (memory-hard, CPU-intensive)
   - Resistant to brute-force attacks
   - Secure password hashing by default

6. **Rate Limiting**
   - Built-in rate limiting on auth routes
   - Configurable IP-based throttling
   - Prevents brute-force attacks

---

## Security Best Practices

### For Developers

#### ✅ DO:
- Use `useAuthContext()` for accessing auth state
- Use `getAuthToken()` from context for API calls
- Always check `isAuthenticated` before protected operations
- Use Better Auth's built-in hooks and methods
- Keep dependencies updated (`npm audit`)

#### ❌ DON'T:
- Never store tokens in localStorage or sessionStorage
- Don't expose tokens in URL parameters
- Don't log tokens or session data
- Don't use `dangerouslySetInnerHTML` with user input
- Don't bypass authentication checks

### Secure API Calls

```typescript
// ✅ Correct: Use auth context
const { getAuthToken, isAuthenticated } = useAuthContext()

if (!isAuthenticated) {
  return <Redirect to="/auth/sign-in" />
}

const token = getAuthToken()
const response = await apiClient.get('/protected', {
  headers: { 'Authorization': `Bearer ${token}` }
})
```

```typescript
// ❌ Wrong: Don't store token
localStorage.setItem('token', token) // NEVER DO THIS

// ❌ Wrong: Don't expose token
window.authToken = token // NEVER DO THIS
```

---

## Production Deployment Checklist

### Critical (Must Complete Before Production):

- [ ] **Configure Trusted Origins**
  ```typescript
  // Backend Better Auth config
  trustedOrigins: [
    'https://yourdomain.com',
    'https://www.yourdomain.com'
  ]
  ```

- [ ] **Enable HTTPS**
  - Secure flag automatically enabled
  - Use SSL/TLS certificates
  - Redirect HTTP to HTTPS

- [ ] **Set Environment Variables**
  ```bash
  NODE_ENV=production
  NEXT_PUBLIC_BASE_URL=https://yourdomain.com
  NEXT_PUBLIC_API_URL=https://api.yourdomain.com
  ```

- [ ] **Verify Cookie Settings**
  - httpOnly: true ✅
  - Secure: true (on HTTPS) ✅
  - SameSite: Lax or Strict ✅

### Recommended (Security Hardening):

- [ ] **Add Content Security Policy**
  ```javascript
  // next.config.js
  headers: [{
    key: 'Content-Security-Policy',
    value: "default-src 'self'; ..."
  }]
  ```

- [ ] **Add Security Headers**
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY
  - Referrer-Policy: strict-origin-when-cross-origin

- [ ] **Configure Rate Limiting**
  ```typescript
  rateLimit: {
    enabled: true,
    max: 10,
    window: 60
  }
  ```

- [ ] **Set Up Session Monitoring**
  - Log authentication events
  - Monitor failed login attempts
  - Alert on suspicious activity

---

## Security Incident Response

### If You Suspect a Security Issue:

1. **Immediate Actions:**
   - Revoke all active sessions (server-side)
   - Rotate authentication secrets
   - Review recent access logs

2. **Investigation:**
   - Identify affected users
   - Determine scope of breach
   - Review server logs

3. **Remediation:**
   - Patch vulnerability
   - Force password resets if needed
   - Notify affected users

4. **Prevention:**
   - Update dependencies
   - Review security audit
   - Implement additional safeguards

### Reporting Vulnerabilities

If you discover a security vulnerability:
- **DO NOT** open a public GitHub issue
- Email security concerns to: [your-security-email]
- Use encrypted communication if possible

---

## Security Audits

### Latest Audit
- **Date**: 2025-10-04
- **Status**: ✅ Secure (A- Rating)
- **Report**: [authentication-security-audit.md](./authentication-security-audit.md)

### Audit Schedule
- **After major auth changes**: Immediate review
- **Quarterly**: Full security audit
- **Annually**: Penetration testing

### Recent Security Updates
- 2025-10-04: Session optimization (no vulnerabilities introduced)
- Better Auth migration: httpOnly cookies, CSRF protection

---

## Dependency Security

### Monitoring
```bash
# Check for vulnerabilities
npm audit

# Auto-fix (review changes first!)
npm audit fix

# Check outdated packages
npm outdated
```

### Update Strategy
- **Critical security patches**: Immediate
- **Major updates**: Review changelog first
- **Dependencies**: Keep within 1 major version
- **Better Auth**: Follow upgrade guides

---

## Compliance

### GDPR Considerations
- User data deletion implemented (`useDeleteAccount`)
- Session data in database (can be purged)
- User consent for cookies (implement cookie banner)

### Data Protection
- Passwords: hashed with scrypt ✅
- Sessions: encrypted cookies ✅
- User data: stored securely in backend database
- API: HTTPS only in production

---

## Additional Resources

- [Better Auth Security Docs](https://www.better-auth.com/docs/reference/security)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Next.js Security](https://nextjs.org/docs/app/building-your-application/configuring/security)
- [Security Audit Report](./authentication-security-audit.md)
- [Authentication Optimization](./authentication-optimization.md)

---

## Contact

For security questions or concerns:
- Review: [authentication-security-audit.md](./authentication-security-audit.md)
- Email: [your-security-email]
- Emergency: [emergency-contact]

**Last Updated**: 2025-10-04
