package com.acme.common;

import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;

/**
 * The classification decoy (P8 fixture, §5.2.6): a shared-module global
 * exception handler — the yas common-library shape. The advice annotation
 * below must NOT trip the service-marker scan by substring, or this module
 * flips to "service" and the source union silently disables for every
 * dependent. (Note: this comment deliberately avoids writing the bare marker
 * tokens — the scan reads raw text, comments included.)
 */
@ControllerAdvice
public class CommonExceptionHandler {

    @ExceptionHandler(RuntimeException.class)
    public String handle(RuntimeException exception) {
        return exception.getMessage();
    }
}
