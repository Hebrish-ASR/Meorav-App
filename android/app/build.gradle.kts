plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// The model catalogue (../catalog/catalog.json) is the same file that is published at
// https://cdn.hebrish.app/models/meorav/catalog.json. It is copied into the APK's assets at build
// time as the offline fallback; never hand-copy it.
val catalogDir = layout.buildDirectory.dir("generated/catalog")
val copyCatalog by tasks.registering(Copy::class) {
    from(rootProject.file("../catalog/catalog.json"))
    into(catalogDir)
}
tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(copyCatalog) }

android {
    namespace = "app.hebrish.meorav"
    compileSdk = 36
    // Pinned so CI and the laptop compile ggml with the same toolchain (CI installs it).
    ndkVersion = "28.0.13004108"

    defaultConfig {
        applicationId = "app.hebrish.meorav"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        // Phones only. qwentts.cpp/ggml is compiled for arm64 (see src/main/cpp/CMakeLists.txt).
        ndk { abiFilters += "arm64-v8a" }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_static")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    buildFeatures { buildConfig = true }

    signingConfigs {
        create("release") {
            // CI writes the keystore from secrets; locally point these env vars at your own.
            val ks = System.getenv("RELEASE_KEYSTORE")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("RELEASE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("RELEASE_KEY_ALIAS")
                keyPassword = System.getenv("RELEASE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("RELEASE_KEYSTORE") != null)
                signingConfigs.getByName("release") else signingConfigs.getByName("debug")
        }
    }

    sourceSets["main"].assets.srcDir(catalogDir)

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { jniLibs { useLegacyPackaging = true } }
}
