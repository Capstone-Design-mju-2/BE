package com.capstone.gateway;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Where the circuit breaker sends a request whose service could not be reached, did not answer in time or is cut off
 * after repeated failures (ADR-133). Error responses the service itself sends pass through unchanged.
 */
@RestController
class FallbackController {

    @RequestMapping("/fallback")
    ResponseEntity<ErrorBody> fallback() {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(new ErrorBody("SERVICE_UNAVAILABLE", "서비스가 잠시 응답하지 않습니다. 잠시 후 다시 시도해 주세요."));
    }

    record ErrorBody(String code, String message) {}
}
