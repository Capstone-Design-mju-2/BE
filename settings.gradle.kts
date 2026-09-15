pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

rootProject.name = "capstone-be"

include("services:catalog-service")
include("services:order-service")
