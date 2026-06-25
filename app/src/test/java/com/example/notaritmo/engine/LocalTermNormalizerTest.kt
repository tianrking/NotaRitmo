package com.example.notaritmo.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Deterministic tests for layer ⑤ (local glossary post-correction). These run on
 * the JVM with no device, no models, and no network, so they lock in the term
 * normalization behavior that the on-device pipeline relies on after every build.
 */
class LocalTermNormalizerTest {
    private val normalizer = LocalTermNormalizer()

    @Test
    fun `built-in rules correct known mishearings`() {
        assertEquals(
            "NotaRitmo 用的 Zipformer",
            normalizer.normalize("诺塔里特莫 用的 齐普former"),
        )
    }

    @Test
    fun `user glossary with aliases rewrites mishearings`() {
        normalizer.setUserGlossary("张江高科=张江高客,张江糕客\n智谱AI=智普AI")
        assertEquals(
            "张江高科 和 智谱AI",
            normalizer.normalize("张江高客 和 智普AI"),
        )
    }

    @Test
    fun `user glossary bare term enforces canonical casing`() {
        normalizer.setUserGlossary("NotaRitmo")
        assertEquals("NotaRitmo", normalizer.normalize("notaritmo"))
    }

    @Test
    fun `comments and blank lines are ignored`() {
        normalizer.setUserGlossary("# 这是一个注释\n\n   \nK2FSA")
        assertEquals("K2FSA", normalizer.normalize("k2fsa"))
    }

    @Test
    fun `clearing the glossary leaves arbitrary text unchanged`() {
        normalizer.setUserGlossary("临时词=临时磁")
        assertEquals("临时词", normalizer.normalize("临时磁"))
        // An empty/null glossary must not keep the previous rules.
        normalizer.setUserGlossary("")
        assertEquals("临时磁", normalizer.normalize("临时磁"))
    }

    @Test
    fun `longer aliases are applied before shorter ones`() {
        // "上海中心" should win over "上海" when both are declared.
        normalizer.setUserGlossary("上海中心\n上海=沪")
        val out = normalizer.normalize("我们去了上海中心")
        assertTrue("expected 上海中心 preserved, got: $out", out.contains("上海中心"))
    }
}
