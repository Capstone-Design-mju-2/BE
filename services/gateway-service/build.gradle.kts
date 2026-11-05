plugins {
    id("org.springframework.boot")
    id("io.spring.dependency-management")
}

description = "API gateway in front of agent, catalog and order (ADR-133)"

dependencyManagement {
    imports {
        // 2025.1.x supports Spring Boot 4.1 from 2025.1.2 on.
        mavenBom("org.springframework.cloud:spring-cloud-dependencies:2025.1.4")
    }
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.cloud:spring-cloud-starter-gateway-server-webflux")
    implementation("org.springframework.cloud:spring-cloud-starter-circuitbreaker-reactor-resilience4j")
    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation("org.springframework.boot:spring-boot-starter-webflux-test")
}
