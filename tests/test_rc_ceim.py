"""Tests for the CEIm-style structured review module.

Covers:
- classify_study_type: study type detection
- _match_heading_to_review_slot: heading classification
- _detect_keywords: keyword presence detection
- _evaluate_checklist: checklist evaluation engine
- _extract_strengths / _extract_weaknesses: pattern detection
- _extract_ethical_considerations: ethical markers
- _compute_recommendation: global recommendation logic
- generate_ceim_review: full review generation (observational + qualitative)
- render_ceim_review_md: markdown output
- generate_ceim_review_file: file output
"""

from __future__ import annotations

import unittest
from pathlib import Path

from researchclaw.ceim_reviewer import (
    classify_study_type,
    generate_ceim_review,
    generate_ceim_review_file,
    render_ceim_review_md,
    StudyType,
    ChecklistItem,
    _match_heading_to_review_slot,
    _detect_keywords,
    _evaluate_checklist,
    _extract_strengths,
    _extract_weaknesses,
    _extract_ethical_considerations,
    _compute_recommendation,
    _OBSERVATIONAL_CHECKLIST,
    _QUALITATIVE_CHECKLIST,
    _is_systematic_review,
    _is_negated,
    _SR_NA_ITEMS,
)


# ---------------------------------------------------------------------------
# Sample protocols
# ---------------------------------------------------------------------------

_OBSERVATIONAL_PROTOCOL = """\
## Title
Efficacy of Curcumin vs Placebo in Pediatric Ulcerative Colitis: A Systematic Review

## Introduction
Pediatric ulcerative colitis (UC) is a chronic inflammatory bowel disease.
The limited evidence on curcumin in pediatric populations represents a gap
in the current knowledge that needs to be addressed.

## Objective
The primary objective is to evaluate the efficacy and safety of curcumin
supplementation in children aged 0-18 with UC.
The secondary objective is to assess adverse event rates.

## Design
This is a systematic review and meta-analysis following PRISMA 2020 guidelines.
The study design was chosen because it provides the highest level of evidence
for synthesizing existing RCT data.

## Population
### Inclusion Criteria
- Children and adolescents aged 0-18 years
- Diagnosed with ulcerative colitis
- Treated with curcumin or Qing Dai

### Exclusion Criteria
- Adult-only studies
- Case reports or case series with n < 5
- Studies without a comparator group

## Methods
A systematic search was conducted in PubMed, Cochrane Library, and Scopus
from inception to April 2023. Risk of bias was assessed using the Cochrane
Risk of Bias 2 tool and Newcastle-Ottawa Scale for observational studies.

### Statistical Analysis
Meta-analysis was performed using random-effects models. Sample size
requirements were based on a power analysis (alpha=0.05, power=80%).
Heterogeneity was assessed using I² statistics. Missing data were
handled using intention to treat analysis.

## Results
Twenty RCTs met the inclusion criteria. Curcumin showed a 30% reduction
in disease activity scores compared to placebo (p<0.05, 95% CI: 15-45%).
Adverse events occurred in 12% of the curcumin group versus 18% in controls.

## Safety
Adverse events were generally mild (GI upset). No serious adverse events
(SAE) were reported. The risk-benefit balance is favorable given the
low risk profile and potential efficacy benefits.

## Ethics
This study was approved by the Hospital Ethics Committee (CEIC).
All included studies had ethics committee approval.
The investigators declare no conflicts of interest.
Funding was provided by an independent research grant.

## Data Protection
Data handling follows RGPD requirements. The data controller is the
principal investigator. Participants' data are pseudonymized.
Data retention period is 15 years per Spanish law. ARCO rights
are guaranteed for all participants.

## Informed Consent
Written informed consent was obtained from all participants' parents.
The patient information sheet was written in plain language.
Assent was obtained from children aged 12-17 years.
Participants could withdraw at any time without consequence.

## Limitations
The search was limited to English-language databases.
Publication bias may affect the results.
Small sample sizes in individual studies limit generalizability.

## Conclusion
Curcumin shows promise as an adjunctive therapy for pediatric UC.
Further larger RCTs are needed to confirm these findings.

## References
[1] Kumar et al. (2017). Curcumin and UC. J Gastroenterol.
[2] Patel et al. (2019). Pediatric IBD. Pediatrics.
"""

_QUALITATIVE_PROTOCOL = """\
## Title
Lived Experiences of Adolescents with Inflammatory Bowel Disease:
A Qualitative Phenomenological Study

## Introduction
Adolescents with IBD face unique challenges that affect their quality
of life, identity, and social relationships. Understanding these lived
experiences is essential for providing patient-centered care.

## Research Question
This study aims to explore and understand the lived experiences of
adolescents diagnosed with IBD, focusing on their perceptions of
disease impact on daily life and coping strategies.

## Methodology
### Paradigm
This study adopts a constructivist paradigm and uses interpretive
phenomenology as the methodological approach.

### Design
Qualitative phenomenological study based on the Heideggerian tradition.

### Participants
Purposive sampling was used to recruit 15-20 adolescents (aged 13-18)
with IBD from a tertiary care centre. Theoretical sampling guided
additional recruitment until data saturation was reached.

### Data Collection
Semi-structured in-depth interviews were conducted using an interview
guide developed from the literature review. Interviews were audio-recorded
and transcribed verbatim. Field notes were taken during observations.
Focus groups were conducted as a supplementary technique.

### Data Analysis
Thematic analysis was performed using NVivo software. Open coding
was followed by axial and selective coding. Two researchers
independently coded the transcripts (intercoder reliability assessed).
Triangulation was achieved through multiple data sources and
member checking was performed with a subset of participants.

### Reflexivity
The principal investigator maintained a reflexivity journal documenting
preconceptions, bracketing, and evolving interpretations. The researcher's
position as a non-IBD individual was acknowledged.

## Ethical Considerations
The study was approved by the Hospital Ethics Committee (CEIm).
Written informed consent was obtained from parents/legal guardians.
Written assent was obtained from all adolescent participants.
Confidentiality was maintained through anonymization of transcripts.
Special attention was given to the vulnerability of minor participants
and the power dynamics in the researcher-participant relationship.

## Results
Five main themes emerged from the analysis: (1) Living with uncertainty,
(2) Social isolation, (3) Identity renegotiation, (4) Coping mechanisms,
(5) Healthcare system navigation. Verbatim quotes illustrate each theme.
Thick description provides context for interpretation.

## Discussion
The findings align with prior qualitative studies on chronic illness
in adolescents. The implications for clinical practice include
the need for psychosocial support programs.

## Transferability
The findings may be transferable to similar adolescent populations
in tertiary care settings. The applicability to primary care contexts
requires further investigation. Recommendations for practice and
policy are provided based on the evidence.

## References
[1] Smith et al. (2020). Qualitative research in IBD. Qual Health Res.
[2] Jones et al. (2019). Adolescent experiences with chronic illness. J Pediatr.
"""

_MINIMAL_PROTOCOL = """\
## Title
A Brief Study on Treatment Outcomes

## Methods
We collected data from patients and analyzed it.

## Results
Treatment was effective in 60% of cases.
"""


# ---------------------------------------------------------------------------
# Tests for classify_study_type
# ---------------------------------------------------------------------------

class TestClassifyStudyType(unittest.TestCase):

    def test_observational_protocol(self):
        self.assertEqual(
            classify_study_type(_OBSERVATIONAL_PROTOCOL),
            StudyType.OBSERVATIONAL
        )

    def test_qualitative_protocol(self):
        self.assertEqual(
            classify_study_type(_QUALITATIVE_PROTOCOL),
            StudyType.QUALITATIVE
        )

    def test_mixed_protocol(self):
        mixed = _OBSERVATIONAL_PROTOCOL + "\n" + _QUALITATIVE_PROTOCOL
        result = classify_study_type(mixed)
        self.assertEqual(result, StudyType.MIXED)

    def test_minimal_defaults_to_observational_or_unknown(self):
        result = classify_study_type(_MINIMAL_PROTOCOL)
        self.assertIn(result, (StudyType.OBSERVATIONAL, StudyType.UNKNOWN))

    def test_empty_text(self):
        result = classify_study_type("")
        self.assertEqual(result, StudyType.UNKNOWN)


# ---------------------------------------------------------------------------
# Tests for _match_heading_to_review_slot
# ---------------------------------------------------------------------------

class TestMatchHeadingToReviewSlot(unittest.TestCase):

    def test_introduction_maps_to_justification(self):
        self.assertEqual(_match_heading_to_review_slot("Introduction"), "justification")

    def test_objective_maps_to_objectives(self):
        self.assertEqual(_match_heading_to_review_slot("Objective"), "objectives")

    def test_methods_maps_to_methods(self):
        self.assertEqual(_match_heading_to_review_slot("Methods"), "methods")

    def test_results_maps_to_results(self):
        self.assertEqual(_match_heading_to_review_slot("Results"), "results")

    def test_conclusion_maps_to_conclusions(self):
        self.assertEqual(_match_heading_to_review_slot("Conclusion"), "conclusions")

    def test_ethics_detection(self):
        self.assertEqual(_match_heading_to_review_slot("Ethical Considerations"), "ethics")

    def test_data_protection(self):
        self.assertEqual(_match_heading_to_review_slot("Data Protection"), "data_protection")

    def test_consent(self):
        self.assertEqual(_match_heading_to_review_slot("Informed Consent"), "consent")

    def test_safety(self):
        self.assertEqual(_match_heading_to_review_slot("Safety"), "safety")

    def test_qualitative_methods(self):
        self.assertEqual(_match_heading_to_review_slot("Reflexivity"), "qualitative_methods")

    def test_spanish_headings(self):
        self.assertEqual(_match_heading_to_review_slot("Introducción"), "justification")
        self.assertEqual(_match_heading_to_review_slot("Métodos"), "methods")
        self.assertEqual(_match_heading_to_review_slot("Protección de Datos"), "data_protection")

    def test_numbered_heading(self):
        self.assertEqual(_match_heading_to_review_slot("5. Methods"), "methods")

    def test_unknown_heading_returns_none(self):
        self.assertIsNone(_match_heading_to_review_slot("Appendix A"))


# ---------------------------------------------------------------------------
# Tests for _detect_keywords
# ---------------------------------------------------------------------------

class TestDetectKeywords(unittest.TestCase):

    def test_finds_present_keywords(self):
        text = "The systematic search of PubMed and Cochrane Library"
        found = _detect_keywords(text, ["systematic", "pubmed", "cochrane"])
        self.assertEqual(len(found), 3)

    def test_case_insensitive(self):
        text = "RGPD compliance is mandatory"
        found = _detect_keywords(text, ["rgpd", "mandatory"])
        self.assertEqual(len(found), 2)

    def test_no_false_positives(self):
        text = "Simple text with no matches"
        found = _detect_keywords(text, ["prisma", "cohort", "randomized"])
        self.assertEqual(len(found), 0)


# ---------------------------------------------------------------------------
# Tests for _extract_strengths / _extract_weaknesses
# ---------------------------------------------------------------------------

class TestStrengthsWeaknesses(unittest.TestCase):

    def test_finds_systematic_review(self):
        strengths = _extract_strengths("This systematic review follows PRISMA guidelines.")
        self.assertTrue(any("sistemática" in s.lower() or "search" in s.lower()
                           for s in strengths))

    def test_finds_prisma_adherence(self):
        strengths = _extract_strengths("The study adheres to PRISMA 2020 guidelines.")
        self.assertTrue(any("guías" in s.lower() or "reporte" in s.lower()
                           for s in strengths))

    def test_finds_limitations(self):
        weaknesses = _extract_weaknesses("Limitations include small sample sizes and potential bias.")
        self.assertTrue(len(weaknesses) > 0, f"Expected weaknesses, got: {weaknesses}")
        labels = " ".join(weaknesses).lower()
        self.assertTrue("limitacion" in labels or "muestral" in labels,
                        f"Expected limitation-related weakness, got: {weaknesses}")

    def test_finds_bias_risk(self):
        weaknesses = _extract_weaknesses("There is a potential risk of selection bias in this study.")
        self.assertTrue(len(weaknesses) > 0, f"Expected weaknesses, got: {weaknesses}")

    def test_empty_text(self):
        self.assertEqual(_extract_strengths(""), [])
        self.assertEqual(_extract_weaknesses(""), [])


# ---------------------------------------------------------------------------
# Tests for _extract_ethical_considerations
# ---------------------------------------------------------------------------

class TestEthicalConsiderations(unittest.TestCase):

    def test_detects_vulnerable_populations(self):
        text = "This study includes pediatric patients and adolescents."
        ethical = _extract_ethical_considerations(text)
        self.assertIn("Poblaciones vulnerables", ethical)

    def test_detects_consent(self):
        text = "Written informed consent was obtained. Assent from minors."
        ethical = _extract_ethical_considerations(text)
        self.assertIn("Consentimiento/Asentimiento", ethical)

    def test_detects_confidentiality(self):
        text = "Data were anonymized to protect confidentiality."
        ethical = _extract_ethical_considerations(text)
        self.assertIn("Confidencialidad", ethical)

    def test_detects_biological_samples(self):
        text = "Blood samples were stored in the institutional biobank."
        ethical = _extract_ethical_considerations(text)
        self.assertIn("Muestras biológicas", ethical)

    def test_empty_text(self):
        ethical = _extract_ethical_considerations("")
        self.assertEqual(len(ethical), 0)


# ---------------------------------------------------------------------------
# Tests for _compute_recommendation
# ---------------------------------------------------------------------------

class TestComputeRecommendation(unittest.TestCase):

    def test_favorable_when_all_pass(self):
        items = [
            ChecklistItem(id="1", category="A", description="Test",
                         critical=True, status="✅"),
            ChecklistItem(id="2", category="A", description="Test2",
                         critical=False, status="✅"),
        ]
        rec, _ = _compute_recommendation(items)
        self.assertEqual(rec, "FAVORABLE")

    def test_revision_mayor_on_critical_fail(self):
        items = [
            ChecklistItem(id="1", category="A", description="Critical thing",
                         critical=True, status="❌"),
            ChecklistItem(id="2", category="A", description="Other",
                         critical=False, status="✅"),
        ]
        rec, _ = _compute_recommendation(items)
        self.assertEqual(rec, "REVISIÓN MAYOR NECESARIA")

    def test_aclaraciones_on_non_critical_fail(self):
        items = [
            ChecklistItem(id="1", category="A", description="Non-critical",
                         critical=False, status="❌"),
            ChecklistItem(id="2", category="A", description="Critical OK",
                         critical=True, status="✅"),
        ]
        rec, _ = _compute_recommendation(items)
        self.assertEqual(rec, "ACLARACIONES REQUERIDAS")

    def test_favorable_con_observaciones(self):
        items = [
            ChecklistItem(id="1", category="A", description="OK",
                         critical=True, status="✅"),
            ChecklistItem(id="2", category="A", description="Partial",
                         critical=False, status="⚠️"),
        ]
        rec, _ = _compute_recommendation(items)
        self.assertEqual(rec, "FAVORABLE CON OBSERVACIONES MENORES")


# ---------------------------------------------------------------------------
# Tests for generate_ceim_review — Observational
# ---------------------------------------------------------------------------

class TestGenerateCEImReviewObservational(unittest.TestCase):

    def setUp(self):
        self.review = generate_ceim_review(_OBSERVATIONAL_PROTOCOL)

    def test_detects_observational_type(self):
        self.assertEqual(self.review.study_type, StudyType.OBSERVATIONAL)

    def test_extracts_title(self):
        self.assertIn("Curcumin", self.review.title)

    def test_has_project_summary(self):
        self.assertGreater(len(self.review.project_summary), 50)
        self.assertIn("Tipo de estudio", self.review.project_summary)

    def test_has_strengths(self):
        self.assertGreater(len(self.review.strengths), 0)

    def test_has_checklist(self):
        self.assertEqual(len(self.review.checklist), 20)

    def test_checklist_has_mixed_statuses(self):
        statuses = {i.status for i in self.review.checklist}
        self.assertTrue(len(statuses) >= 2, "Checklist should have varied statuses")

    def test_ethical_considerations_present(self):
        self.assertGreater(len(self.review.ethical_considerations), 0)

    def test_has_recommendation(self):
        self.assertIn(self.review.recommendation, [
            "FAVORABLE", "FAVORABLE CON OBSERVACIONES MENORES",
            "ACLARACIONES REQUERIDAS", "REVISIÓN MAYOR NECESARIA",
        ])

    def test_recommendation_has_justification(self):
        self.assertGreater(len(self.review.recommendation_justification), 30)

    def test_slot_texts_populated(self):
        self.assertIn("methods", self.review.slot_texts)
        self.assertIn("objectives", self.review.slot_texts)

    def test_no_invented_information(self):
        """Review should only reference things found in the protocol text."""
        for item in self.review.checklist:
            if item.status == "✅":
                # Findings should reference actual keywords found
                self.assertIn("indicador", item.finding.lower())


# ---------------------------------------------------------------------------
# Tests for generate_ceim_review — Qualitative
# ---------------------------------------------------------------------------

class TestGenerateCEImReviewQualitative(unittest.TestCase):

    def setUp(self):
        self.review = generate_ceim_review(_QUALITATIVE_PROTOCOL)

    def test_detects_qualitative_type(self):
        self.assertEqual(self.review.study_type, StudyType.QUALITATIVE)

    def test_uses_caspe_checklist(self):
        ids = [i.id for i in self.review.checklist]
        self.assertTrue(any(i.startswith("Q") for i in ids))

    def test_checklist_has_10_items(self):
        self.assertEqual(len(self.review.checklist), 10)

    def test_reflexivity_assessed(self):
        """CASPe Q6 — reflexivity should be evaluated."""
        q6 = next((i for i in self.review.checklist if i.id == "Q6"), None)
        self.assertIsNotNone(q6)
        # The qualitative protocol has reflexivity section
        self.assertIn(q6.status, ("✅", "⚠️"))

    def test_data_collection_assessed(self):
        """CASPe Q5 — data collection techniques."""
        q5 = next((i for i in self.review.checklist if i.id == "Q5"), None)
        self.assertIsNotNone(q5)

    def test_rigour_assessed(self):
        """CASPe Q8 — rigour of analysis."""
        q8 = next((i for i in self.review.checklist if i.id == "Q8"), None)
        self.assertIsNotNone(q8)

    def test_strengths_include_triangulation(self):
        self.assertTrue(
            any("triangulación" in s.lower() for s in self.review.strengths),
            f"Expected triangulation in strengths, got: {self.review.strengths}"
        )


# ---------------------------------------------------------------------------
# Tests for generate_ceim_review — Mixed
# ---------------------------------------------------------------------------

class TestGenerateCEImReviewMixed(unittest.TestCase):

    def test_mixed_combines_checklists(self):
        mixed_text = _OBSERVATIONAL_PROTOCOL + "\n" + _QUALITATIVE_PROTOCOL
        review = generate_ceim_review(mixed_text)
        self.assertEqual(review.study_type, StudyType.MIXED)
        # Should have both A/B/C/D items AND Q items
        ids = [i.id for i in review.checklist]
        self.assertTrue(any(i.startswith("A") for i in ids))
        self.assertTrue(any(i.startswith("Q") for i in ids))
        self.assertEqual(len(review.checklist), 30)  # 20 + 10


# ---------------------------------------------------------------------------
# Tests for force_study_type override
# ---------------------------------------------------------------------------

class TestForceStudyType(unittest.TestCase):

    def test_force_qualitative_on_observational(self):
        review = generate_ceim_review(
            _OBSERVATIONAL_PROTOCOL,
            force_study_type=StudyType.QUALITATIVE,
        )
        self.assertEqual(review.study_type, StudyType.QUALITATIVE)
        self.assertEqual(len(review.checklist), 10)

    def test_force_observational_on_qualitative(self):
        review = generate_ceim_review(
            _QUALITATIVE_PROTOCOL,
            force_study_type=StudyType.OBSERVATIONAL,
        )
        self.assertEqual(review.study_type, StudyType.OBSERVATIONAL)
        self.assertEqual(len(review.checklist), 20)


# ---------------------------------------------------------------------------
# Tests for render_ceim_review_md
# ---------------------------------------------------------------------------

class TestRenderCEImReviewMd(unittest.TestCase):

    def test_has_all_sections(self):
        review = generate_ceim_review(_OBSERVATIONAL_PROTOCOL)
        md = render_ceim_review_md(review)
        self.assertIn("## 1. Resumen del Proyecto", md)
        self.assertIn("## 2. Adecuación del Tipo de Estudio", md)
        self.assertIn("## 3. Fortalezas Identificadas", md)
        self.assertIn("## 4. Debilidades Metodológicas", md)
        self.assertIn("## 5. Checklist de Evaluación", md)
        self.assertIn("## 6. Consideraciones Éticas", md)
        self.assertIn("## 7. Balance Riesgo-Beneficio", md)
        self.assertIn("## 8. Protección de Datos", md)
        self.assertIn("## 9. Consentimiento / Asentimiento", md)
        self.assertIn("## 10. Muestras Biológicas", md)
        self.assertIn("## 11. Observaciones", md)
        self.assertIn("## 12. Recomendación Global", md)

    def test_has_checklist_table(self):
        review = generate_ceim_review(_OBSERVATIONAL_PROTOCOL)
        md = render_ceim_review_md(review)
        self.assertIn("| Ítem |", md)
        self.assertIn("✅", md)

    def test_has_disclaimer(self):
        review = generate_ceim_review(_OBSERVATIONAL_PROTOCOL)
        md = render_ceim_review_md(review)
        self.assertIn("No constituye un dictamen oficial", md)

    def test_qualitative_mentions_caspe(self):
        review = generate_ceim_review(_QUALITATIVE_PROTOCOL)
        md = render_ceim_review_md(review)
        self.assertIn("CASPe", md)


# ---------------------------------------------------------------------------
# Tests for generate_ceim_review_file
# ---------------------------------------------------------------------------

class TestGenerateCEImReviewFile(unittest.TestCase):

    def test_creates_file(self):
        out = Path("/tmp/test_ceim_review.md")
        out.unlink(missing_ok=True)
        result = generate_ceim_review_file(_OBSERVATIONAL_PROTOCOL, out)
        self.assertTrue(result.exists())
        content = result.read_text()
        self.assertIn("CEIm", content)
        self.assertIn("Recomendación Global", content)

    def test_qualitative_file(self):
        out = Path("/tmp/test_ceim_qualitative.md")
        result = generate_ceim_review_file(_QUALITATIVE_PROTOCOL, out)
        content = result.read_text()
        self.assertIn("CASPe", content)
        self.assertIn("Cualitativo", content)


# ---------------------------------------------------------------------------
# Tests for edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_protocol(self):
        review = generate_ceim_review("")
        self.assertEqual(review.study_type, StudyType.UNKNOWN)
        self.assertGreater(len(review.checklist), 0)
        # All items should be ❌ or N/A
        for item in review.checklist:
            self.assertIn(item.status, ("❌", "N/A"))

    def test_minimal_protocol(self):
        review = generate_ceim_review(_MINIMAL_PROTOCOL)
        self.assertIsNotNone(review.recommendation)
        self.assertGreater(len(review.recommendation_justification), 0)

    def test_does_not_invent_data(self):
        """Review of minimal protocol should flag most items as missing."""
        review = generate_ceim_review(_MINIMAL_PROTOCOL)
        n_fail = sum(1 for i in review.checklist if i.status == "❌")
        # Most items should fail for a minimal protocol
        self.assertGreater(n_fail, len(review.checklist) // 2)


# ---------------------------------------------------------------------------
# Tests for systematic review N/A detection
# ---------------------------------------------------------------------------

_SR_PROTOCOL = """\
## Title
Efficacy of Curcumin in Pediatric UC: A Systematic Review and Meta-Analysis

## Introduction
This systematic review follows PRISMA 2020 guidelines. The protocol
was registered in PROSPERO (CRD42023456789). There is limited evidence
on the use of curcumin in pediatric populations, representing a gap
in current knowledge that needs to be addressed.

## Objectives
The primary objective is to evaluate the efficacy of curcumin.
The primary outcome is clinical remission rate.

## Methods
### Search Strategy
A systematic search was conducted in PubMed, Cochrane, and Scopus.
Eligibility criteria were pre-defined. Studies were screened
by two independent reviewers. Risk of bias was assessed using
the Cochrane Risk of Bias 2 tool.

### Statistical Analysis
Meta-analysis was performed with random-effects models.
Heterogeneity was assessed using I² statistics.

## Results
Twelve RCTs met the inclusion criteria.

## Discussion
The findings suggest curcumin may be beneficial.

## Limitations
Limited number of studies. Publication bias possible.

## Conclusions
More research is needed.
"""


class TestIsSystematicReview(unittest.TestCase):

    def test_sr_detected(self):
        self.assertTrue(_is_systematic_review(_SR_PROTOCOL))

    def test_qualitative_not_sr(self):
        self.assertFalse(_is_systematic_review(_QUALITATIVE_PROTOCOL))

    def test_minimal_not_sr(self):
        self.assertFalse(_is_systematic_review(_MINIMAL_PROTOCOL))


class TestSRNAItems(unittest.TestCase):

    def test_sr_marks_na_on_inapplicable_items(self):
        review = generate_ceim_review(_SR_PROTOCOL)
        na_ids = {i.id for i in review.checklist if i.status == "N/A"}
        # B2 (sample size), C1 (consent), C2 (HIP), C3 (RGPD),
        # C4 (insurance), D1 (monitoring), D2 (stopping), D4 (samples)
        for expected_na in ["B2", "C1", "C2", "C3", "C4", "D1", "D2", "D4"]:
            self.assertIn(expected_na, na_ids,
                         f"{expected_na} should be N/A for systematic review")

    def test_sr_keeps_applicable_items(self):
        review = generate_ceim_review(_SR_PROTOCOL)
        # A2, A3, A4, B1 should NOT be N/A
        na_ids = {i.id for i in review.checklist if i.status == "N/A"}
        for should_stay in ["A2", "A3", "A4", "B1"]:
            self.assertNotIn(should_stay, na_ids,
                            f"{should_stay} should still be evaluated for SR")

    def test_sr_prospero_detected(self):
        """PROSPERO registration should make A1 non-failing."""
        review = generate_ceim_review(_SR_PROTOCOL)
        a1 = next(i for i in review.checklist if i.id == "A1")
        self.assertNotEqual(a1.status, "❌",
                           f"A1 should detect PROSPERO, got: {a1.status}")

    def test_sr_recommendation_improves(self):
        """SR should get better recommendation than REVISIÓN MAYOR."""
        review = generate_ceim_review(_SR_PROTOCOL)
        self.assertNotEqual(review.recommendation, "REVISIÓN MAYOR NECESARIA",
                           f"SR should not get worst recommendation")

    def test_non_sr_not_affected(self):
        """Non-SR protocols should not get N/A items from SR logic."""
        review = generate_ceim_review(_QUALITATIVE_PROTOCOL)
        na_ids = {i.id for i in review.checklist if i.status == "N/A"}
        # Qualitative checklist has Q-items, no A/B/C/D items to mark N/A
        sr_na_in_result = na_ids & _SR_NA_ITEMS
        self.assertEqual(len(sr_na_in_result), 0)


# ---------------------------------------------------------------------------
# Tests for negation detection
# ---------------------------------------------------------------------------

class TestNegationDetection(unittest.TestCase):

    def test_spanish_negation(self):
        text = "No se obtuvo consentimiento informado de los participantes."
        self.assertTrue(_is_negated(text, "consentimiento informado"))

    def test_spanish_sin(self):
        text = "El estudio se realizó sin la aprobación del comité de ética."
        self.assertTrue(_is_negated(text, "aprobación"))

    def test_english_not(self):
        text = "Informed consent was not obtained from participants."
        self.assertTrue(_is_negated(text, "informed consent"))

    def test_english_without(self):
        text = "The study proceeded without ethical approval."
        self.assertTrue(_is_negated(text, "ethical"))

    def test_non_negated_positive(self):
        text = "Written informed consent was obtained from all participants."
        self.assertFalse(_is_negated(text, "informed consent"))

    def test_mixed_positive_and_negative(self):
        """If keyword appears both negated and non-negated, it's non-negated."""
        text = ("Initially, consent was not obtained. "
                "Later, informed consent was obtained from all participants.")
        self.assertFalse(_is_negated(text, "consent"))

    def test_absence_of(self):
        text = "The absence of data protection measures is concerning."
        self.assertTrue(_is_negated(text, "data protection"))

    def test_negation_affects_detect_keywords(self):
        """_detect_keywords should exclude negated keywords."""
        text = "No se obtuvo consentimiento informado. El diseño es observacional."
        found = _detect_keywords(text, ["consentimiento informado", "observacional"])
        self.assertIn("observacional", found)
        self.assertNotIn("consentimiento informado", found)

    def test_detect_keywords_keeps_non_negated(self):
        text = "Se obtuvo consentimiento informado de todos los participantes."
        found = _detect_keywords(text, ["consentimiento informado"])
        self.assertIn("consentimiento informado", found)


if __name__ == "__main__":
    unittest.main()
