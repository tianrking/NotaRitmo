import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
}

val localProps = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) {
        file.inputStream().use(::load)
    }
}

val enableAbiSplits = providers.gradleProperty("enableAbiSplits")
    .map { it.toBoolean() }
    .orElse(false)
val appVersionCode = providers.gradleProperty("versionCode")
    .map { it.toInt() }
    .orElse(1)
val appVersionName = providers.gradleProperty("versionName")
    .orElse("1.0")

fun propOrEnv(name: String, fallback: String = ""): String {
    return localProps.getProperty(name)
        ?: System.getenv(name)
        ?: fallback
}

fun quoted(value: String): String {
    return "\"" + value
        .replace("\\", "\\\\")
        .replace("\"", "\\\"") + "\""
}

android {
    namespace = "com.example.notaritmo"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.example.notaritmo"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode.get()
        versionName = appVersionName.get()

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField(
            "String",
            "DEFAULT_LLM_BASE",
            quoted(propOrEnv("ANTHROPIC_BASE_URL", "https://open.bigmodel.cn/api/anthropic"))
        )
        buildConfigField(
            "String",
            "DEFAULT_LLM_MODEL",
            quoted(
                propOrEnv(
                    "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    propOrEnv("ANTHROPIC_MODEL", "glm-5.2")
                )
            )
        )
        buildConfigField(
            "String",
            "DEFAULT_LLM_API_KEY",
            quoted(propOrEnv("ANTHROPIC_AUTH_TOKEN", ""))
        )
    }

    buildFeatures {
        buildConfig = true
    }

    splits {
        abi {
            isEnable = enableAbiSplits.get()
            reset()
            include("arm64-v8a")
            isUniversalApk = true
        }
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
        }
    }
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}
