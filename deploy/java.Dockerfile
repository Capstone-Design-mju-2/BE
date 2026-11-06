# One image per Spring service: build with --build-arg SERVICE=catalog-service, order-service or gateway-service.
FROM eclipse-temurin:21.0.10_7-jdk AS build
WORKDIR /src
COPY gradlew settings.gradle.kts build.gradle.kts ./
COPY gradle gradle
COPY services services
ARG SERVICE
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew --no-daemon -q :services:${SERVICE}:bootJar \
    && find services/${SERVICE}/build/libs -name '*.jar' ! -name '*-plain.jar' -exec cp {} /app.jar \;

FROM eclipse-temurin:21.0.10_7-jre
RUN useradd --system app
COPY --from=build /app.jar /app/app.jar
USER app
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
